/**
 * DocuMind Architecture Continuous Video-Like Animation Controller
 * Coordinated sequential timeline for the Isometric Exploded Stack diagram.
 * Eliminates object collisions with dedicated non-overlapping vertical zones.
 * Confined strictly to #hero-arch-diagram-wrap and its internal SVG.
 */
(function initDocuMindArchitectureAnimation() {
  const TOTAL_DURATION = 20000; // 20.0 seconds per cycle (deliberate, human-digestible rhythm)
  let currentTime = 0;
  let isPlaying = true;
  let currentOutcome = 'grounded'; // 'grounded' or 'abstain'
  let outcomePreference = 'auto'; // 'auto', 'grounded', 'abstain'
  let cycleCount = 0;
  let lastTimestamp = null;
  let animFrameId = null;

  // DOM Elements
  let wrapEl = null;
  let svgEl = null;
  let stageLabelEl = null;
  let liveDotEl = null;
  let playBtn = null;
  let playIcon = null;
  let playText = null;
  let replayBtn = null;
  let outcomeBtn = null;
  let scrubberProgress = null;
  let scrubberTrack = null;
  let telemetryEl = null;

  // SVG Layer Groups
  let layerDoc = null;
  let layerChunk = null;
  let layerVector = null;
  let layerStore = null;

  // SVG Sub-elements
  let docTopFace = null;
  let docLine1 = null;
  let docLine2 = null;
  let docLine3 = null;
  let docScanLine = null;
  let docVerifyTicks = null;
  let docValidationTag = null;
  let axisPulse = null;

  let chunkC0 = null;
  let chunkC1 = null;
  let chunkC2 = null;
  let chunkC3 = null;
  let chunkOverlap = null;

  let vBars = [];
  let vPeakSpark = null;
  let vPulseBeam = null;
  let vDimTag = null;

  let chromaTopEllipse = null;
  let chromaRipple = null;
  let chromaCommitTag = null;

  let queryCapsule = null;
  let queryRay = null;
  let citeS1 = null;
  let citeS2 = null;
  let outcomeGrounded = null;
  let outcomeAbstain = null;

  // Non-overlapping Baseline Vector Spike Heights (exact coordinates on Y=330..380 base plate)
  const defaultBars = [
    { x: 210, y1: 350, y2: 320 },
    { x: 230, y1: 354, y2: 310 },
    { x: 250, y1: 358, y2: 300 },
    { x: 270, y1: 362, y2: 290 },
    { x: 290, y1: 358, y2: 305 },
    { x: 310, y1: 354, y2: 312 },
    { x: 330, y1: 350, y2: 325 }
  ];

  function queryElements() {
    wrapEl = document.getElementById('hero-arch-diagram-wrap');
    if (!wrapEl) return false;

    svgEl = document.getElementById('arch-anim-svg');
    stageLabelEl = document.getElementById('arch-stage-label');
    liveDotEl = document.getElementById('arch-live-dot');
    playBtn = document.getElementById('arch-btn-play');
    playIcon = document.getElementById('arch-play-icon');
    playText = document.getElementById('arch-play-text');
    replayBtn = document.getElementById('arch-btn-replay');
    outcomeBtn = document.getElementById('arch-btn-outcome');
    scrubberProgress = document.getElementById('arch-scrubber-progress');
    scrubberTrack = document.getElementById('arch-scrubber-track');
    telemetryEl = document.getElementById('arch-timeline-time');

    layerDoc = document.getElementById('layer-doc');
    layerChunk = document.getElementById('layer-chunk');
    layerVector = document.getElementById('layer-vector');
    layerStore = document.getElementById('layer-store');

    docTopFace = document.getElementById('doc-top-face');
    docLine1 = document.getElementById('doc-line-1');
    docLine2 = document.getElementById('doc-line-2');
    docLine3 = document.getElementById('doc-line-3');
    docScanLine = document.getElementById('doc-scan-line');
    docVerifyTicks = document.getElementById('doc-verify-ticks');
    docValidationTag = document.getElementById('doc-validation-tag');
    axisPulse = document.getElementById('central-axis-pulse');

    chunkC0 = document.getElementById('chunk-c0');
    chunkC1 = document.getElementById('chunk-c1');
    chunkC2 = document.getElementById('chunk-c2');
    chunkC3 = document.getElementById('chunk-c3');
    chunkOverlap = document.getElementById('chunk-overlap-zones');

    vBars = [];
    for (let i = 0; i < 7; i++) {
      const b = document.getElementById(`v-bar-${i}`);
      if (b) vBars.push(b);
    }
    vPeakSpark = document.getElementById('v-peak-spark');
    vPulseBeam = document.getElementById('v-pulse-beam');
    vDimTag = document.getElementById('v-dim-tag');

    chromaTopEllipse = document.getElementById('chroma-top-ellipse');
    chromaRipple = document.getElementById('chroma-ripple');
    chromaCommitTag = document.getElementById('chroma-commit-tag');

    queryCapsule = document.getElementById('arch-query-capsule');
    queryRay = document.getElementById('arch-query-ray');
    citeS1 = document.getElementById('cite-s1');
    citeS2 = document.getElementById('cite-s2');
    outcomeGrounded = document.getElementById('arch-outcome-grounded');
    outcomeAbstain = document.getElementById('arch-outcome-abstain');

    return true;
  }

  function easeInOutQuad(t) {
    return t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t;
  }

  function clamp01(v) {
    return Math.max(0, Math.min(1, v));
  }

  function renderFrame(timeMs) {
    const tSec = timeMs / 1000;
    const progress = (timeMs / TOTAL_DURATION) * 100;

    // Scrubber & Footer Status
    if (scrubberProgress) scrubberProgress.style.width = `${progress.toFixed(2)}%`;
    if (telemetryEl) {
      const curSec = Math.floor(tSec).toString().padStart(2, '0');
      const curMs = Math.floor((tSec % 1) * 10);
      const outcomeText = currentOutcome === 'grounded' ? 'GROUNDED [S1][S2]' : 'ABSTAIN [τ < 0.35]';
      telemetryEl.innerHTML = `<span>00:${curSec}.${curMs} / 00:20</span> · <span class="active-outcome">${outcomeText}</span>`;
    }

    // =========================================================================
    // SCENE 1: UPLOAD (0.0s – 2.6s) · Your document enters DocuMind
    // =========================================================================
    if (timeMs >= 0 && timeMs < 2600) {
      const p = timeMs / 2600;
      if (stageLabelEl) stageLabelEl.textContent = '01 · UPLOAD: Your document enters DocuMind';

      // Keep downstream layers stationary and subdued
      if (layerChunk) layerChunk.style.opacity = '0.35';
      if (layerVector) layerVector.style.opacity = '0.35';
      if (layerStore) layerStore.style.opacity = '0.35';

      // Document gently floats into position
      if (layerDoc) {
        const docY = -25 + 25 * easeInOutQuad(Math.min(1, p * 1.8));
        const docOpacity = Math.min(1, p * 2.2);
        layerDoc.setAttribute('transform', `translate(0, ${docY.toFixed(1)})`);
        layerDoc.style.opacity = docOpacity;
      }

      // Scanning line passes across top face
      if (docScanLine) {
        if (p > 0.35 && p < 0.90) {
          const scanP = (p - 0.35) / 0.55;
          const startX = 200 + 40 * scanP;
          const startY = 52 + 35 * scanP;
          const endX = 340 + 40 * scanP;
          const endY = 97 + 35 * scanP;
          docScanLine.setAttribute('x1', startX.toFixed(1));
          docScanLine.setAttribute('y1', startY.toFixed(1));
          docScanLine.setAttribute('x2', endX.toFixed(1));
          docScanLine.setAttribute('y2', endY.toFixed(1));
          docScanLine.style.opacity = (Math.sin(scanP * Math.PI) * 0.95).toFixed(2);
        } else {
          docScanLine.style.opacity = '0';
        }
      }

      if (docVerifyTicks) {
        docVerifyTicks.style.opacity = p > 0.7 ? clamp01((p - 0.7) * 4).toFixed(2) : '0';
      }
      if (docValidationTag) {
        docValidationTag.style.opacity = p > 0.8 ? clamp01((p - 0.8) * 4).toFixed(2) : '0';
      }
      if (docTopFace) {
        docTopFace.setAttribute('stroke', p > 0.75 ? '#ff571d' : '#e5e2e1');
      }

      resetDownstream(0);
      return;
    }

    // =========================================================================
    // SCENE 2: EXTRACT (2.6s – 5.0s) · Readable text is extracted
    // =========================================================================
    if (timeMs >= 2600 && timeMs < 5000) {
      const p = (timeMs - 2600) / 2400;
      if (stageLabelEl) stageLabelEl.textContent = '02 · EXTRACT: Readable text is extracted from uploaded PDF';

      // Document lifts slightly (6px) to indicate extraction separation
      if (layerDoc) {
        const liftY = -6 * Math.sin(Math.min(1, p * 1.5) * Math.PI * 0.5);
        layerDoc.setAttribute('transform', `translate(0, ${liftY.toFixed(1)})`);
        layerDoc.style.opacity = '1';
      }
      if (docScanLine) docScanLine.style.opacity = '0';
      if (docValidationTag) docValidationTag.style.opacity = '1';

      // Text lines illuminate sequentially
      if (docLine1) {
        const l1P = clamp01(p * 3);
        docLine1.setAttribute('stroke', l1P > 0.4 ? '#ff8c53' : '#8A8690');
        docLine1.setAttribute('stroke-width', l1P > 0.4 ? '2' : '1.2');
      }
      if (docLine2) {
        const l2P = clamp01((p - 0.25) * 3);
        docLine2.setAttribute('stroke', l2P > 0.4 ? '#ff8c53' : '#8A8690');
        docLine2.setAttribute('stroke-width', l2P > 0.4 ? '2' : '1.2');
      }
      if (docLine3) {
        const l3P = clamp01((p - 0.5) * 3);
        docLine3.setAttribute('stroke', l3P > 0.4 ? '#ff8c53' : '#8A8690');
        docLine3.setAttribute('stroke-width', l3P > 0.4 ? '2' : '1.2');
      }

      // Indicator travels along the clear 35px separation channel from Document (Y=128) to Chunks (Y=165)
      if (axisPulse) {
        const pulseY = 128 + (165 - 128) * p;
        axisPulse.setAttribute('cy', pulseY.toFixed(1));
        axisPulse.style.opacity = (Math.sin(p * Math.PI) * 0.95).toFixed(2);
      }

      resetDownstream(1);
      return;
    }

    // =========================================================================
    // SCENE 3: CHUNK (5.0s – 8.0s) · Text is divided into smaller passages
    // =========================================================================
    if (timeMs >= 5000 && timeMs < 8000) {
      const p = (timeMs - 5000) / 3000;
      if (stageLabelEl) stageLabelEl.textContent = '03 · CHUNK: Text is divided into 200-w passages with 30-w overlap';

      // Document settles firmly into resting position
      if (layerDoc) {
        layerDoc.setAttribute('transform', 'translate(0, 0)');
        layerDoc.style.opacity = '0.9';
      }
      if (layerChunk) layerChunk.style.opacity = '1';
      if (docValidationTag) docValidationTag.style.opacity = '0';
      if (axisPulse) axisPulse.style.opacity = '0';

      // Introduce chunks sequentially into their designated, non-overlapping positions
      const chunkList = [
        { el: chunkC0, startP: 0.00, endP: 0.25, fromX: -18, fromY: 0 },
        { el: chunkC3, startP: 0.20, endP: 0.45, fromX: 0, fromY: -15 },
        { el: chunkC2, startP: 0.40, endP: 0.65, fromX: 18, fromY: 0 },
        { el: chunkC1, startP: 0.60, endP: 0.85, fromX: 0, fromY: 15 }
      ];

      chunkList.forEach(item => {
        if (!item.el) return;
        const poly = item.el.querySelector('polygon');
        const txt = item.el.querySelector('text');

        if (p < item.startP) {
          item.el.style.opacity = '0';
        } else if (p <= item.endP) {
          const prog = (p - item.startP) / (item.endP - item.startP);
          const eased = easeInOutQuad(prog);
          const curX = item.fromX * (1 - eased);
          const curY = item.fromY * (1 - eased);
          item.el.setAttribute('transform', `translate(${curX.toFixed(1)}, ${curY.toFixed(1)})`);
          item.el.style.opacity = eased.toFixed(2);

          if (poly) {
            poly.setAttribute('stroke', '#ff571d');
            poly.setAttribute('stroke-width', '1.8');
          }
          if (txt) txt.setAttribute('fill', '#ff8c53');
        } else {
          // Settled in position
          item.el.setAttribute('transform', 'translate(0, 0)');
          item.el.style.opacity = '1';
          if (poly) {
            poly.setAttribute('stroke', '#e5e2e1');
            poly.setAttribute('stroke-width', '1');
          }
          if (txt) txt.setAttribute('fill', '#8A8690');
        }
      });

      // Illuminate overlap regions after chunks have settled
      if (chunkOverlap) {
        if (p > 0.80) {
          const overlapP = (p - 0.80) / 0.20;
          chunkOverlap.style.opacity = (overlapP * 0.95).toFixed(2);
        } else {
          chunkOverlap.style.opacity = '0';
        }
      }

      resetDownstream(2);
      return;
    }

    // =========================================================================
    // SCENE 4: EMBED (8.0s – 11.0s) · Each passage receives a numerical representation
    // =========================================================================
    if (timeMs >= 8000 && timeMs < 11000) {
      const p = (timeMs - 8000) / 3000;
      if (stageLabelEl) stageLabelEl.textContent = '04 · EMBED: Each passage receives a 384-D numerical embedding';

      // Chunks stay stationary in their clear band
      if (chunkOverlap) chunkOverlap.style.opacity = '0.4';
      [chunkC0, chunkC1, chunkC2, chunkC3].forEach(c => {
        if (c) {
          c.style.opacity = '1';
          c.setAttribute('transform', 'translate(0, 0)');
        }
      });

      // Highlight active source chunk C_1
      if (chunkC1) {
        const poly = chunkC1.querySelector('polygon');
        if (poly) {
          poly.setAttribute('stroke', '#ff571d');
          poly.setAttribute('stroke-width', '1.8');
        }
      }

      // Connector beam flows from Chunk C_1 (Y=255) down to Vector peak (Y=290)
      if (vPulseBeam) {
        const beamP = clamp01(p * 2);
        vPulseBeam.style.opacity = (Math.sin(beamP * Math.PI) * 0.95).toFixed(2);
      }

      // Vector layer brightens
      if (layerVector) layerVector.style.opacity = '1';

      // Sequential illumination of the 7 vector bars from left to right
      vBars.forEach((bar, idx) => {
        const base = defau