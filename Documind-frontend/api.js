/**
 * DocuMind Frontend API Client (Phase 1 Secure Integration)
 * - Zero client-side API secrets.
 * - Automatic session isolation token management via sessionStorage.
 * - Centralized configuration, timeouts, and structured error handling.
 */

(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  if (typeof root !== "undefined") {
    root.DocuMindAPI = api;
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const DEFAULT_TIMEOUT_MS = 35000;

  function getBaseUrl() {
    if (typeof window !== "undefined" && window.DOCUMIND_API_URL) {
      return window.DOCUMIND_API_URL.replace(/\/+$/, "");
    }
    // If running in browser and protocol is http/https, default to origin or local API
    if (typeof window !== "undefined" && window.location && window.location.origin) {
      if (window.location.port === "5500") {
        return "http://127.0.0.1:8000";
      }
      return window.location.origin;
    }
    return "http://127.0.0.1:8000";
  }

  let _sessionPromise = null;

  function getSessionId() {
    if (typeof window === "undefined" || !window.sessionStorage) {
      return null;
    }
    return window.sessionStorage.getItem("documind_session_id") || null;
  }

  async function initSession(forceNew = false) {
    if (!forceNew && typeof window !== "undefined" && window.sessionStorage) {
      const existing = window.sessionStorage.getItem("documind_session_id");
      if (existing && existing.length >= 16) {
        return existing;
      }
    }
    if (!forceNew && _sessionPromise) {
      return _sessionPromise;
    }

    _sessionPromise = (async () => {
      try {
        const baseUrl = getBaseUrl();
        const res = await fetch(`${baseUrl}/api/demo/session`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
        });
        if (res.ok) {
          const data = await res.json();
          if (data && data.session_id) {
            if (typeof window !== "undefined" && window.sessionStorage) {
              window.sessionStorage.setItem("documind_session_id", data.session_id);
            }
            return data.session_id;
          }
        }
        const errData = await res.json().catch(() => ({}));
        const errMsg = (errData.error && errData.error.message) || errData.detail || `Session creation failed with HTTP ${res.status}`;
        const err = new Error(errMsg);
        err.status = res.status;
        err.code = (errData.error && errData.error.code) || "SESSION_INIT_FAILED";
        throw err;
      } finally {
        _sessionPromise = null;
      }
    })();

    return _sessionPromise;
  }

  async function request(endpoint, options = {}) {
    const baseUrl = getBaseUrl();
    const url = `${baseUrl}${endpoint}`;
    const timeoutMs = options.timeoutMs || DEFAULT_TIMEOUT_MS;

    let sid = getSessionId();
    if (!sid && endpoint !== "/api/demo/session" && endpoint !== "/healthz") {
      try {
        sid = await initSession();
      } catch (sessErr) {
        // If session init fails, proceed to attempt request or bubble error
      }
    }

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

    const headers = new Headers(options.headers || {});
    if (sid && !headers.has("X-Session-ID")) {
      headers.set("X-Session-ID", sid);
    }

    const fetchOptions = {
      method: options.method || "GET",
      headers: headers,
      signal: controller.signal,
    };

    if (options.body) {
      fetchOptions.body = options.body;
    }

    try {
      const res = await fetch(url, fetchOptions);
      clearTimeout(timeoutId);

      if (res.status === 401 && !options._retried) {
        try {
          const newSid = await initSession(true);
          const retryHeaders = new Headers(options.headers || {});
          retryHeaders.set("X-Session-ID", newSid);
          return request(endpoint, { ...options, headers: retryHeaders, _retried: true });
        } catch (retryErr) {
          // let normal error handler process the 401 response
        }
      }

      if (res.status === 204) {
        return null;
      }

      const contentType = res.headers.get("content-type") || "";
      let data = null;
      if (contentType.includes("application/json")) {
        data = await res.json();
      } else {
        const text = await res.text();
        try {
          data = JSON.parse(text);
        } catch {
          data = text;
        }
      }

      if (!res.ok) {
        const errObj = (data && data.error) || {};
        const code = errObj.code || `HTTP_${res.status}`;
        let message = errObj.message || data.detail || (typeof data === "string" ? data : `Request failed with HTTP ${res.status}`);
        const retryAfter = res.headers.get("Retry-After");
        if (res.status === 429 && retryAfter) {
          message += ` (Retry after ${retryAfter}s)`;
        }
        const err = new Error(message);
        err.type = "server_error";
        err.code = code;
        err.status = res.status;
        err.retryAfter = retryAfter;
        err.requestId = errObj.request_id || res.headers.get("X-Request-ID");
        throw err;
      }

      return data;
    } catch (err) {
      clearTimeout(timeoutId);
      if (err.type === "server_error") {
        throw err;
      }
      if (err.name === "AbortError") {
        const timeoutErr = new Error(`Request timed out after ${timeoutMs}ms`);
        timeoutErr.type = "network_error";
        timeoutErr.code = "TIMEOUT";
        timeoutErr.status = 408;
        throw timeoutErr;
      }
      if (err instanceof TypeError || (err.message && err.message.toLowerCase().includes("fetch"))) {
        const netErr = new Error("Cannot reach DocuMind server. Check connection or CORS.");
        netErr.type = "network_error";
        netErr.code = "NETWORK_ERROR";
        throw netErr;
      }
      err.type = "client_error";
      throw err;
    }
  }

  const API = {
    getBaseUrl,
    getSessionId,

    resetSession() {
      if (typeof window !== "undefined" && window.sessionStorage) {
        window.sessionStorage.removeItem("documind_session_id");
      }
      return getSessionId();
    },

    async getHealth() {
      return request("/healthz");
    },

    async getDocuments() {
      return request("/api/demo/documents");
    },

    async uploadDocument(file, replace = false) {
      const formData = new FormData();
      formData.append("file", file);
      const query = replace ? "?replace=true" : "";
      return request(`/api/demo/documents${query}`, {
        method: "POST",
        body: formData,
        timeoutMs: 60000,
      });
    },

    async deleteDocument(source) {
      return request(`/api/demo/documents/${encodeURIComponent(source)}`, {
        method: "DELETE",
      });
    },

    async getDocumentChunks(source) {
      return request(`/api/demo/documents/${encodeURIComponent(source)}/chunks`);
    },

    async askQuestion(question, topK = 5) {
      let q = question;
      let k = topK;
      if (typeof question === "object" && question !== null) {
        q = question.question;
        k = question.top_k || topK;
      }
      return request("/api/demo/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q, top_k: k }),
        timeoutMs: 45000,
      });
    },

    async analyze(action, source = null) {
      let body = {};
      if (typeof action === "object" && action !== null) {
        body = action;
      } else {
        body = { action };
        if (source) body.source = source;
      }
      return request("/api/demo/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        timeoutMs: 45000,
      });
    },

    async getEvents() {
      return request("/api/demo/events");
    },

    async getMeta() {
      return request("/api/demo/meta");
    },

    async listConversations() {
      return request("/api/demo/conversations");
    },

    async getConversationMessages(conversationId) {
      return request(`/api/demo/conversations/${encodeURIComponent(conversationId)}/messages`);
    },

    async deleteConversation(conversationId) {
      return request(`/api/demo/conversations/${encodeURIComponent(conversationId)}`, {
        method: "DELETE",
      });
    },

    async chat(question, conversationId = null, topK = 5) {
      return request("/api/demo/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question,
          conversation_id: conversationId,
          top_k: topK,
        }),
        timeoutMs: 45000,
      });
    },

    async chatStream(question, conversationId = null, onEvent = null, options = {}) {
      const baseUrl = getBaseUrl();
      const url = `${baseUrl}/api/demo/chat/stream`;
      const timeoutMs = options.timeoutMs || 60000;
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

      const headers = new Headers(options.headers || {});
      headers.set("Content-Type", "application/json");
      if (!headers.has("X-Session-ID")) {
        headers.set("X-Session-ID", getSessionId());
      }

      try {
        const res = await fetch(url, {
          method: "POST",
          headers: headers,
          body: JSON.stringify({
            question: question,
            conversation_id: conversationId || null,
            top_k: options.topK || 5,
          }),
          signal: controller.signal,
        });

        if (!res.ok) {
          clearTimeout(timeoutId);
          if (res.status === 401 && !options._retried) {
            const newSid = await initSession(true);
            const retryHeaders = new Headers(options.headers || {});
            retryHeaders.set("X-Session-ID", newSid);
            return this.chatStream(question, conversationId, onEvent, {
              ...options,
              headers: retryHeaders,
              _retried: true,
            });
          }
          const errData = await res.json().catch(() => ({}));
          const err = new Error(errData.detail || `Stream failed with HTTP ${res.status}`);
          err.status = res.status;
          throw err;
        }

        if (!res.body) {
          clearTimeout(timeoutId);
          throw new Error("ReadableStream not supported by browser");
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder("utf-8");
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const parts = buffer.split("\n\n");
          buffer = parts.pop() || "";

          for (const part of parts) {
            if (!part.trim()) continue;
            const lines = part.trim().split("\n");
            let eventName = null;
            let eventData = null;
            for (const line of lines) {
              if (line.startsWith("event: ")) {
                eventName = line.substring(7).trim();
              } else if (line.startsWith("data: ")) {
                try {
                  eventData = JSON.parse(line.substring(6).trim());
                } catch {
                  eventData = line.substring(6).trim();
                }
              }
            }
            if (eventName && onEvent) {
              onEvent(eventName, eventData);
            }
          }
        }
        clearTimeout(timeoutId);
      } catch (err) {
        clearTimeout(timeoutId);
        throw err;
      }
    },

    async initSession(forceNew = false) {
      return initSession(forceNew);
    },

    async newSession() {
      if (typeof window !== "undefined" && window.sessionStorage) {
        window.sessionStorage.removeItem("documind_session_id");
      }
      return initSession(true);
    },

    async register(email, password, claimGuest = true, displayName = null) {
      const guestSid = claimGuest ? getSessionId() : null;
      return request("/api/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email,
          password,
          display_name: displayName,
          claim_guest_session: guestSid,
        }),
      });
    },

    async login(email, password, claimGuest = true) {
      const guestSid = claimGuest ? getSessionId() : null;
      return request("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email,
          password,
          claim_guest_session: guestSid,
        }),
      });
    },

    async logout() {
      return request("/api/auth/logout", {
        method: "POST",
      });
    },

    async requestPasswordReset(email) {
      return request("/api/auth/password-reset/request", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
    },

    async confirmPasswordReset(token, newPassword) {
      return request("/api/auth/password-reset/confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, new_password: newPassword }),
      });
    },

    getGoogleAuthUrl(redirect = null) {
      const target = redirect || (typeof window !== "undefined" ? window.location.href : "/app/console/code.html");
      return `${getBaseUrl()}/api/auth/google/authorize?redirect=${encodeURIComponent(target)}`;
    },

    async getEvals() {
      try {
        return await request("/api/demo/evals", { method: "GET" });
      } catch (e) {
        return null;
      }
    },

    async getAuthUser() {
      try {
        return await request("/api/auth/me", { method: "GET" });
      } catch (e) {
        return { authenticated: false, user: null };
      }
    },
  };

  // UI Formatters and helpers
  API.fmtMs = function (n) {
    return n != null ? `${Math.round(n)}ms` : "—";
  };

  API.fmtInr = function (n) {
    return n != null ? `₹${n.toFixed(4)}` : "—";
  };

  API.setStatusDot = function (el, color, label) {
    if (!el) return;
    el.innerHTML = `<span class="w-1.5 h-1.5 rounded-full bg-${color} inline-block"></span><span class="font-code-sm text-code-sm text-on-surface tracking-wider uppercase">${label}</span>`;
  };

  API.showError = function (el, msg) {
    API.setStatusDot(el, "error", msg);
  };

  // Backwards compatibility globals
  if (typeof window !== "undefined") {
    window.getJSON = (path) => request(path);
    window.postJSON = (path, body) => request(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    window.uploadFile = (path, file) => {
      const formData = new FormData();
      formData.append("file", file);
      return request(path, { method: "POST", body: formData });
    };
    window.deleteReq = (path) => request(path, { method: "DELETE" });
    window.fmtMs = API.fmtMs;
    window.fmtInr = API.fmtInr;
    window.setStatusDot = API.setStatusDot;
    window.showError = API.showError;
  }

  API.formatError = function (err) {
    if (!err) return { code: "ERROR", message: "Unknown error occurred" };
    if (err.type === "server_error") {
      let msg = err.message || "Server error";
      return { code: err.code || `HTTP ${err.status}`, message: msg };
    }
    if (err.type === "network_error") {
      return { code: err.code || "NETWORK", message: err.message || "Cannot reach server" };
    }
    console.error("Frontend exception:", err);
    return { code: "FRONTEND_ERROR", message: err.message || "Frontend execution error" };
  };

  // User Authentication Modal & Avatar binding
  function openAuthModal(currentUser) {
    let existing = document.getElementById("documind-auth-modal");
    if (existing) existing.remove();

    const overlay = document.createElement("div");
    overlay.id = "documind-auth-modal";
    overlay.className = "fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-sm p-4";

    let modalHtml = "";
    if (currentUser) {
      modalHtml = `
        <div class="bg-surface-container border border-surface-variant rounded-2xl p-6 shadow-2xl max-w-sm w-full flex flex-col gap-4 text-on-surface">
          <div class="flex items-center justify-between pb-2 border-b border-surface-variant">
            <div class="flex items-center gap-2">
              <span class="material-symbols-outlined text-primary">account_circle</span>
              <span class="font-headline-sm text-sm font-semibold text-on-surface">ACCOUNT PROFILE</span>
            </div>
            <button id="auth-modal-close" class="text-on-surface-variant hover:text-on-surface p-1 cursor-pointer">✕</button>
          </div>
          <div class="flex flex-col gap-1 py-2">
            <span class="font-code-sm text-[11px] text-on-surface-variant uppercase tracking-wider">Signed in as:</span>
            <span class="font-body-sm font-medium text-on-surface break-all">${currentUser.email}</span>
            <span class="font-code-sm text-[10px] text-on-surface-variant/70">ID: ${currentUser.id}</span>
          </div>
          <div class="bg-surface-container-low p-3 rounded-xl border border-surface-variant/40 flex flex-col gap-1 font-code-sm text-[11px] text-on-surface-variant">
            <span class="text-tertiary flex items-center gap-1 font-semibold">● Persistent Workspace Active</span>
            <span>Your indexed documents and conversations are saved and isolated in your private vault.</span>
          </div>
          <div class="pt-2 flex items-center justify-end gap-2 border-t border-surface-variant">
            <button id="btn-auth-logout" class="px-4 py-2 rounded-xl bg-error/15 text-error hover:bg-error/25 font-code-sm text-xs font-medium transition-colors cursor-pointer">
              SIGN OUT
            </button>
          </div>
        </div>
      `;
    } else {
      modalHtml = `
        <div class="bg-surface-container border border-surface-variant rounded-2xl p-6 shadow-2xl max-w-sm w-full flex flex-col gap-4 text-on-surface">
          <div class="flex items-center justify-between pb-2 border-b border-surface-variant">
            <div class="flex items-center gap-2">
              <span class="material-symbols-outlined text-primary">lock</span>
              <span class="font-headline-sm text-sm font-semibold text-on-surface">DOCUMIND ACCOUNT</span>
            </div>
            <button id="auth-modal-close" class="text-on-surface-variant hover:text-on-surface p-1 cursor-pointer">✕</button>
          </div>
          <!-- Tabs -->
          <div class="flex bg-surface-container-low rounded-xl p-1 border border-surface-variant">
            <button id="tab-auth-login" class="flex-1 py-1.5 rounded-lg text-xs font-code-sm font-semibold transition-colors bg-surface-container-high text-primary shadow-sm cursor-pointer">SIGN IN</button>
            <button id="tab-auth-register" class="flex-1 py-1.5 rounded-lg text-xs font-code-sm font-semibold transition-colors text-on-surface-variant hover:text-on-surface cursor-pointer">REGISTER</button>
          </div>
          <div id="auth-error-box" class="hidden p-2.5 rounded-lg bg-error/15 border border-error/30 text-error font-code-sm text-[11px] leading-tight"></div>
          <form id="auth-form" class="flex flex-col gap-3">
            <div class="flex flex-col gap-1">
              <label class="font-code-sm text-[10px] text-on-surface-variant uppercase tracking-wider">Email Address</label>
              <input id="auth-input-email" type="email" required placeholder="you@domain.com" class="w-full bg-surface-container-lowest border border-surface-variant rounded-xl px-3 py-2 text-sm text-on-surface outline-none focus:border-primary transition-colors font-body-sm" />
            </div>
            <div class="flex flex-col gap-1">
              <label class="font-code-sm text-[10px] text-on-surface-variant uppercase tracking-wider">Password (min 10 chars)</label>
              <input id="auth-input-password" type="password" required minlength="10" placeholder="••••••••••" class="w-full bg-surface-container-lowest border border-surface-variant rounded-xl px-3 py-2 text-sm text-on-surface outline-none focus:border-primary transition-colors font-body-sm" />
            </div>
            <label class="flex items-start gap-2 pt-1 cursor-pointer">
              <input id="auth-input-migrate" type="checkbox" checked class="mt-0.5 rounded border-surface-variant text-primary focus:ring-0" />
              <span class="font-code-sm text-[11px] text-on-surface-variant leading-tight">Move current guest session documents into my account</span>
            </label>
            <button id="btn-auth-submit" type="submit" class="mt-2 w-full py-2.5 rounded-xl bg-primary-container text-on-primary-container hover:bg-inverse-primary font-code-sm text-xs font-bold tracking-wider uppercase transition-colors cursor-pointer shadow-sm">
              SIGN IN
            </button>
          </form>
        </div>
      `;
    }

    overlay.innerHTML = modalHtml;
    document.body.appendChild(overlay);

    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) overlay.remove();
    });

    const closeBtn = overlay.querySelector("#auth-modal-close");
    if (closeBtn) closeBtn.addEventListener("click", () => overlay.remove());

    if (currentUser) {
      const logoutBtn = overlay.querySelector("#btn-auth-logout");
      if (logoutBtn) {
        logoutBtn.addEventListener("click", async () => {
          logoutBtn.disabled = true;
          logoutBtn.textContent = "SIGNING OUT…";
          await API.logout();
          window.location.reload();
        });
      }
    } else {
      let isRegisterMode = false;
      const tabLogin = overlay.querySelector("#tab-auth-login");
      const tabRegister = overlay.querySelector("#tab-auth-register");
      const submitBtn = overlay.querySelector("#btn-auth-submit");
      const form = overlay.querySelector("#auth-form");
      const errorBox = overlay.querySelector("#auth-error-box");
      const emailInput = overlay.querySelector("#auth-input-email");
      const passwordInput = overlay.querySelector("#auth-input-password");
      const migrateCheck = overlay.querySelector("#auth-input-migrate");

      tabLogin.addEventListener("click", () => {
        isRegisterMode = false;
        tabLogin.className = "flex-1 py-1.5 rounded-lg text-xs font-code-sm font-semibold transition-colors bg-surface-container-high text-primary shadow-sm cursor-pointer";
        tabRegister.className = "flex-1 py-1.5 rounded-lg text-xs font-code-sm font-semibold transition-colors text-on-surface-variant hover:text-on-surface cursor-pointer";
        submitBtn.textContent = "SIGN IN";
        errorBox.classList.add("hidden");
      });

      tabRegister.addEventListener("click", () => {
        isRegisterMode = true;
        tabRegister.className = "flex-1 py-1.5 rounded-lg text-xs font-code-sm font-semibold transition-colors bg-surface-container-high text-primary shadow-sm cursor-pointer";
        tabLogin.className = "flex-1 py-1.5 rounded-lg text-xs font-code-sm font-semibold transition-colors text-on-surface-variant hover:text-on-surface cursor-pointer";
        submitBtn.textContent = "CREATE ACCOUNT";
        errorBox.classList.add("hidden");
      });

      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        errorBox.classList.add("hidden");
        const email = emailInput.value.trim();
        const password = passwordInput.value;
        const migrate = migrateCheck ? migrateCheck.checked : false;

        if (password.length < 10) {
          errorBox.textContent = "Password must be at least 10 characters long.";
          errorBox.classList.remove("hidden");
          return;
        }

        submitBtn.disabled = true;
        submitBtn.textContent = "PLEASE WAIT…";

        try {
          if (isRegisterMode) {
            await API.register(email, password, migrate);
          } else {
            await API.login(email, password, migrate);
          }
          overlay.remove();
          window.location.reload();
        } catch (err) {
          submitBtn.disabled = false;
          submitBtn.textContent = isRegisterMode ? "CREATE ACCOUNT" : "SIGN IN";
          errorBox.textContent = err.message || "Authentication failed. Please check credentials.";
          errorBox.classList.remove("hidden");
        }
      });
    }
  }

  function bindAuthUI() {
    const avatarBtns = document.querySelectorAll("header .rounded-full.bg-primary, #header-user-avatar");
    if (!avatarBtns.length) return;

    let currentUser = null;

    API.getAuthUser().then((res) => {
      if (res && res.authenticated && res.user) {
        currentUser = res.user;
        avatarBtns.forEach((btn) => {
          btn.setAttribute("title", `Signed in as ${res.user.email}`);
          btn.classList.add("cursor-pointer", "ring-2", "ring-primary");
          const initials = (res.user.display_name || res.user.email).slice(0, 2).toUpperCase();
          btn.innerHTML = `<span class="font-code-sm text-[12px] font-bold text-on-primary uppercase">${initials}</span>`;
        });
      } else {
        avatarBtns.forEach((btn) => {
          btn.setAttribute("title", "Sign in / Register");
          btn.classList.add("cursor-pointer");
        });
      }
    });

    avatarBtns.forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        if (currentUser) {
          openAuthModal(currentUser);
        } else {
          window.location.href = `/app/auth.html?redirect=${encodeURIComponent(window.location.href)}`;
        }
      });
    });
  }

  // Cross-view Navigation handler
  function bindNavigation() {
    const pathMap = {
      chat: "../chat.html",
      architecture: "../architecture/code.html",
      console: "../console/code.html",
      proof: "../proof/code.html",
      library: "../library/code.html",
      benchmarks: "../proof/code.html",
      compliance: "../proof/code.html",
    };
    document.querySelectorAll("[data-path]").forEach((el) => {
      const target = pathMap[el.getAttribute("data-path")];
      if (target) {
        el.addEventListener("click", (e) => {
          e.preventDefault();
          window.location.href = target;
        });
      }
    });
  }

  if (typeof document !== "undefined") {
    function initUI() {
      bindNavigation();
      bindAuthUI();
    }
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", initUI);
    } else {
      initUI();
    }
  }

  return API;
});

