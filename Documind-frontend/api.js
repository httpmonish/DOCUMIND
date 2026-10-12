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

  function generateSessionToken() {
    if (typeof crypto !== "undefined" && crypto.randomUUID) {
      return crypto.randomUUID().replace(/-/g, "");
    }
    return "sess_" + Math.random().toString(36).substring(2, 15) + Math.random().toString(36).substring(2, 15);
  }

  function getSessionId() {
    if (typeof window === "undefined" || !window.sessionStorage) {
      return "anon_session_default_1234567890";
    }
    let sid = window.sessionStorage.getItem("documind_session_id");
    if (!sid || sid.length < 16) {
      sid = generateSessionToken();
      window.sessionStorage.setItem("documind_session_id", sid);
    }
    return sid;
  }

  async function initSession(forceNew = false) {
    if (!forceNew && typeof window !== "undefined" && window.sessionStorage) {
      const existing = window.sessionStorage.getItem("documind_session_id");
      if (existing && existing.length >= 16) {
        return existing;
      }
    }
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
    } catch (e) {
      console.warn("Could not negotiate server session token, using fallback:", e);
    }
    const sid = generateSessionToken();
    if (typeof window !== "undefined" && window.sessionStorage) {
      window.sessionStorage.setItem("documind_session_id", sid);
    }
    return sid;
  }

  async function request(endpoint, options = {}) {
    const baseUrl = getBaseUrl();
    const url = `${baseUrl}${endpoint}`;
    const timeoutMs = options.timeoutMs || DEFAULT_TIMEOUT_MS;

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

    const headers = new Headers(options.headers || {});
    if (!headers.has("X-Session-ID")) {
      headers.set("X-Session-ID", getSessionId());
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
        const newSid = await initSession(true);
        const retryHeaders = new Headers(options.headers || {});
        retryHeaders.set("X-Session-ID", newSid);
        return request(endpoint, { ...options, headers: retryHeaders, _retried: true });
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

    async initSession(forceNew = false) {
      return initSession(forceNew);
    },

    async newSession() {
      if (typeof window !== "undefined" && window.sessionStorage) {
        window.sessionStorage.removeItem("documind_session_id");
      }
      return initSession(true);
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

  // Cross-view Navigation handler
  if (typeof document !== "undefined") {
    document.addEventListener("DOMContentLoaded", () => {
      const pathMap = {
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
    });
  }

  return API;
});
