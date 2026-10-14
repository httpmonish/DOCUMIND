/**
 * DocuMind Reusable Chat Drawer Component
 * - Single source of truth for the Chat experience across all pages (Console, Library, Proof, Architecture)
 * - Opens as a sliding right-side panel without page navigation
 * - Real document chunk counts, true SSE streaming, verified citations, and honest status states
 */

(function () {
  "use strict";

  let drawerEl = null;
  let backdropEl = null;
  let messagesListEl = null;
  let composerTextarea = null;
  let btnSend = null;
  let docsTrayEl = null;
  let docsCountBadge = null;
  let evidenceDrawerEl = null;
  let evidenceSnippetEl = null;
  let evidenceSourceEl = null;
  let fileInputEl = null;
  let historyDrawerEl = null;
  let historyListEl = null;

  let currentConversationId = null;
  let isStreaming = false;
  let loadedDocs = [];
  let lastFailedQuestion = null;

  function renderCitationFormattedText(container, text, citations, onCitationClick) {
    container.textContent = "";
    if (!text) return;
    if (!citations || citations.length === 0) {
      container.textContent = text;
      return;
    }
    const markerRegex = /\[S(\d+)\]/g;
    let lastIndex = 0;
    let match;
    while ((match = markerRegex.exec(text)) !== null) {
      const matchIndex = match.index;
      if (matchIndex > lastIndex) {
        container.appendChild(document.createTextNode(text.substring(lastIndex, matchIndex)));
      }
      const markerText = match[0];
      const citNum = parseInt(match[1], 10);
      const citIndex = citNum - 1;
      const citation = citations[citIndex] || citations.find(c => c.marker === markerText);

      const pill = document.createElement("button");
      pill.className = "docu-citation-pill";
      pill.textContent = markerText;
      if (citation && onCitationClick) {
        pill.addEventListener("click", () => onCitationClick(citation));
      }
      container.appendChild(pill);
      lastIndex = markerRegex.lastIndex;
    }
    if (lastIndex < text.length) {
      container.appendChild(document.createTextNode(text.substring(lastIndex)));
    }
  }

  function renderCitationsTray(container, citations, onCitationClick) {
    container.textContent = "";
    if (!citations || citations.length === 0) {
      container.style.display = "none";
      return;
    }
    container.style.display = "flex";
    citations.forEach((c, idx) => {
      const pill = document.createElement("button");
      pill.className = "docu-citation-pill";
      const marker = c.marker || `[S${idx + 1}]`;
      pill.textContent = `${marker} ${c.source || "doc"} · c${c.chunk_index ?? 0}`;
      if (onCitationClick) {
        pill.addEventListener("click", () => onCitationClick(c));
      }
      container.appendChild(pill);
    });
  }

  function initChatDrawer() {
    if (document.getElementById("documind-chat-drawer-root")) {
      return;
    }

    // 1. Create root container
    const root = document.createElement("div");
    root.id = "documind-chat-drawer-root";
    root.innerHTML = `
      <div class="documind-chat-backdrop" id="docu-backdrop" aria-hidden="true"></div>
      <aside class="documind-chat-drawer" id="docu-drawer" role="dialog" aria-modal="true" aria-label="DocuMind Chat">
        <!-- Header -->
        <header class="docu-drawer-header">
          <div class="docu-drawer-brand">
            <div class="docu-drawer-brand-icon">
              <svg width="24" height="24" viewBox="0 0 32 32" fill="none">
                <polygon points="16,2 29,9.5 29,24.5 16,32 3,24.5 3,9.5" fill="#201f1f" stroke="#ff571d" stroke-width="2"/>
                <circle cx="16" cy="17" r="4.5" fill="#ff571d"/>
                <path d="M16 6v6.5M8.5 21.5l5.5-3M23.5 21.5l-5.5-3" stroke="#e5e2e1" stroke-width="1.5" stroke-linecap="round"/>
              </svg>
            </div>
            <div>
              <div class="docu-drawer-title">
                DocuMind Chat
                <span class="docu-drawer-status-pill" id="docu-header-status">RAG READY</span>
              </div>
            </div>
          </div>
          <div class="docu-drawer-actions">
            <button class="docu-btn-text" id="docu-btn-history" title="View conversation history">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
              <span>History</span>
            </button>
            <button class="docu-btn-text" id="docu-btn-new-chat" title="Start a fresh conversation thread">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/></svg>
              <span>New</span>
            </button>
            <button class="docu-btn-icon" id="docu-btn-close" aria-label="Close chat drawer" title="Close (Escape)">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
            </button>
          </div>
        </header>

        <!-- History Overlay Panel -->
        <div class="docu-history-drawer" id="docu-history-drawer" style="display: none;">
          <div class="docu-history-header">
            <span>SAVED CONVERSATIONS</span>
            <button class="docu-btn-icon" id="docu-btn-close-history" aria-label="Close history">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
            </button>
          </div>
          <div class="docu-history-list" id="docu-history-list">
            <span style="font-size: 11px; color: var(--docu-chat-muted);">Loading past conversations…</span>
          </div>
        </div>

        <!-- Document Tray -->
        <section class="docu-docs-tray">
          <div class="docu-docs-tray-header">
            <span>INDEXED DOCUMENTS (<span id="docu-docs-count">0</span>)</span>
            <button class="docu-btn-text" id="docu-btn-tray-upload" style="padding: 2px 7px; font-size: 11px;">
              + Upload PDF
            </button>
          </div>
          <div class="docu-docs-chips-list" id="docu-docs-chips-list">
            <span style="font-size: 11px; color: var(--docu-chat-muted);">Loading active workspace documents…</span>
          </div>
        </section>

        <!-- Messages List -->
        <main class="docu-messages-area" id="docu-messages-list">
          <div class="docu-welcome-card" id="docu-welcome-card">
            <div class="docu-welcome-icon">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
            </div>
            <div class="docu-welcome-title">Ask your documents</div>
            <div class="docu-welcome-desc">
              Questions are answered strictly from your uploaded files with verified citations. If an answer cannot be grounded, DocuMind will abstain.
            </div>
          </div>
        </main>

        <!-- Evidence Inspector Overlay Drawer -->
        <div class="docu-evidence-drawer" id="docu-evidence-drawer">
          <div class="docu-evidence-header">
            <div>
              <div style="font-size: 11px; font-family: 'JetBrains Mono', monospace; color: var(--docu-chat-muted); text-transform: uppercase;">
                Grounded Evidence
              </div>
              <div style="font-size: 13px; font-weight: 600;" id="docu-evidence-source">
                Source Document
              </div>
            </div>
            <button class="docu-btn-icon" id="docu-btn-close-evidence" aria-label="Close evidence">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
            </button>
          </div>
          <div class="docu-evidence-body">
            <div class="docu-evidence-snippet" id="docu-evidence-snippet"></div>
          </div>
        </div>

        <!-- Composer -->
        <footer class="docu-composer-tray">
          <div class="docu-composer-wrapper">
            <button class="docu-btn-icon" id="docu-btn-attach" title="Attach Document (PDF, TXT, MD)" style="align-self: flex-end; margin-bottom: 2px;">
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>
            </button>
            <input type="file" id="docu-file-input" accept=".pdf,.txt,.md" style="display: none;" />
            <textarea class="docu-composer-textarea" id="docu-composer-input" rows="1" placeholder="Ask about the indexed documents..."></textarea>
            <button class="docu-btn-send" id="docu-btn-send" title="Send message (Enter)" aria-label="Send">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
            </button>
          </div>
          <div class="docu-composer-hints">
            <span>Deterministic RAG · τ 0.35</span>
            <span>Shift+Enter for new line</span>
          </div>
        </footer>
      </aside>
    `;

    document.body.appendChild(root);

    drawerEl = document.getElementById("docu-drawer");
    backdropEl = document.getElementById("docu-backdrop");
    messagesListEl = document.getElementById("docu-messages-list");
    composerTextarea = document.getElementById("docu-composer-input");
    btnSend = document.getElementById("docu-btn-send");
    docsTrayEl = document.getElementById("docu-docs-chips-list");
    docsCountBadge = document.getElementById("docu-docs-count");
    evidenceDrawerEl = document.getElementById("docu-evidence-drawer");
    evidenceSnippetEl = document.getElementById("docu-evidence-snippet");
    evidenceSourceEl = document.getElementById("docu-evidence-source");
    fileInputEl = document.getElementById("docu-file-input");
    historyDrawerEl = document.getElementById("docu-history-drawer");
    historyListEl = document.getElementById("docu-history-list");

    // Event listeners
    backdropEl.addEventListener("click", closeDrawer);
    document.getElementById("docu-btn-close").addEventListener("click", closeDrawer);
    document.getElementById("docu-btn-close-evidence").addEventListener("click", closeEvidence);

    document.getElementById("docu-btn-new-chat").addEventListener("click", resetConversation);
    const btnHistory = document.getElementById("docu-btn-history");
    if (btnHistory) btnHistory.addEventListener("click", toggleHistory);
    const btnCloseHist = document.getElementById("docu-btn-close-history");
    if (btnCloseHist) btnCloseHist.addEventListener("click", closeHistory);

    // Attach actions
    const btnAttach = document.getElementById("docu-btn-attach");
    const btnTrayUpload = document.getElementById("docu-btn-tray-upload");
    btnAttach.addEventListener("click", () => fileInputEl.click());
    btnTrayUpload.addEventListener("click", () => fileInputEl.click());

    fileInputEl.addEventListener("change", handleFileUpload);

    // Composer auto-resize & key bindings
    composerTextarea.addEventListener("input", () => {
      composerTextarea.style.height = "auto";
      composerTextarea.style.height = Math.min(composerTextarea.scrollHeight, 120) + "px";
    });

    composerTextarea.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendCurrentQuestion();
      }
    });

    btnSend.addEventListener("click", sendCurrentQuestion);

    // Escape listener
    window.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        if (evidenceDrawerEl && evidenceDrawerEl.classList.contains("active")) {
          closeEvidence();
          return;
        }
        if (isOpen()) {
          closeDrawer();
        }
      }
    });

    // Wire all page buttons that trigger chat
    wireChatTriggers();

    // Auto-restore active conversation if present in session storage
    try {
      const savedConvId = sessionStorage.getItem("documind_active_conv_id");
      if (savedConvId) {
        loadConversation(savedConvId);
      }
    } catch (_) {}
  }

  function wireChatTriggers() {
    // Intercept clicks on links or buttons with data-path="chat" or pointing to chat.html
    document.addEventListener("click", (e) => {
      const target = e.target.closest("a, button");
      if (!target) return;

      const path = target.getAttribute("data-path");
      const href = target.getAttribute("href") || "";
      const text = (target.textContent || "").trim();

      const isChatTrigger =
        path === "chat" ||
        href.includes("chat.html") ||
        text === "Chat UI" ||
        text === "LAUNCH CHAT ↗" ||
        text.includes("OPEN CHAT");

      if (isChatTrigger) {
        e.preventDefault();
        e.stopPropagation();
        openDrawer();
      }
    });
  }

  function isOpen() {
    return drawerEl && drawerEl.classList.contains("open");
  }

  async function openDrawer() {
    // Check authentication prior to granting chat access
    try {
      const auth = typeof DocuMindAPI !== "undefined" && DocuMindAPI.getAuthUser ? await DocuMindAPI.getAuthUser() : null;
      if (!auth || !auth.authenticated) {
        if (typeof DocuMindAPI !== "undefined" && typeof DocuMindAPI.showAuthRequiredModal === "function") {
          DocuMindAPI.showAuthRequiredModal({
            title: "Login or Register Required",
            message: "You should first login or register to access the chat assistant and upload documents.",
          });
        } else {
          window.location.href = `/app/auth.html?reason=auth_required&redirect=${encodeURIComponent(window.location.href)}`;
        }
        return;
      }
    } catch (e) {
      if (typeof DocuMindAPI !== "undefined" && typeof DocuMindAPI.showAuthRequiredModal === "function") {
        DocuMindAPI.showAuthRequiredModal({
          title: "Login or Register Required",
          message: "You should first login or register to access the chat assistant and upload documents.",
        });
      } else {
        window.location.href = `/app/auth.html?reason=auth_required&redirect=${encodeURIComponent(window.location.href)}`;
      }
      return;
    }

    if (!drawerEl) initChatDrawer();
    backdropEl.classList.add("active");
    drawerEl.classList.add("open");
    document.body.style.overflow = "hidden";
    if (composerTextarea) {
      setTimeout(() => composerTextarea.focus(), 150);
    }
    refreshDocuments();
  }

  function closeDrawer() {
    if (!drawerEl) return;
    drawerEl.classList.remove("open");
    backdropEl.classList.remove("active");
    closeEvidence();
    document.body.style.overflow = "";
  }

  function openEvidence(citation) {
    if (!evidenceDrawerEl) return;
    evidenceSourceEl.textContent = `${citation.source} (chunk ${citation.chunk_index}) · score ${citation.score}`;
    evidenceSnippetEl.textContent = citation.snippet || "No snippet available.";
    evidenceDrawerEl.classList.add("active");
  }

  function closeEvidence() {
    if (evidenceDrawerEl) {
      evidenceDrawerEl.classList.remove("active");
    }
  }

  function closeHistory() {
    if (historyDrawerEl) {
      historyDrawerEl.style.display = "none";
    }
  }

  async function toggleHistory() {
    if (!historyDrawerEl) return;
    if (historyDrawerEl.style.display === "flex") {
      closeHistory();
      return;
    }
    closeEvidence();
    historyDrawerEl.style.display = "flex";
    historyListEl.innerHTML = `
      <span style="font-size: 11px; color: var(--docu-chat-muted); padding: 8px;">Loading saved conversations…</span>
    `;
    try {
      const convs = await DocuMindAPI.listConversations();
      const list = Array.isArray(convs) ? convs : [];
      if (list.length === 0) {
        historyListEl.innerHTML = `
          <div style="text-align: center; padding: 24px 12px; color: var(--docu-chat-muted); font-size: 12px;">
            No saved conversations found. Ask a question to start one!
          </div>
        `;
        return;
      }
      historyListEl.innerHTML = list.map(c => {
        const title = c.title || "Untitled Conversation";
        const dateStr = c.last_message_at ? new Date(c.last_message_at * 1000).toLocaleDateString(undefined, {
          month: "short", day: "numeric", hour: "2-digit", minute: "2-digit"
        }) : (c.created_at ? new Date(c.created_at * 1000).toLocaleDateString() : "");
        const isActive = c.id === currentConversationId ? " active" : "";
        return `
          <div class="docu-history-item${isActive}" data-conv-id="${escapeHtml(c.id)}">
            <div class="docu-history-item-info">
              <span class="docu-history-item-title">${escapeHtml(title)}</span>
              <span class="docu-history-item-date">${escapeHtml(dateStr)}</span>
            </div>
            <button class="docu-history-delete-btn" data-delete-id="${escapeHtml(c.id)}" title="Delete conversation">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
            </button>
          </div>
        `;
      }).join("");

      historyListEl.querySelectorAll(".docu-history-item").forEach(item => {
        item.addEventListener("click", (e) => {
          if (e.target.closest(".docu-history-delete-btn")) return;
          const cid = item.getAttribute("data-conv-id");
          if (cid) loadConversation(cid);
        });
      });

      historyListEl.querySelectorAll(".docu-history-delete-btn").forEach(btn => {
        btn.addEventListener("click", async (e) => {
          e.stopPropagation();
          const cid = btn.getAttribute("data-delete-id");
          if (!cid) return;
          try {
            await DocuMindAPI.deleteConversation(cid);
            if (currentConversationId === cid) {
              resetConversation();
            }
            toggleHistory();
          } catch (delErr) {
            console.error("Failed to delete conversation:", delErr);
          }
        });
      });
    } catch (err) {
      console.error("Failed to load conversations:", err);
      historyListEl.innerHTML = `
        <div style="color: var(--docu-chat-red); font-size: 12px; padding: 12px;">
          Failed to load history: ${escapeHtml(err.message)}
        </div>
      `;
    }
  }

  async function loadConversation(convId) {
    closeHistory();
    closeEvidence();
    currentConversationId = convId;
    try {
      sessionStorage.setItem("documind_active_conv_id", convId);
    } catch (_) {}
    if (messagesListEl) {
      messagesListEl.innerHTML = `
        <div style="padding: 24px; text-align: center; color: var(--docu-chat-muted); font-size: 12.5px;">
          Restoring conversation messages…
        </div>
      `;
    }
    try {
      const msgs = await DocuMindAPI.getConversationMessages(convId);
      const list = Array.isArray(msgs) ? msgs : [];
      if (messagesListEl) {
        messagesListEl.innerHTML = "";
      }
      if (list.length === 0) {
        resetConversation();
        return;
      }
      for (const m of list) {
        if (m.role === "user") {
          const userRow = document.createElement("div");
          userRow.className = "docu-msg-row user";
          userRow.innerHTML = `
            <span class="docu-msg-role">YOU</span>
            <div class="docu-user-bubble">${escapeHtml(m.content)}</div>
          `;
          messagesListEl.appendChild(userRow);
        } else {
          const assistantRow = document.createElement("div");
          assistantRow.className = "docu-msg-row assistant";
          const roleSpan = document.createElement("span");
          roleSpan.className = "docu-msg-role";
          roleSpan.innerHTML = `<svg width="12" height="12" viewBox="0 0 32 32" fill="none" style="display:inline-block; vertical-align:-1px; margin-right:5px;"><polygon points="16,2 29,9.5 29,24.5 16,32 3,24.5 3,9.5" fill="#201f1f" stroke="#ff571d" stroke-width="2.5"/><circle cx="16" cy="17" r="4.5" fill="#ff571d"/><path d="M16 6v6.5M8.5 21.5l5.5-3M23.5 21.5l-5.5-3" stroke="#e5e2e1" stroke-width="1.8" stroke-linecap="round"/></svg>DOCUMIND`;

          const card = document.createElement("div");
          card.className = "docu-assistant-card";

          const contentDiv = document.createElement("div");
          contentDiv.className = "docu-assistant-content";
          const tokenSpan = document.createElement("span");
          tokenSpan.className = "token-stream";
          const citations = Array.isArray(m.citations) ? m.citations : [];
          renderCitationFormattedText(tokenSpan, m.content || "", citations, openEvidence);
          contentDiv.appendChild(tokenSpan);
          card.appendChild(contentDiv);

          const tray = document.createElement("div");
          tray.className = "docu-citations-tray";
          renderCitationsTray(tray, citations, openEvidence);
          card.appendChild(tray);

          const metaDiv = document.createElement("div");
          metaDiv.className = "docu-assistant-meta";
          const statusSpan = document.createElement("span");
          statusSpan.className = "status-label";
          statusSpan.style.color = "var(--docu-chat-green)";
          statusSpan.textContent = `${citations.length} Verified Citations`;
          metaDiv.appendChild(statusSpan);
          card.appendChild(metaDiv);

          assistantRow.appendChild(roleSpan);
          assistantRow.appendChild(card);
          messagesListEl.appendChild(assistantRow);
        }
      }
      messagesListEl.scrollTop = messagesListEl.scrollHeight;
      if (composerTextarea) {
        composerTextarea.focus();
      }
    } catch (err) {
      console.error("Failed to restore conversation messages:", err);
      if (messagesListEl) {
        messagesListEl.innerHTML = `
          <div class="docu-banner-error">
            <span>Failed to restore messages: ${escapeHtml(err.message)}</span>
          </div>
        `;
      }
    }
  }

  function resetConversation() {
    currentConversationId = null;
    lastFailedQuestion = null;
    try {
      sessionStorage.removeItem("documind_active_conv_id");
    } catch (_) {}
    if (messagesListEl) {
      messagesListEl.innerHTML = `
        <div class="docu-welcome-card" id="docu-welcome-card">
          <div class="docu-welcome-icon">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
          </div>
          <div class="docu-welcome-title">Fresh conversation started</div>
          <div class="docu-welcome-desc">
            Enter a question below to analyze your documents.
          </div>
        </div>
      `;
    }
    if (composerTextarea) {
      composerTextarea.value = "";
      composerTextarea.focus();
    }
  }

  async function refreshDocuments() {
    if (!docsTrayEl || typeof DocuMindAPI === "undefined") return;
    try {
      const docs = await DocuMindAPI.getDocuments();
      loadedDocs = Array.isArray(docs) ? docs : (docs && docs.documents ? docs.documents : []);

      if (docsCountBadge) {
        docsCountBadge.textContent = String(loadedDocs.length);
      }

      if (loadedDocs.length === 0) {
        docsTrayEl.innerHTML = `
          <span style="font-size: 11px; color: var(--docu-chat-muted);">No documents indexed yet. Click "+ Upload PDF" to get started.</span>
        `;
        return;
      }

      docsTrayEl.innerHTML = loadedDocs.map(d => {
        const chunkCount = d.chunks ?? d.chunk_count ?? 0;
        const ext = d.source.split(".").pop().toUpperCase();
        return `
          <div class="docu-doc-chip" title="${escapeHtml(d.source)}">
            <span class="docu-doc-chip-badge">${escapeHtml(ext)}</span>
            <span style="max-width: 130px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${escapeHtml(d.source)}</span>
            <span class="docu-doc-chip-chunks">${chunkCount} chk</span>
          </div>
        `;
      }).join("");
    } catch (err) {
      console.warn("Failed to refresh documents in chat drawer:", err);
      docsTrayEl.innerHTML = `
        <span style="font-size: 11px; color: var(--docu-chat-amber);">Ready for local session documents.</span>
      `;
    }
  }

  async function handleFileUpload(e) {
    const file = e.target.files && e.target.files[0];
    if (!file) return;

    // Check authentication - require login or register before uploading
    try {
      const authState = await DocuMindAPI.getAuthUser();
      if (!authState || !authState.authenticated) {
        if (typeof DocuMindAPI !== "undefined" && typeof DocuMindAPI.showAuthRequiredModal === "function") {
          DocuMindAPI.showAuthRequiredModal({
            title: "Login or Register Required",
            message: "You should first login or register before uploading documents.",
          });
        }
        const authCard = document.createElement("div");
        authCard.className = "docu-msg-row assistant";
        authCard.innerHTML = `
          <div class="docu-banner-error" style="display: flex; flex-direction: column; gap: 8px;">
            <span><strong>Authentication Required:</strong> Anonymous users cannot upload or index documents. Please sign in or register to access your secure vault.</span>
            <a href="/app/auth.html?reason=auth_required&redirect=${encodeURIComponent(window.location.href)}" class="docu-btn-primary" style="align-self: flex-start; text-decoration: none; padding: 4px 12px; font-size: 11px;">Sign in / Register ›</a>
          </div>
        `;
        messagesListEl.appendChild(authCard);
        messagesListEl.scrollTop = messagesListEl.scrollHeight;
        fileInputEl.value = "";
        return;
      }
    } catch (authErr) {
      if (typeof DocuMindAPI !== "undefined" && typeof DocuMindAPI.showAuthRequiredModal === "function") {
        DocuMindAPI.showAuthRequiredModal({
          title: "Login or Register Required",
          message: "You should first login or register before uploading documents.",
        });
      }
      const authCard = document.createElement("div");
      authCard.className = "docu-msg-row assistant";
      authCard.innerHTML = `
        <div class="docu-banner-error" style="display: flex; flex-direction: column; gap: 8px;">
          <span><strong>Authentication Required:</strong> Anonymous users cannot upload or index documents. Please sign in or register to access your secure vault.</span>
          <a href="/app/auth.html?reason=auth_required&redirect=${encodeURIComponent(window.location.href)}" class="docu-btn-primary" style="align-self: flex-start; text-decoration: none; padding: 4px 12px; font-size: 11px;">Sign in / Register ›</a>
        </div>
      `;
      messagesListEl.appendChild(authCard);
      messagesListEl.scrollTop = messagesListEl.scrollHeight;
      fileInputEl.value = "";
      return;
    }

    // Show temporary banner in message area
    const uploadingCard = document.createElement("div");
    uploadingCard.className = "docu-msg-row assistant";
    uploadingCard.innerHTML = `
      <div class="docu-assistant-card" style="border-left: 3px solid var(--docu-chat-blue);">
        <div style="font-size: 12.5px; display: flex; items-center; gap: 8px;">
          <span class="docu-streaming-cursor"></span>
          <span>Uploading and indexing <strong>${escapeHtml(file.name)}</strong>...</span>
        </div>
      </div>
    `;
    messagesListEl.appendChild(uploadingCard);
    messagesListEl.scrollTop = messagesListEl.scrollHeight;

    try {
      const res = await DocuMindAPI.uploadDocument(file);
      const chunkCount = res.chunks ?? res.chunk_count ?? 0;
      uploadingCard.innerHTML = `
        <div class="docu-assistant-card" style="border-left: 3px solid var(--docu-chat-green);">
          <div style="font-size: 13px;">
            ✓ Successfully indexed <strong>${escapeHtml(res.source || file.name)}</strong> (${chunkCount} chunks created). You can now ask questions about it!
          </div>
        </div>
      `;
      refreshDocuments();
    } catch (err) {
      if (err.code === "FREE_DOCUMENT_LIMIT_REACHED" || (err.message && err.message.includes("FREE_DOCUMENT_LIMIT_REACHED"))) {
        uploadingCard.innerHTML = `
          <div class="docu-banner-upgrade" style="background: rgba(255,87,29,0.12); border: 1px solid rgba(255,87,29,0.35); border-radius: 8px; padding: 12px; color: #ffb59f; font-family: 'JetBrains Mono', monospace; display: flex; flex-direction: column; gap: 8px;">
            <div style="font-weight: 700; font-size: 13px;">📄 Lifetime Document Limit Reached</div>
            <div style="font-size: 12px; color: #e5e2e1;">The initial free plan includes 1 indexed document over your account's lifetime. Upgrade your plan to index additional documents.</div>
            <button id="docu-upload-upgrade-btn" class="docu-btn-primary" style="align-self: flex-start; padding: 5px 14px; font-size: 11px; font-weight: 700; cursor: pointer;">VIEW PLANS & UPGRADE ›</button>
          </div>
        `;
        const upBtn = uploadingCard.querySelector("#docu-upload-upgrade-btn");
        if (upBtn) {
          upBtn.onclick = () => {
            if (typeof DocuMindAPI !== "undefined" && DocuMindAPI.openUpgradeModal) {
              DocuMindAPI.openUpgradeModal();
            }
          };
        }
      } else if (err.status === 401 || err.code === "UNAUTHORIZED" || (err.message && err.message.includes("Authentication required"))) {
        uploadingCard.innerHTML = `
          <div class="docu-banner-error" style="display: flex; flex-direction: column; gap: 6px;">
            <span><strong>Authentication Required:</strong> Please sign in to index and query documents.</span>
            <a href="/app/auth.html?reason=auth_required&redirect=${encodeURIComponent(window.location.href)}" class="docu-btn-primary" style="align-self: flex-start; text-decoration: none; padding: 4px 10px; font-size: 11px;">Sign in to Continue ›</a>
          </div>
        `;
      } else {
        uploadingCard.innerHTML = `
          <div class="docu-banner-error">
            <span>Failed to index ${escapeHtml(file.name)}: ${escapeHtml(err.message)}</span>
          </div>
        `;
      }
    } finally {
      fileInputEl.value = "";
    }
  }

  async function sendCurrentQuestion() {
    if (isStreaming) return;
    const q = composerTextarea.value.trim();
    if (!q) return;

    // Check authentication prior to sending questions
    try {
      const auth = typeof DocuMindAPI !== "undefined" && DocuMindAPI.getAuthUser ? await DocuMindAPI.getAuthUser() : null;
      if (!auth || !auth.authenticated) {
        if (typeof DocuMindAPI !== "undefined" && typeof DocuMindAPI.showAuthRequiredModal === "function") {
          DocuMindAPI.showAuthRequiredModal({
            title: "Login or Register Required",
            message: "You should first login or register to access the chat assistant.",
          });
        }
        return;
      }
    } catch (e) {
      if (typeof DocuMindAPI !== "undefined" && typeof DocuMindAPI.showAuthRequiredModal === "function") {
        DocuMindAPI.showAuthRequiredModal({
          title: "Login or Register Required",
          message: "You should first login or register to access the chat assistant.",
        });
      }
      return;
    }

    composerTextarea.value = "";
    composerTextarea.style.height = "auto";

    // Hide welcome card
    const welcomeCard = document.getElementById("docu-welcome-card");
    if (welcomeCard) welcomeCard.remove();

    // 1. Render User Message
    const userRow = document.createElement("div");
    userRow.className = "docu-msg-row user";
    userRow.innerHTML = `
      <span class="docu-msg-role">YOU</span>
      <div class="docu-user-bubble">${escapeHtml(q)}</div>
    `;
    messagesListEl.appendChild(userRow);

    // 2. Render Assistant Streaming Container
    const assistantRow = document.createElement("div");
    assistantRow.className = "docu-msg-row assistant";
    assistantRow.innerHTML = `
      <span class="docu-msg-role"><svg width="12" height="12" viewBox="0 0 32 32" fill="none" style="display:inline-block; vertical-align:-1px; margin-right:5px;"><polygon points="16,2 29,9.5 29,24.5 16,32 3,24.5 3,9.5" fill="#201f1f" stroke="#ff571d" stroke-width="2.5"/><circle cx="16" cy="17" r="4.5" fill="#ff571d"/><path d="M16 6v6.5M8.5 21.5l5.5-3M23.5 21.5l-5.5-3" stroke="#e5e2e1" stroke-width="1.8" stroke-linecap="round"/></svg>DOCUMIND</span>
      <div class="docu-assistant-card">
        <div class="docu-assistant-content"><span class="token-stream"></span><span class="docu-streaming-cursor"></span></div>
        <div class="docu-citations-tray" style="display: none;"></div>
        <div class="docu-assistant-meta">
          <span class="status-label">Retrieving evidence…</span>
          <span class="worked-label docu-worked-badge" style="display: none;"></span>
        </div>
      </div>
    `;
    messagesListEl.appendChild(assistantRow);
    messagesListEl.scrollTop = messagesListEl.scrollHeight;

    const tokenSpan = assistantRow.querySelector(".token-stream");
    const cursorEl = assistantRow.querySelector(".docu-streaming-cursor");
    const citationsTray = assistantRow.querySelector(".docu-citations-tray");
    const statusLabel = assistantRow.querySelector(".status-label");
    const workedLabel = assistantRow.querySelector(".worked-label");

    isStreaming = true;
    btnSend.disabled = true;
    const startTime = performance.now();

    let accumulatedText = "";
    let citations = [];
    let outcome = "answered";
    let reportedLatency = null;
    let streamDone = null;
    let streamError = null;

    try {
      await DocuMindAPI.chatStream(
        q,
        currentConversationId,
        (ev, data) => {
          if (ev === "meta") {
            if (data && data.conversation_id) {
              currentConversationId = data.conversation_id;
              try {
                sessionStorage.setItem("documind_active_conv_id", currentConversationId);
              } catch (_) {}
            }
            statusLabel.textContent = "Searching vector space…";
          } else if (ev === "retrieval") {
            statusLabel.textContent = `Found ${(data.retrieved || []).length} passages…`;
          } else if (ev === "token") {
            if (statusLabel) statusLabel.textContent = "Synthesizing answer…";
            if (data && data.delta) {
              accumulatedText += data.delta;
              tokenSpan.textContent = accumulatedText;
              messagesListEl.scrollTop = messagesListEl.scrollHeight;
            }
          } else if (ev === "citations") {
            citations = (data && data.citations) || [];
          } else if (ev === "done") {
            streamDone = data;
            outcome = (data && data.outcome) || "answered";
            if (data && data.latency_ms) {
              reportedLatency = data.latency_ms;
            }
          } else if (ev === "error") {
            streamError = typeof data === "object" && data !== null ? data : { message: String(data) };
          }
        }
      );

      const elapsed = reportedLatency || Math.round(performance.now() - startTime);

      // Remove cursor
      if (cursorEl) cursorEl.remove();

      // Show Worked for Xs
      if (workedLabel) {
        workedLabel.textContent = `Worked for ${(elapsed / 1000).toFixed(1)}s`;
        workedLabel.style.display = "inline-flex";
      }

      // Handle backend error
      if (streamError) {
        const errCode = streamError.code || "error";
        const errMsg = streamError.message || "An error occurred during response generation.";
        statusLabel.textContent = errCode === "index_empty" ? "Workspace Index Empty" : "Request Failed";
        statusLabel.style.color = "var(--docu-chat-red)";
        if (errCode === "index_empty") {
          tokenSpan.textContent = "No documents are currently indexed in this workspace.";
          assistantRow.querySelector(".docu-assistant-card").insertAdjacentHTML("afterbegin", `
            <div class="docu-banner-abstain" style="background:#fee2e2; border-color:#fca5a5; color:#991b1b; padding:8px 12px; margin-bottom:8px; border-radius:6px; font-size:12px;">
              <div><strong>Workspace index is empty.</strong> Please upload a document in the Library before asking questions.</div>
            </div>
          `);
        } else {
          tokenSpan.textContent = `⚠️ ${errMsg}`;
        }
        return;
      }

      // Handle interrupted stream without completion event
      if (!streamDone) {
        statusLabel.textContent = "Stream Interrupted";
        statusLabel.style.color = "var(--docu-chat-red)";
        if (!accumulatedText) {
          tokenSpan.textContent = "⚠️ Response stream was interrupted before completion.";
        }
        return;
      }

      // Handle outcomes
      if (outcome && outcome.startsWith("abstain")) {
        statusLabel.textContent = "Grounded Abstention (τ < 0.35)";
        statusLabel.style.color = "var(--docu-chat-amber)";
        assistantRow.querySelector(".docu-assistant-card").insertAdjacentHTML("afterbegin", `
          <div class="docu-banner-abstain">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="shrink: 0; margin-top: 1px;"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
            <div><strong>Insufficient document evidence.</strong> DocuMind refuses to hallucinate facts not present in your files.</div>
          </div>
        `);
      } else if (outcome === "unconfigured_model") {
        statusLabel.textContent = "Semantic Retrieval Only";
        statusLabel.style.color = "var(--docu-chat-amber)";
        assistantRow.querySelector(".docu-assistant-card").insertAdjacentHTML("afterbegin", `
          <div class="docu-banner-unconfigured">
            <div style="font-weight: 600;">⚠️ Language Model Unconfigured</div>
            <div style="font-size: 12px; color: #713f12;">
              The retrieved evidence below was verified with cosine confidence, but no LLM key is configured in <code>.env</code> to generate an answer.
            </div>
          </div>
        `);
      } else {
        if (!accumulatedText.trim()) {
          accumulatedText = "I couldn't find sufficient context in your documents to answer this question.";
        }
        statusLabel.textContent = `${citations.length} Verified Citations`;
        statusLabel.style.color = "var(--docu-chat-green)";

        // Format text with interactive citation pills safely
        renderCitationFormattedText(tokenSpan, accumulatedText, citations, openEvidence);
      }

      // Populate citations footer tray safely
      if (citations.length > 0) {
        renderCitationsTray(citationsTray, citations, openEvidence);
      }

    } catch (err) {
      console.error("Chat error:", err);
      lastFailedQuestion = q;
      if (cursorEl) cursorEl.remove();

      if (err.code === "FREE_QUESTION_LIMIT_REACHED" || (err.message && err.message.includes("FREE_QUESTION_LIMIT_REACHED"))) {
        statusLabel.textContent = "Free Question Quota Reached";
        statusLabel.style.color = "var(--docu-chat-amber)";
        assistantRow.querySelector(".docu-assistant-card").innerHTML = `
          <div class="docu-banner-upgrade" style="background: rgba(255,87,29,0.12); border: 1px solid rgba(255,87,29,0.35); border-radius: 8px; padding: 12px; color: #ffb59f; font-family: 'JetBrains Mono', monospace; display: flex; flex-direction: column; gap: 8px;">
            <div style="font-weight: 700; font-size: 13px;">🚀 Free Question Limit Reached</div>
            <div style="font-size: 12px; color: #e5e2e1;">Your five free DocuMind questions have been used. Upgrade your plan to continue asking questions about your documents.</div>
            <button id="docu-chat-upgrade-btn" class="docu-btn-primary" style="align-self: flex-start; padding: 5px 14px; font-size: 11px; font-weight: 700; cursor: pointer;">VIEW PLANS & UPGRADE ›</button>
          </div>
        `;
        const upBtn = assistantRow.querySelector("#docu-chat-upgrade-btn");
        if (upBtn) {
          upBtn.onclick = () => {
            if (typeof DocuMindAPI !== "undefined" && DocuMindAPI.openUpgradeModal) {
              DocuMindAPI.openUpgradeModal();
            }
          };
        }
      } else {
        statusLabel.textContent = "Request failed";
        statusLabel.style.color = "var(--docu-chat-red)";

        assistantRow.querySelector(".docu-assistant-card").innerHTML = `
          <div class="docu-banner-error">
            <span>${escapeHtml(err.message || "Failed to stream response.")}</span>
            <button class="docu-btn-text" id="docu-btn-retry" style="padding: 2px 8px; font-size: 11px;">
              Retry
            </button>
          </div>
        `;

        const btnRetry = assistantRow.querySelector("#docu-btn-retry");
        if (btnRetry) {
          btnRetry.addEventListener("click", () => {
            assistantRow.remove();
            composerTextarea.value = lastFailedQuestion;
            sendCurrentQuestion();
          });
        }
      }
    } finally {
      isStreaming = false;
      btnSend.disabled = false;
      messagesListEl.scrollTop = messagesListEl.scrollHeight;
    }
  }

  function escapeHtml(str) {
    if (!str) return "";
    return String(str).replace(/[&<>"']/g, function (m) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[m];
    });
  }

  // Auto-initialize when DOM is ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      initChatDrawer();
      checkAutoOpen();
    });
  } else {
    initChatDrawer();
    checkAutoOpen();
  }

  function checkAutoOpen() {
    const params = new URLSearchParams(window.location.search);
    if (params.get("chat") === "open") {
      openDrawer();
    }
  }

  // Public API
  window.DocuMindChatDrawer = {
    open: openDrawer,
    close: closeDrawer,
    toggle: () => (isOpen() ? closeDrawer() : openDrawer()),
    isOpen,
    refreshDocuments,
    resetConversation,
  };
})();
