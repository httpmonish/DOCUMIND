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

  function getAuthToken() {
    if (typeof window === "undefined") return null;
    try {
      return (window.localStorage && window.localStorage.getItem("documind_auth_token")) ||
             (window.sessionStorage && window.sessionStorage.getItem("documind_auth_token")) || null;
    } catch (_) {
      return null;
    }
  }

  function setAuthToken(token) {
    if (typeof window === "undefined") return;
    try {
      if (token) {
        if (window.localStorage) window.localStorage.setItem("documind_auth_token", token);
        if (window.sessionStorage) window.sessionStorage.setItem("documind_auth_token", token);
      } else {
        if (window.localStorage) window.localStorage.removeItem("documind_auth_token");
        if (window.sessionStorage) window.sessionStorage.removeItem("documind_auth_token");
      }
    } catch (_) {}
  }

  function getBaseUrl() {
    if (typeof window !== "undefined" && window.DOCUMIND_API_URL) {
      return window.DOCUMIND_API_URL.replace(/\/+$/, "");
    }
    // If running in browser and protocol is http/https, default to origin or local API
    if (typeof window !== "undefined" && window.location && window.location.origin && window.location.origin !== "null") {
      if (window.location.port === "5500") {
        return "http://127.0.0.1:8000";
      }
      return window.location.origin;
    }
    return "http://127.0.0.1:8000";
  }

  let _sessionPromise = null;

  function getSessionId() {
    if (typeof window === "undefined") {
      return null;
    }
    try {
      if (window.sessionStorage) {
        const sid = window.sessionStorage.getItem("documind_session_id");
        if (sid && sid.length >= 16) return sid;
      }
      if (window.localStorage) {
        const sid = window.localStorage.getItem("documind_session_id");
        if (sid && sid.length >= 16) {
          if (window.sessionStorage) window.sessionStorage.setItem("documind_session_id", sid);
          return sid;
        }
      }
    } catch (_) {}
    return null;
  }

  async function initSession(forceNew = false) {
    if (!forceNew) {
      const existing = getSessionId();
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
          credentials: "include",
        });
        if (res.ok) {
          const data = await res.json();
          if (data && data.session_id) {
            try {
              if (window.sessionStorage) window.sessionStorage.setItem("documind_session_id", data.session_id);
              if (window.localStorage) window.localStorage.setItem("documind_session_id", data.session_id);
            } catch (_) {}
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
    const authToken = getAuthToken();
    if (!sid && !authToken && endpoint !== "/api/demo/session" && endpoint !== "/healthz") {
      try {
        sid = await initSession();
      } catch (sessErr) {
        // If session init fails, proceed to attempt request or bubble error
      }
    }

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

    const headers = new Headers(options.headers || {});
    if (authToken && !headers.has("Authorization")) {
      headers.set("Authorization", `Bearer ${authToken}`);
    }
    if (sid && !headers.has("X-Session-ID")) {
      headers.set("X-Session-ID", sid);
    }

    const fetchOptions = {
      method: options.method || "GET",
      headers: headers,
      credentials: "include",
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
      if (typeof window !== "undefined") {
        try {
          if (window.sessionStorage) window.sessionStorage.removeItem("documind_session_id");
          if (window.localStorage) window.localStorage.removeItem("documind_session_id");
        } catch (_) {}
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
      try {
        const auth = await API.getAuthUser();
        if (!auth || !auth.authenticated) {
          showAuthRequiredModal({
            title: "Authentication Required",
            message: "You should first login or register before uploading documents.",
          });
          const err = new Error("Authentication required. Please sign in or register to upload documents.");
          err.type = "client_error";
          err.code = "AUTH_REQUIRED";
          err.status = 401;
          throw err;
        }
      } catch (authErr) {
        if (authErr.code === "AUTH_REQUIRED") throw authErr;
        showAuthRequiredModal({
          title: "Authentication Required",
          message: "You should first login or register before uploading documents.",
        });
        const err = new Error("Authentication required. Please sign in or register to upload documents.");
        err.type = "client_error";
        err.code = "AUTH_REQUIRED";
        err.status = 401;
        throw err;
      }

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

    async getRecentDocuments(limit = 10) {
      return request(`/api/demo/documents/recent?limit=${encodeURIComponent(limit)}`);
    },

    async getDocument(source) {
      return request(`/api/demo/documents/${encodeURIComponent(source)}`);
    },

    async renameDocument(source, displayName) {
      return request(`/api/demo/documents/${encodeURIComponent(source)}/rename`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ display_name: displayName }),
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

    async createConversation(title = "New Conversation", documentId = null) {
      return request("/api/demo/conversations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, document_id: documentId }),
      });
    },

    async getConversation(conversationId) {
      return request(`/api/demo/conversations/${encodeURIComponent(conversationId)}`);
    },

    async renameConversation(conversationId, title) {
      return request(`/api/demo/conversations/${encodeURIComponent(conversationId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      });
    },

    async archiveConversation(conversationId) {
      return request(`/api/demo/conversations/${encodeURIComponent(conversationId)}/archive`, {
        method: "POST",
      });
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

      let sid = getSessionId();
      const authToken = getAuthToken();
      if (!sid && !authToken) {
        try {
          sid = await initSession();
        } catch (_) {}
      }

      const headers = new Headers(options.headers || {});
      headers.set("Content-Type", "application/json");
      if (authToken && !headers.has("Authorization")) {
        headers.set("Authorization", `Bearer ${authToken}`);
      }
      if (sid && !headers.has("X-Session-ID")) {
        headers.set("X-Session-ID", sid);
      }

      try {
        const res = await fetch(url, {
          method: "POST",
          headers: headers,
          credentials: "include",
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
      if (typeof window !== "undefined") {
        try {
          if (window.sessionStorage) window.sessionStorage.removeItem("documind_session_id");
          if (window.localStorage) window.localStorage.removeItem("documind_session_id");
        } catch (_) {}
      }
      return initSession(true);
    },

    async register(email, password, claimGuest = true, displayName = null) {
      const guestSid = claimGuest ? getSessionId() : null;
      const res = await request("/api/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email,
          password,
          display_name: displayName,
          claim_guest_session: guestSid,
        }),
      });
      if (res && res.token) {
        setAuthToken(res.token);
      }
      return res;
    },

    async login(email, password, claimGuest = true) {
      const guestSid = claimGuest ? getSessionId() : null;
      const res = await request("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email,
          password,
          claim_guest_session: guestSid,
        }),
      });
      if (res && res.token) {
        setAuthToken(res.token);
      }
      return res;
    },

    async logout() {
      try {
        return await request("/api/auth/logout", {
          method: "POST",
        });
      } finally {
        setAuthToken(null);
      }
    },

    async getProfile() {
      return request("/api/auth/profile");
    },

    async updateProfile(data = {}) {
      return request("/api/auth/profile", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          display_name: data.displayName || data.display_name,
          avatar_url: data.avatarUrl || data.avatar_url,
        }),
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

  function escapeHtml(str) {
    if (!str) return "";
    return String(str).replace(/[&<>"']/g, function (m) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[m];
    });
  }

  function showAuthRequiredModal(options = {}) {
    if (typeof document === "undefined") return;
    let existing = document.getElementById("documind-auth-required-modal");
    if (existing) existing.remove();

    const title = options.title || "Authentication Required";
    const message = options.message || "You should first login or register before uploading documents or accessing the chat.";
    const redirectUrl = options.redirectUrl || `/app/auth.html?reason=auth_required&redirect=${encodeURIComponent(window.location.href)}`;

    const overlay = document.createElement("div");
    overlay.id = "documind-auth-required-modal";
    overlay.style.cssText = `
      position: fixed;
      inset: 0;
      z-index: 999999;
      display: flex;
      align-items: center;
      justify-content: center;
      background: rgba(0, 0, 0, 0.8);
      backdrop-filter: blur(6px);
      padding: 16px;
      font-family: 'JetBrains Mono', monospace;
    `;

    overlay.innerHTML = `
      <div style="background: #191818; border: 1px solid rgba(255, 87, 29, 0.45); border-radius: 14px; max-width: 440px; width: 100%; padding: 24px; box-shadow: 0 20px 45px rgba(0,0,0,0.85); display: flex; flex-direction: column; gap: 16px; color: #e5e2e1; position: relative;">
        <div style="display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid #2d2c2c; padding-bottom: 12px;">
          <div style="display: flex; align-items: center; gap: 10px;">
            <div style="width: 28px; height: 28px; border-radius: 6px; background: rgba(255,87,29,0.15); border: 1px solid #ff571d; display: flex; align-items: center; justify-content: center; color: #ff571d; font-size: 15px; font-weight: bold;">
              !
            </div>
            <span style="font-size: 13.5px; font-weight: 700; letter-spacing: 0.05em; color: #ffffff; text-transform: uppercase;">${escapeHtml(title)}</span>
          </div>
          <button id="docu-auth-modal-close" style="background: transparent; border: none; color: #8e8d8d; font-size: 18px; cursor: pointer; padding: 4px 8px; line-height: 1;">✕</button>
        </div>

        <div style="font-size: 13px; line-height: 1.5; color: #c4c2c1;">
          ${escapeHtml(message)}
        </div>

        <div style="display: flex; align-items: center; justify-content: flex-end; gap: 10px; margin-top: 8px;">
          <button id="docu-auth-modal-cancel" style="background: #2b2a2a; border: 1px solid #3d3c3c; color: #e5e2e1; padding: 8px 16px; border-radius: 6px; font-size: 12px; font-weight: 600; cursor: pointer; font-family: inherit;">
            Cancel
          </button>
          <a href="${redirectUrl}" style="background: #ff571d; border: 1px solid #ff571d; color: #191818; padding: 8px 18px; border-radius: 6px; font-size: 12px; font-weight: 700; text-decoration: none; display: inline-flex; align-items: center; gap: 6px; cursor: pointer; font-family: inherit;">
            Login / Register ›
          </a>
        </div>
      </div>
    `;

    document.body.appendChild(overlay);

    const close = () => overlay.remove();
    const closeBtn = overlay.querySelector("#docu-auth-modal-close");
    const cancelBtn = overlay.querySelector("#docu-auth-modal-cancel");
    if (closeBtn) closeBtn.onclick = close;
    if (cancelBtn) cancelBtn.onclick = close;
    overlay.onclick = (e) => { if (e.target === overlay) close(); };
  }

  async function openUpgradeModal() {
    let existing = document.getElementById("documind-upgrade-modal");
    if (existing) existing.remove();

    const overlay = document.createElement("div");
    overlay.id = "documind-upgrade-modal";
    overlay.className = "fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 overflow-y-auto";

    overlay.innerHTML = `
      <div class="bg-surface-container border border-surface-variant rounded-2xl p-6 shadow-2xl max-w-lg w-full flex flex-col gap-4 text-on-surface my-auto">
        <div class="flex items-center justify-between pb-3 border-b border-surface-variant">
          <div class="flex items-center gap-2">
            <span class="material-symbols-outlined text-primary-container">workspace_premium</span>
            <span class="font-headline-sm text-base font-semibold text-on-surface">DOCUMIND SUBSCRIPTIONS</span>
          </div>
          <button id="upgrade-modal-close" class="text-on-surface-variant hover:text-on-surface p-1 cursor-pointer">✕</button>
        </div>

        <div id="upgrade-modal-content" class="flex flex-col gap-4">
          <div class="p-4 rounded-xl bg-surface-container-low border border-surface-variant/50 text-center font-code-sm text-xs text-on-surface-variant">
            Loading current plan and entitlements…
          </div>
        </div>
      </div>
    `;

    document.body.appendChild(overlay);

    const closeBtn = overlay.querySelector("#upgrade-modal-close");
    if (closeBtn) closeBtn.onclick = () => overlay.remove();
    overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };

    try {
      const [authRes, plansRes] = await Promise.all([
        API.getAuthUser(),
        API.getBillingPlans().catch(() => ({ plans: [] })),
      ]);

      const content = overlay.querySelector("#upgrade-modal-content");
      if (!content) return;

      if (!authRes || !authRes.authenticated) {
        content.innerHTML = `
          <div class="p-4 rounded-xl bg-error/15 border border-error/30 text-error font-code-sm text-xs flex flex-col gap-2">
            <span><strong>Authentication Required:</strong> Please sign in to view and purchase DocuMind subscriptions.</span>
            <a href="/app/auth.html?redirect=${encodeURIComponent(window.location.href)}" class="mt-2 inline-block px-4 py-2 bg-primary text-on-primary font-bold rounded-lg text-center uppercase tracking-wider">
              SIGN IN / REGISTER ›
            </a>
          </div>
        `;
        return;
      }

      const quota = authRes.quota || { plan_id: "free", doc_limit: 1, consumed_docs: 0, question_limit: 5, consumed_questions: 0 };
      const sub = authRes.subscription || null;
      const plans = (plansRes && plansRes.plans) || [];
      const paidPlans = plans.filter(p => p.plan_id !== "free");

      const isSubscribed = sub && sub.status === "active" && sub.plan_id !== "free";
      const qRemaining = Math.max(0, quota.question_limit - quota.consumed_questions);
      const docsRemaining = Math.max(0, quota.doc_limit - quota.consumed_docs);

      let plansHtml = paidPlans.map(plan => {
        const isCurrentPlan = quota.plan_id === plan.plan_id;
        const priceInr = Math.round(plan.price_cents / 100);
        return `
          <div class="p-4 rounded-xl border ${isCurrentPlan ? 'border-primary bg-primary/5' : 'border-surface-variant bg-surface-container-low'} flex flex-col gap-3">
            <div class="flex items-center justify-between">
              <div>
                <h4 class="font-headline-sm text-sm font-bold text-on-surface">${escapeHtml(plan.display_name)}</h4>
                <span class="font-code-sm text-xs text-primary font-semibold">₹${priceInr.toLocaleString('en-IN')} / month</span>
              </div>
              ${isCurrentPlan ? '<span class="px-2 py-0.5 rounded-full bg-primary/20 text-primary font-code-sm text-[10px] uppercase font-bold">CURRENT PLAN</span>' : ''}
            </div>
            <ul class="font-code-sm text-[11px] text-on-surface-variant space-y-1">
              <li>✓ Up to <strong>${plan.doc_limit}</strong> indexed documents</li>
              <li>✓ <strong>${plan.question_limit}</strong> document questions per month</li>
              <li>✓ Citations, relevance checks, and evidence export</li>
            </ul>
            ${!isCurrentPlan ? `
              <button data-plan-id="${plan.plan_id}" class="btn-checkout-plan w-full py-2 bg-primary-container hover:bg-inverse-primary text-on-primary-container font-code-sm text-xs font-bold rounded-lg uppercase tracking-wider transition-colors cursor-pointer">
                UPGRADE TO ${escapeHtml(plan.display_name)}
              </button>
            ` : ''}
          </div>
        `;
      }).join("");

      content.innerHTML = `
        <!-- Current Quota Badge -->
        <div class="p-4 rounded-xl bg-surface-container-low border border-surface-variant flex flex-col gap-2">
          <div class="flex items-center justify-between">
            <span class="font-code-sm text-[10px] text-on-surface-variant uppercase tracking-wider">YOUR ACCOUNT STATUS</span>
            <span class="font-code-sm text-xs font-bold ${quota.plan_id === 'free' ? 'text-primary' : 'text-tertiary'} uppercase">${quota.plan_id === 'free' ? 'Free Tier' : quota.plan_id}</span>
          </div>
          <div class="grid grid-cols-2 gap-2 mt-1">
            <div class="p-2.5 rounded-lg bg-surface-container border border-surface-variant/40 flex flex-col">
              <span class="font-code-sm text-[10px] text-on-surface-variant">DOCUMENTS</span>
              <span class="font-metric-display text-sm font-bold text-on-surface">${quota.consumed_docs} / ${quota.doc_limit} used</span>
              <span class="font-code-sm text-[10px] text-on-surface-variant/80">${docsRemaining} remaining</span>
            </div>
            <div class="p-2.5 rounded-lg bg-surface-container border border-surface-variant/40 flex flex-col">
              <span class="font-code-sm text-[10px] text-on-surface-variant">QUESTIONS</span>
              <span class="font-metric-display text-sm font-bold text-on-surface">${quota.consumed_questions} / ${quota.question_limit} used</span>
              <span class="font-code-sm text-[10px] text-on-surface-variant/80">${qRemaining} remaining</span>
            </div>
          </div>
          ${isSubscribed ? `
            <div class="pt-2 flex items-center justify-between border-t border-surface-variant/50 font-code-sm text-[11px] text-on-surface-variant">
              <span>Subscription Provider: Razorpay (${sub.status})</span>
              <button id="btn-cancel-sub" class="text-error hover:underline cursor-pointer">Cancel Subscription</button>
            </div>
          ` : ''}
        </div>

        <!-- Available Upgrades -->
        <div class="flex flex-col gap-3">
          <span class="font-code-sm text-[10px] text-on-surface-variant uppercase tracking-wider">AVAILABLE SUBSCRIPTIONS</span>
          ${plansHtml}
        </div>
      `;

      // Bind Checkout buttons
      content.querySelectorAll(".btn-checkout-plan").forEach(btn => {
        btn.addEventListener("click", async () => {
          const planId = btn.getAttribute("data-plan-id");
          btn.disabled = true;
          btn.textContent = "INITIALIZING CHECKOUT…";
          try {
            const checkout = await API.createCheckout(planId);
            if (checkout.is_test_mode) {
              const confirmVerify = window.confirm(
                `[TEST MODE ACTIVATED]\nRazorpay Test Checkout initialized.\nOrder ID: ${checkout.order_id}\nAmount: ₹${(checkout.amount / 100).toLocaleString('en-IN')}\n\nClick OK to simulate cryptographically verified signature and activate entitlements instantly.`
              );
              if (confirmVerify) {
                btn.textContent = "VERIFYING PAYMENT…";
                await API.verifyPayment({
                  plan_id: planId,
                  order_id: checkout.order_id,
                  payment_id: "pay_test_" + Date.now(),
                  signature: checkout.test_signature,
                });
                alert(`Subscription successfully activated! Your new limits are in effect.`);
                overlay.remove();
                window.location.reload();
              } else {
                btn.disabled = false;
                btn.textContent = "UPGRADE NOW";
              }
            } else if (typeof Razorpay !== "undefined") {
              const rzp = new Razorpay({
                key: checkout.key_id,
                order_id: checkout.order_id,
                amount: checkout.amount,
                currency: checkout.currency,
                name: "DocuMind SaaS",
                description: checkout.plan_name,
                handler: async function (response) {
                  btn.textContent = "VERIFYING PAYMENT…";
                  await API.verifyPayment({
                    plan_id: planId,
                    order_id: response.razorpay_order_id,
                    payment_id: response.razorpay_payment_id,
                    signature: response.razorpay_signature,
                  });
                  alert(`Payment verified! Your ${checkout.plan_name} plan is now active.`);
                  overlay.remove();
                  window.location.reload();
                },
              });
              rzp.open();
            } else {
              alert(`Checkout created (Order: ${checkout.order_id}). Razorpay SDK script is loading.`);
            }
          } catch (cErr) {
            alert(`Checkout failed: ${cErr.message || "Server error"}`);
            btn.disabled = false;
            btn.textContent = "TRY AGAIN";
          }
        });
      });

      // Bind Cancel Subscription button
      const cancelBtn = content.querySelector("#btn-cancel-sub");
      if (cancelBtn) {
        cancelBtn.addEventListener("click", async () => {
          if (!window.confirm("Are you sure you want to cancel your subscription? Your entitlements will remain active until the end of the current period.")) return;
          cancelBtn.disabled = true;
          cancelBtn.textContent = "CANCELLING…";
          try {
            await API.cancelSubscription();
            alert("Subscription cancelled successfully.");
            overlay.remove();
            window.location.reload();
          } catch (cancelErr) {
            alert(`Failed to cancel subscription: ${cancelErr.message}`);
            cancelBtn.disabled = false;
            cancelBtn.textContent = "Cancel Subscription";
          }
        });
      }

    } catch (err) {
      console.error("Failed to load upgrade options:", err);
    }
  }

  function updateUsagePill(res) {
    if (!res || !res.authenticated || !res.quota) return;
    const quota = res.quota;
    const planName = quota.plan_id === "free" ? "Free" : (quota.plan_id.includes("team") ? "Team" : "Pro");
    const docText = `${quota.consumed_docs}/${quota.doc_limit} Docs`;
    const qRemaining = Math.max(0, quota.question_limit - quota.consumed_questions);
    const qText = `${quota.consumed_questions}/${quota.question_limit} Qs (${qRemaining} left)`;

    let pill = document.getElementById("header-usage-indicator");
    if (!pill) {
      const headerContainers = document.querySelectorAll("header .flex.items-center.gap-space-lg, header .h-14 > .flex.items-center:last-child");
      if (headerContainers.length) {
        pill = document.createElement("button");
        pill.id = "header-usage-indicator";
        pill.className = "hidden sm:inline-flex items-center gap-2 px-3 py-1 rounded-xl bg-surface-container-high border border-surface-variant hover:border-primary text-on-surface font-code-sm text-[11px] transition-colors cursor-pointer mr-1";
        headerContainers[0].insertBefore(pill, headerContainers[0].firstChild);
      }
    }
    if (pill) {
      pill.innerHTML = `
        <span class="w-1.5 h-1.5 rounded-full ${quota.plan_id === 'free' ? 'bg-primary-container' : 'bg-tertiary'}"></span>
        <span class="font-medium text-on-surface">${planName}:</span>
        <span class="text-on-surface-variant">${docText} · ${qText}</span>
        <span class="text-primary font-bold ml-1">${quota.plan_id === 'free' ? 'UPGRADE' : 'MANAGE'}</span>
      `;
      pill.onclick = (e) => {
        e.preventDefault();
        openUpgradeModal();
      };
    }
  }

  function bindAuthUI() {
    const avatarBtns = document.querySelectorAll("header .rounded-full.bg-primary, #header-user-avatar");
    if (!avatarBtns.length) return;

    let currentUser = null;

    API.getAuthUser().then((res) => {
      if (res && res.authenticated && res.user) {
        currentUser = res.user;
        updateUsagePill(res);
        avatarBtns.forEach((btn) => {
          btn.setAttribute("title", `Signed in as ${res.user.email} (${res.quota ? res.quota.plan_id : 'plan'})`);
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

  API.openUpgradeModal = openUpgradeModal;
  API.showAuthRequiredModal = showAuthRequiredModal;
  API.updateUsagePill = updateUsagePill;

  // Cross-view Navigation handler
  function bindNavigation() {
    const pathMap = {
      architecture: "../architecture/code.html",
      console: "../console/code.html",
      proof: "../proof/code.html",
      library: "../library/code.html",
      benchmarks: "../proof/code.html",
      compliance: "../proof/code.html",
    };
    document.querySelectorAll("[data-path]").forEach((el) => {
      const path = el.getAttribute("data-path");
      if (path === "chat") {
        el.addEventListener("click", async (e) => {
          e.preventDefault();
          try {
            const auth = await API.getAuthUser();
            if (!auth || !auth.authenticated) {
              showAuthRequiredModal({
                title: "Login or Register Required",
                message: "You should first login or register to access the chat assistant and upload documents.",
              });
              return;
            }
          } catch (_) {
            showAuthRequiredModal({
              title: "Login or Register Required",
              message: "You should first login or register to access the chat assistant and upload documents.",
            });
            return;
          }
          if (window.DocuMindChatDrawer && typeof window.DocuMindChatDrawer.open === "function") {
            window.DocuMindChatDrawer.open();
          } else {
            window.location.href = "../console/code.html?chat=open";
          }
        });
        return;
      }
      const target = pathMap[path];
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

