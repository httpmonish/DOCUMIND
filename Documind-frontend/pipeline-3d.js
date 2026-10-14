/**
 * DocuMind Interactive 3D Pipeline & Architecture Controller
 * Implements:
 * 1. Bidirectional 3D pipeline stage hover, click, focus, and touch synchronization
 *    between the left navigation controller rows and the right visual cards.
 * 2. Dynamic stage telemetry, invariants, and architecture inspector.
 * 3. Guided pipeline walkthrough tour with play/pause and reset controls.
 * 4. RAG Question Journey scenario switcher (Sufficient Evidence vs Hard Abstention).
 * 5. Interactive citation evidence explorer with verified source passage previews.
 * 6. Responsive 3D tilt physics with prefers-reduced-motion accessibility.
 */

(function () {
  "use strict";

  const stage = document.getElementById("pipeline-3d-stage");
  const container = document.getElementById("pipeline-3d-container");
  if (!stage || !container) return;

  const cards = Array.from(stage.querySelectorAll(".pipeline-card"));
  const conduits = Array.from(stage.querySelectorAll(".pipeline-connector-track"));
  const stageRows = Array.from(document.querySelectorAll(".pipeline-stage-row"));
  const activeBadge = document.getElementById("pipeline-active-badge");

  // Inspector elements
  const inspectorLabel = document.getElementById("inspector-stage-label");
  const inspectorLatency = document.getElementById("inspector-stage-latency");
  const inspectorDesc = document.getElementById("inspector-stage-desc");
  const inspectorInvariant = document.getElementById("inspector-stage-invariant");
  const inspectorSpec = document.getElementById("inspector-stage-spec");

  // Simulation Viewport & Interactive Canvas Elements
  const simViewport = document.getElementById("doc-simulation-viewport");
  const canvasWrap = document.getElementById("doc-3d-canvas-wrap");
  const docScene = document.getElementById("doc-3d-scene");
  const canvasPips = Array.from(document.querySelectorAll(".sim-canvas-pip"));
  const btnCanvasPrev = document.getElementById("sim-canvas-prev");
  const btnCanvasNext = document.getElementById("sim-canvas-next");
  const simChunksOverlay = document.getElementById("sim-chunks-overlay");

  // Walkthrough buttons
  const btnWalkthrough = document.getElementById("btn-pipeline-walkthrough");
  const btnReset = document.getElementById("btn-pipeline-reset");

  const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* =========================================================================
     STAGE DATA MODEL (ARCHITECTURAL INVARIANTS & TELEMETRY)
     ========================================================================= */

  const STAGE_DATA = {
    1: {
      label: "STAGE 01 · UPLOAD DISPATCH",
      title: "Upload & Ingest",
      latency: "14 ms",
      desc: "Direct multipart upload buffer stream into memory sandbox. Calculates SHA-256 fingerprint upfront for cryptographic deduplication and pipeline idempotency.",
      invariant: "INVARIANT: SHA-256 Idempotency",
      spec: "BUFFER: 50 MB MAX"
    },
    2: {
      label: "STAGE 02 · MAGIC BYTES VALIDATION",
      title: "Magic-Byte Validation",
      latency: "0.8 ms",
      desc: "Low-level magic byte validator checks leading binary signature (%PDF-1.7) and enforces strict MIME type sanity. Malformed or poisoned files are quarantined before parsing.",
      invariant: "INVARIANT: Binary Header Match",
      spec: "SANITY: %PDF-1.7 SIGNATURE"
    },
    3: {
      label: "STAGE 03 · LAYER SEPARATION",
      title: "Layer Separation",
      latency: "14 ms",
      desc: "pypdf sandboxed text extraction separates pure textual content streams while discarding non-text raster glyphs and unsafe embedded JavaScript.",
      invariant: "INVARIANT: UTF-8 Normalization",
      spec: "STREAM: PURE TEXT LAYER"
    },
    4: {
      label: "STAGE 04 · SLIDING CHUNK WINDOW",
      title: "Sliding Chunk Window",
      latency: "2 ms",
      desc: "Recursive token chunker slices text into 200-word tiles with a calibrated 30-word overlap zone. Sentence boundary preservation prevents mid-concept fragmentation.",
      invariant: "INVARIANT: Boundary Preserved",
      spec: "TILES: 200 WORDS / 30w OVERLAP"
    },
    5: {
      label: "STAGE 05 · DENSE EMBEDDING",
      title: "Dense Embedding",
      latency: "92 ms",
      desc: "HuggingFace BGE transformer maps each chunk into a 384-dimensional dense semantic vector. L2 normalization ensures unit length (||v|| = 1.0) for accurate cosine similarity.",
      invariant: "INVARIANT: L2 Normalized (||v|| = 1.0)",
      spec: "TENSOR: 384 DIMENSIONS"
    },
    6: {
      label: "STAGE 06 · ATOMIC ZERO-LAST WRITE",
      title: "Atomic Zero-Last Write",
      latency: "11 ms",
      desc: "ChromaDB monotonic insertion with Chunk 0 written last as an atomic commit marker. Guarantees that interrupted uploads never leak uncommitted chunks to the retrieval index.",
      invariant: "INVARIANT: Monotonic Atomicity",
      spec: "MARKER: CHUNK 0 COMMITTED LAST"
    }
  };

  let activeStep = 1;
  let walkthroughTimer = null;
  let isWalkthroughPlaying = false;

  /* =========================================================================
     ACTIVE STAGE SYNCHRONIZATION
     ========================================================================= */

  function setActiveStage(stepNum, shouldScroll = false) {
    if (!STAGE_DATA[stepNum]) return;
    activeStep = stepNum;

    // Update Left Stage Rows
    stageRows.forEach(row => {
      const step = parseInt(row.dataset.step, 10);
      if (step === stepNum) {
        row.classList.add("is-active");
      } else {
        row.classList.remove("is-active");
      }
    });

    // Update Right Visual Cards
    cards.forEach(card => {
      const step = parseInt(card.dataset.step, 10);
      if (step === stepNum) {
        card.classList.add("is-active");
        if (shouldScroll && window.innerWidth >= 1024) {
          card.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }
      } else {
        card.classList.remove("is-active");
      }
    });

    // Update Active Badge
    if (activeBadge) {
      activeBadge.textContent = `STAGE 0${stepNum}`;
    }

    // Update Conduits
    conduits.forEach(conduit => {
      const fromStep = parseInt(conduit.dataset.from, 10);
      if (fromStep === stepNum) {
        conduit.classList.add("active-conduit");
      } else {
        conduit.classList.remove("active-conduit");
      }
    });

    // Update Stage Inspector
    const data = STAGE_DATA[stepNum];
    if (inspectorLabel) inspectorLabel.textContent = data.label;
    if (inspectorLatency) inspectorLatency.textContent = data.latency;
    if (inspectorDesc) inspectorDesc.textContent = data.desc;
    if (inspectorInvariant) inspectorInvariant.textContent = data.invariant;
    if (inspectorSpec) inspectorSpec.textContent = data.spec;

    // Update 3D Simulation Viewport State
    if (simViewport) {
      simViewport.className = simViewport.className.replace(/\bsim-stage-\d\b/g, "").trim();
      simViewport.classList.add(`sim-stage-${stepNum}`);
    }
    // Update Canvas Step Pips
    canvasPips.forEach(pip => {
      const dotStep = parseInt(pip.dataset.step, 10);
      if (dotStep === stepNum) {
        pip.classList.add("is-active");
      } else {
        pip.classList.remove("is-active");
      }
    });
    if (simChunksOverlay) {
      simChunksOverlay.style.opacity = stepNum === 4 ? "1" : "0";
      simChunksOverlay.style.pointerEvents = stepNum === 4 ? "auto" : "none";
    }
  }

  /* =========================================================================
     STAGE NAVIGATION: CHEVRONS ("TICKS") & CANVAS PIPS
     ========================================================================= */

  function slideNext() {
    stopWalkthrough();
    const nextStep = activeStep < 6 ? activeStep + 1 : 1;
    setActiveStage(nextStep, true);
  }

  function slidePrev() {
    stopWalkthrough();
    const prevStep = activeStep > 1 ? activeStep - 1 : 6;
    setActiveStage(prevStep, true);
  }


  // Canvas Pips Click Handlers
  canvasPips.forEach(pip => {
    const step = parseInt(pip.dataset.step, 10);
    pip.addEventListener("click", (e) => {
      e.stopPropagation();
      stopWalkthrough();
      setActiveStage(step, true);
    });
  });

  // Canvas Nav Chevrons
  if (btnCanvasPrev) {
    btnCanvasPrev.addEventListener("click", (e) => {
      e.stopPropagation();
      slidePrev();
    });
  }

  if (btnCanvasNext) {
    btnCanvasNext.addEventListener("click", (e) => {
      e.stopPropagation();
      slideNext();
    });
  }



  /* =========================================================================
     EVENT LISTENERS: LEFT ROWS & RIGHT CARDS
     ========================================================================= */

  stageRows.forEach(row => {
    const step = parseInt(row.dataset.step, 10);

    row.addEventListener("mouseenter", () => {
      stopWalkthrough();
      setActiveStage(step);
    });

    row.addEventListener("click", () => {
      stopWalkthrough();
      setActiveStage(step, true);
    });

    row.addEventListener("keydown", e => {
      if (e.key === "Enter" || e.key === " " || e.key === "Spacebar") {
        e.preventDefault();
        stopWalkthrough();
        setActiveStage(step, true);
      }
    });
  });

  cards.forEach(card => {
    const step = parseInt(card.dataset.step, 10);

    card.addEventListener("mouseenter", () => {
      stopWalkthrough();
      setActiveStage(step);
    });

    card.addEventListener("click", () => {
      stopWalkthrough();
      setActiveStage(step);
    });

    card.addEventListener("focus", () => {
      stopWalkthrough();
      setActiveStage(step);
    });
  });

  /* =========================================================================
     WALKTHROUGH TOUR CONTROLS
     ========================================================================= */

  function startWalkthrough() {
    isWalkthroughPlaying = true;
    if (btnWalkthrough) {
      btnWalkthrough.innerHTML = `<span class="material-symbols-outlined text-[15px]">pause</span><span>PAUSE TOUR</span>`;
    }

    function stepLoop() {
      let nextStep = activeStep + 1;
      if (nextStep > 6) nextStep = 1;
      setActiveStage(nextStep, true);
      walkthroughTimer = setTimeout(stepLoop, 1700);
    }

    walkthroughTimer = setTimeout(stepLoop, 1700);
  }

  function stopWalkthrough() {
    if (walkthroughTimer) {
      clearTimeout(walkthroughTimer);
      walkthroughTimer = null;
    }
    isWalkthroughPlaying = false;
    if (btnWalkthrough) {
      btnWalkthrough.innerHTML = `<span class="material-symbols-outlined text-[15px]">play_arrow</span><span>AUTOPLAY TOUR</span>`;
    }
  }

  if (btnWalkthrough) {
    btnWalkthrough.addEventListener("click", () => {
      if (isWalkthroughPlaying) {
        stopWalkthrough();
      } else {
        startWalkthrough();
      }
    });
  }

  if (btnReset) {
    btnReset.addEventListener("click", () => {
      stopWalkthrough();
      setActiveStage(1, true);
    });
  }

  /* =========================================================================
     3D TILT & PARALLAX PHYSICS
     ========================================================================= */

  let targetRotX = 0;
  let targetRotY = 0;
  let currentRotX = 0;
  let currentRotY = 0;
  let isPointerInside = false;
  let tiltRafId = null;

  function update3DTilt() {
    if (!container) return;
    if (!isPointerInside && Math.abs(currentRotX) < 0.01 && Math.abs(currentRotY) < 0.01) {
      container.style.transform = "rotateX(0deg) rotateY(0deg)";
      tiltRafId = null;
      return;
    }

    const factor = 0.12;
    currentRotX += (targetRotX - currentRotX) * factor;
    currentRotY += (targetRotY - currentRotY) * factor;

    container.style.transform = `rotateX(${currentRotX.toFixed(2)}deg) rotateY(${currentRotY.toFixed(2)}deg)`;
    tiltRafId = requestAnimationFrame(update3DTilt);
  }

  function handlePointerMove(e) {
    if (prefersReducedMotion) return;

    const rect = stage.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;

    const normX = (x / rect.width) * 2 - 1;
    const normY = (y / rect.height) * 2 - 1;

    const MAX_TILT = 3.5;
    targetRotX = -normY * MAX_TILT;
    targetRotY = normX * MAX_TILT;

    if (!tiltRafId) {
      tiltRafId = requestAnimationFrame(update3DTilt);
    }
  }

  function handlePointerEnter() {
    isPointerInside = true;
    if (!tiltRafId && !prefersReducedMotion) {
      tiltRafId = requestAnimationFrame(update3DTilt);
    }
  }

  function handlePointerLeave() {
    isPointerInside = false;
    targetRotX = 0;
    targetRotY = 0;
  }

  stage.addEventListener("pointermove", handlePointerMove, { passive: true });
  stage.addEventListener("pointerenter", handlePointerEnter);
  stage.addEventListener("pointerleave", handlePointerLeave);

  /* =========================================================================
     SECTION 3: THE JOURNEY OF A QUESTION (SCENARIOS & CITATION EVIDENCE)
     ========================================================================= */

  const btnScenarioPass = document.getElementById("btn-scenario-pass");
  const btnScenarioAbstain = document.getElementById("btn-scenario-abstain");

  const q1Text = document.getElementById("q1-input-text");
  const q1CharCount = document.getElementById("q1-char-count");
  const q3List = document.getElementById("q3-retrieval-list");
  const q3Badge = document.getElementById("q3-candidates-badge");
  const q4GateCard = document.getElementById("q4-gate-card");
  const q4ScoreDisplay = document.getElementById("q4-score-display");
  const q4ScoreBar = document.getElementById("q4-score-bar");
  const q4ScoreIndicator = document.getElementById("q4-score-indicator");
  const q4DecisionBadge = document.getElementById("q4-decision-badge");
  const q4bAbstainCard = document.getElementById("q4b-abstain-card");
  const q4bCostBadge = document.getElementById("q4b-cost-badge");
  const q4bSignalText = document.getElementById("q4b-signal-text");
  const q4bDissipationText = document.getElementById("q4b-dissipation-text");

  const q5Envelope = document.getElementById("q5-context-envelope");
  const q5TokensBadge = document.getElementById("q5-tokens-badge");
  const q6StreamStatus = document.getElementById("q6-stream-status");
  const q6StreamText = document.getElementById("q6-stream-text");
  const q6LatencyBadge = document.getElementById("q6-latency-badge");
  const q6VelocityBadge = document.getElementById("q6-velocity-badge");
  const q7CitationsList = document.getElementById("q7-citations-list");
  const q7SanitizedBadge = document.getElementById("q7-sanitized-badge");

  // Citation evidence box
  const evidenceTitle = document.getElementById("evidence-citation-title");
  const evidenceDoc = document.getElementById("evidence-source-doc");
  const evidenceQuote = document.getElementById("evidence-quote-text");
  const evidenceMatch = document.getElementById("evidence-match-status");
  const evidenceScore = document.getElementById("evidence-score-stat");

  const CITATION_DATA = {
    1: {
      title: "GROUNDED SOURCE PASSAGE · CITATION [1] (c_102)",
      doc: "DOC: kernel_cpu.pdf · Page 4",
      quote: "The Completely Fair Scheduler (CFS) implements process execution multiplexing using red-black trees indexed by vruntime. CPU execution time is allocated inversely proportional to task priority (nice value).",
      match: "✓ VERIFIED GROUND TRUTH MATCH",
      score: "COSINE SIMILARITY: 0.71 (CONFIDENCE: HIGH)"
    },
    2: {
      title: "GROUNDED SOURCE PASSAGE · CITATION [2] (c_104)",
      doc: "DOC: process_pcb.pdf · Page 8",
      quote: "Each Process Control Block (PCB) maintains execution context (registers, stack pointer, program counter) swapped atomically during voluntary or preemption context switches.",
      match: "✓ VERIFIED GROUND TRUTH MATCH",
      score: "COSINE SIMILARITY: 0.58 (CONFIDENCE: HIGH)"
    },
    3: {
      title: "GROUNDED SOURCE PASSAGE · CITATION [3] (c_108)",
      doc: "DOC: sched_algo.pdf · Page 12",
      quote: "Real-time scheduling policies SCHED_FIFO and SCHED_RR preempt normal CFS tasks immediately based on static priority levels [1..99] to enforce bounded latency.",
      match: "✓ VERIFIED GROUND TRUTH MATCH",
      score: "COSINE SIMILARITY: 0.49 (CONFIDENCE: PASS)"
    },
    4: {
      title: "UNGROUNDED REFERENCE PURGED · CITATION [4] (c_ghost)",
      doc: "DOC: NULL · Hallucination Suppressed",
      quote: "No candidate chunk in the ChromaDB vector index supported this speculative sentence. DocuMind citation reconciler dropped the token to prevent ungrounded claims.",
      match: "✕ HALLUCINATION PURGED",
      score: "COSINE SIMILARITY: < 0.10 (BELOW NOISE FLOOR)"
    }
  };

  function updateCitationEvidence(citeId) {
    const item = CITATION_DATA[citeId];
    if (!item) return;

    if (evidenceTitle) evidenceTitle.textContent = item.title;
    if (evidenceDoc) evidenceDoc.textContent = item.doc;
    if (evidenceQuote) evidenceQuote.textContent = `"${item.quote}"`;
    if (evidenceMatch) evidenceMatch.textContent = item.match;
    if (evidenceScore) evidenceScore.textContent = item.score;

    // Highlight citation chips
    document.querySelectorAll(".citation-chip").forEach(chip => {
      const c = parseInt(chip.dataset.cite, 10);
      if (c === citeId) {
        chip.classList.add("is-active");
      } else {
        chip.classList.remove("is-active");
      }
    });

    // Highlight retrieval tile cards
    const tileMap = { 1: 0, 2: 1, 3: 2 };
    const tileIdx = tileMap[citeId];
    const tiles = document.querySelectorAll(".retrieval-tile-card");
    tiles.forEach((tile, idx) => {
      if (idx === tileIdx) {
        tile.classList.add("is-cited");
      } else {
        tile.classList.remove("is-cited");
      }
    });
  }

  function bindCitationListeners() {
    document.querySelectorAll(".citation-chip").forEach(chip => {
      const citeId = parseInt(chip.dataset.cite, 10);
      chip.addEventListener("mouseenter", () => updateCitationEvidence(citeId));
      chip.addEventListener("click", () => updateCitationEvidence(citeId));
    });
  }

  function applyScenario(scenario) {
    if (scenario === "pass") {
      // Buttons
      if (btnScenarioPass) btnScenarioPass.classList.add("is-active");
      if (btnScenarioAbstain) btnScenarioAbstain.classList.remove("is-active");

      // Q1 Input
      if (q1Text) q1Text.innerHTML = `<span class="text-primary-container">›</span> Explain process scheduling in the OS kernel`;
      if (q1CharCount) q1CharCount.textContent = "47 / 2000 CHARACTERS";

      // Q3 Retrieval List
      if (q3List) {
        q3List.innerHTML = `
          <div class="retrieval-tile-card flex justify-between items-center text-primary-container p-1 rounded">
            <span>c_102 (kernel_cpu.pdf)</span>
            <span class="font-semibold">0.71</span>
          </div>
          <div class="retrieval-tile-card flex justify-between items-center text-primary-container p-1 rounded">
            <span>c_104 (process_pcb.pdf)</span>
            <span class="font-semibold">0.58</span>
          </div>
          <div class="retrieval-tile-card flex justify-between items-center text-primary-container p-1 rounded">
            <span>c_108 (sched_algo.pdf)</span>
            <span class="font-semibold">0.49</span>
          </div>
          <div class="retrieval-tile-card flex justify-between items-center text-on-surface-variant opacity-60 p-1 rounded">
            <span>c_210 (io_devices.pdf)</span>
            <span>0.32</span>
          </div>
          <div class="retrieval-tile-card flex justify-between items-center text-on-surface-variant opacity-60 p-1 rounded">
            <span>c_055 (memory_swap.pdf)</span>
            <span>0.24</span>
          </div>
        `;
      }
      if (q3Badge) q3Badge.textContent = "5 TILES RANKED";

      // Q4 Gate Card
      if (q4GateCard) q4GateCard.style.opacity = "1";
      if (q4ScoreDisplay) {
        q4ScoreDisplay.textContent = "0.71";
        q4ScoreDisplay.className = "font-metric-display text-[20px] text-tertiary";
      }
      if (q4ScoreBar) {
        q4ScoreBar.style.width = "71%";
        q4ScoreBar.className = "absolute left-0 top-0 bottom-0 bg-tertiary/20 transition-all";
      }
      if (q4ScoreIndicator) {
        q4ScoreIndicator.style.left = "71%";
        q4ScoreIndicator.className = "absolute top-0 bottom-0 w-1 bg-tertiary z-20 transition-all";
      }
      if (q4DecisionBadge) {
        q4DecisionBadge.className = "flex items-center gap-2 p-2 bg-tertiary/10 border border-tertiary/30 rounded font-code-sm text-tertiary text-[11px] transition-all";
        q4DecisionBadge.innerHTML = `<span class="material-symbols-outlined text-sm">verified</span><span>DECISION: 0.71 ≥ 0.35 (GATE PASS)</span>`;
      }

      // Q4B Abstain Card (Dimmed)
      if (q4bAbstainCard) q4bAbstainCard.style.opacity = "0.35";
      if (q4bCostBadge) q4bCostBadge.textContent = "₹0.00 SPENT";
      if (q4bSignalText) q4bSignalText.textContent = `> ABSTAIN_SIGNAL: "Inactive: evidence above threshold τ"`;
      if (q4bDissipationText) q4bDissipationText.textContent = "0 TOKEN DISSIPATION";

      // Q5 Context Envelope
      if (q5Envelope) {
        q5Envelope.innerHTML = `
          <div class="text-tertiary"># SYSTEM: Ground truth extraction</div>
          <div class="text-on-surface-variant">&lt;context&gt;</div>
          <div class="text-on-surface pl-2 border-l border-surface-variant">[1] c_102 ... [2] c_104 ... [3] c_108</div>
          <div class="text-on-surface-variant">&lt;/context&gt;</div>
          <div class="text-primary-container">&lt;question&gt; Explain process scheduling &lt;/question&gt;</div>
        `;
      }
      if (q5TokensBadge) q5TokensBadge.textContent = "1,712 TOKENS";

      // Q6 Inference
      if (q6StreamStatus) {
        q6StreamStatus.textContent = "STREAMING";
        q6StreamStatus.className = "text-tertiary";
      }
      if (q6StreamText) {
        q6StreamText.textContent = `"Process scheduling coordinates CPU execution quantum across active PCBs..."`;
      }
      if (q6LatencyBadge) q6LatencyBadge.textContent = "2,950 ms";
      if (q6VelocityBadge) q6VelocityBadge.textContent = "88 TOKENS / SEC";

      // Q7 Citations
      if (q7CitationsList) {
        q7CitationsList.innerHTML = `
          <div class="citation-chip flex items-center justify-between text-tertiary p-1 rounded border border-transparent cursor-pointer" data-cite="1">
            <span>[1] matched source tile c_102</span>
            <span>✓ VALID</span>
          </div>
          <div class="citation-chip flex items-center justify-between text-tertiary p-1 rounded border border-transparent cursor-pointer" data-cite="2">
            <span>[2] matched source tile c_104</span>
            <span>✓ VALID</span>
          </div>
          <div class="citation-chip flex items-center justify-between text-tertiary p-1 rounded border border-transparent cursor-pointer" data-cite="3">
            <span>[3] matched source tile c_108</span>
            <span>✓ VALID</span>
          </div>
          <div class="citation-chip flex items-center justify-between text-error line-through opacity-70 p-1 rounded border border-transparent cursor-pointer" data-cite="4">
            <span>[4] hallucinated ghost citation</span>
            <span>✕ DROPPED</span>
          </div>
        `;
        bindCitationListeners();
      }
      if (q7SanitizedBadge) q7SanitizedBadge.textContent = "3 VALID · 1 PURGED";

      updateCitationEvidence(1);
    } else {
      // Scenario: Hard Abstention
      if (btnScenarioPass) btnScenarioPass.classList.remove("is-active");
      if (btnScenarioAbstain) btnScenarioAbstain.classList.add("is-active");

      // Q1 Input
      if (q1Text) q1Text.innerHTML = `<span class="text-error">›</span> What is the revenue growth forecast for fiscal year 2027?`;
      if (q1CharCount) q1CharCount.textContent = "64 / 2000 CHARACTERS";

      // Q3 Retrieval List
      if (q3List) {
        q3List.innerHTML = `
          <div class="retrieval-tile-card flex justify-between items-center text-error opacity-70 p-1 rounded">
            <span>c_088 (accounting_stub.pdf)</span>
            <span class="font-semibold">0.22</span>
          </div>
          <div class="retrieval-tile-card flex justify-between items-center text-on-surface-variant opacity-50 p-1 rounded">
            <span>c_142 (disclaimer_text.pdf)</span>
            <span>0.19</span>
          </div>
          <div class="retrieval-tile-card flex justify-between items-center text-on-surface-variant opacity-40 p-1 rounded">
            <span>c_003 (license_gnu.pdf)</span>
            <span>0.11</span>
          </div>
          <div class="retrieval-tile-card flex justify-between items-center text-on-surface-variant opacity-30 p-1 rounded">
            <span>c_012 (changelog.pdf)</span>
            <span>0.08</span>
          </div>
        `;
      }
      if (q3Badge) q3Badge.textContent = "4 TILES RANKED (ALL < τ)";

      // Q4 Gate Card (Dimmed)
      if (q4GateCard) q4GateCard.style.opacity = "0.45";
      if (q4ScoreDisplay) {
        q4ScoreDisplay.textContent = "0.22";
        q4ScoreDisplay.className = "font-metric-display text-[20px] text-error";
      }
      if (q4ScoreBar) {
        q4ScoreBar.style.width = "22%";
        q4ScoreBar.className = "absolute left-0 top-0 bottom-0 bg-error/20 transition-all";
      }
      if (q4ScoreIndicator) {
        q4ScoreIndicator.style.left = "22%";
        q4ScoreIndicator.className = "absolute top-0 bottom-0 w-1 bg-error z-20 transition-all";
      }
      if (q4DecisionBadge) {
        q4DecisionBadge.className = "flex items-center gap-2 p-2 bg-error/10 border border-error/30 rounded font-code-sm text-error text-[11px] transition-all";
        q4DecisionBadge.innerHTML = `<span class="material-symbols-outlined text-sm">block</span><span>DECISION: 0.22 < 0.35 (GATE BLOCKED)</span>`;
      }

      // Q4B Abstain Card (Active / Illuminated)
      if (q4bAbstainCard) {
        q4bAbstainCard.style.opacity = "1";
        q4bAbstainCard.classList.add("ring-1", "ring-error/40");
      }
      if (q4bCostBadge) q4bCostBadge.textContent = "₹0.00 SPENT (SUPPRESSED)";
      if (q4bSignalText) q4bSignalText.textContent = `> ABSTAIN_SIGNAL: "No indexed passages provide sufficient verifiable evidence regarding fiscal 2027 revenue."`;
      if (q4bDissipationText) q4bDissipationText.textContent = "0 TOKENS DISPATCHED";

      // Q5 Context Envelope
      if (q5Envelope) {
        q5Envelope.innerHTML = `
          <div class="text-error"># RELEVANCE FILTER: Low confidence cutoff</div>
          <div class="text-on-surface-variant opacity-60">&lt;context&gt; EMPTY (LLM INVOCATION BLOCKED) &lt;/context&gt;</div>
          <div class="text-error">&lt;action&gt; RETURN DETERMINISTIC ABSTENTION &lt;/action&gt;</div>
        `;
      }
      if (q5TokensBadge) q5TokensBadge.textContent = "0 TOKENS (BLOCKED)";

      // Q6 Inference
      if (q6StreamStatus) {
        q6StreamStatus.textContent = "SUPPRESSED";
        q6StreamStatus.className = "text-error font-semibold";
      }
      if (q6StreamText) {
        q6StreamText.innerHTML = `<span class="text-error font-semibold">"DocuMind Abstains:</span> The uploaded document does not contain verifiable evidence regarding fiscal year 2027 revenue forecasts."`;
      }
      if (q6LatencyBadge) q6LatencyBadge.textContent = "0.2 ms";
      if (q6VelocityBadge) q6VelocityBadge.textContent = "0 TOKENS / SEC";

      // Q7 Citations
      if (q7CitationsList) {
        q7CitationsList.innerHTML = `
          <div class="flex items-center justify-between text-error/80 p-1 rounded font-code-sm text-[11px]">
            <span>[✕] All low-relevance passages suppressed</span>
            <span>0 CITATIONS</span>
          </div>
          <div class="flex items-center justify-between text-on-surface-variant opacity-60 p-1 rounded font-code-sm text-[11px]">
            <span>Zero hallucinated facts generated</span>
            <span>✓ SAFEGUARDED</span>
          </div>
        `;
      }
      if (q7SanitizedBadge) q7SanitizedBadge.textContent = "HARD ABSTENTION ENGAGED";

      // Evidence Box
      if (evidenceTitle) evidenceTitle.textContent = "RELEVANCE GATE · DETERMINISTIC ABSTENTION";
      if (evidenceDoc) evidenceDoc.textContent = "NO RELEVANT CHUNKS ABOVE τ 0.35";
      if (evidenceQuote) evidenceQuote.textContent = `"System safely suppressed generation. The document collection contains technical operating system architecture, and contains zero evidence regarding corporate fiscal 2027 revenue projections."`;
      if (evidenceMatch) evidenceMatch.textContent = "✕ INSUFFICIENT EVIDENCE (PROTECTION TRIGGERED)";
      if (evidenceScore) evidenceScore.textContent = "MAX COSINE SCORE: 0.22 (< THRESHOLD 0.35)";
    }
  }

  if (btnScenarioPass) {
    btnScenarioPass.addEventListener("click", () => applyScenario("pass"));
  }
  if (btnScenarioAbstain) {
    btnScenarioAbstain.addEventListener("click", () => applyScenario("abstain"));
  }

  // Initialize
  bindCitationListeners();
  setActiveStage(1);
  updateCitationEvidence(1);
})();
