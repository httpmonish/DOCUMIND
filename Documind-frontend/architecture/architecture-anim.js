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
        const base = defaultBars[idx];
        if (!base) return;
        const barStartP = idx * 0.10;
        const barP = clamp01((p - barStartP) / 0.35);

        if (barP > 0) {
          const eased = easeInOutQuad(barP);
          // Rise from base plate y1 to resting height y2
          const currentY2 = base.y1 - (base.y1 - base.y2) * eased;
          bar.setAttribute('y2', currentY2.toFixed(1));
          bar.setAttribute('stroke', barP < 1 ? '#ff8c53' : '#ff571d');
          bar.setAttribute('stroke-width', barP < 1 ? '3' : (idx === 3 ? '3' : '2.5'));
        } else {
          bar.setAttribute('y2', base.y1.toString());
        }
      });

      // Peak spark node flare at the top of the vector layer (Y=290)
      if (vPeakSpark) {
        if (p > 0.5) {
          const sparkP = (p - 0.5) / 0.5;
          const radius = 3.5 + Math.sin(sparkP * Math.PI * 3) * 1.5;
          vPeakSpark.setAttribute('r', radius.toFixed(1));
          vPeakSpark.style.opacity = '1';
        } else {
          vPeakSpark.setAttribute('r', '3.5');
          vPeakSpark.style.opacity = '0.5';
        }
      }

      // Dimension indicator tag
      if (vDimTag) {
        vDimTag.style.opacity = p > 0.65 ? clamp01((p - 0.65) * 3).toFixed(2) : '0';
      }

      resetDownstream(3);
      return;
    }

    // =========================================================================
    // SCENE 5: STORE (11.0s – 13.8s) · The index makes passages searchable
    // =========================================================================
    if (timeMs >= 11000 && timeMs < 13800) {
      const p = (timeMs - 11000) / 2800;
      if (stageLabelEl) stageLabelEl.textContent = '05 · STORE: The index makes passages searchable in local storage';

      if (vDimTag) vDimTag.style.opacity = '0';
      if (vPulseBeam) vPulseBeam.style.opacity = '0';
      if (layerStore) layerStore.style.opacity = '1';

      // Vector indicator travels across the 45px separation from Vector base (Y=380) into Chroma (Y=430)
      if (axisPulse) {
        if (p < 0.6) {
          const travelP = p / 0.6;
          const pulseY = 380 + (430 - 380) * travelP;
          axisPulse.setAttribute('cy', pulseY.toFixed(1));
          axisPulse.style.opacity = (Math.sin(travelP * Math.PI) * 0.95).toFixed(2);
        } else {
          axisPulse.style.opacity = '0';
        }
      }

      // Chroma cylinder illuminates upon arrival
      if (chromaTopEllipse) {
        const ellipseActive = p > 0.35;
        chromaTopEllipse.setAttribute('stroke', ellipseActive ? '#ff571d' : '#e5e2e1');
        chromaTopEllipse.setAttribute('stroke-width', ellipseActive ? '1.8' : '1');
      }

      // Concentric confirmation ripple on top face
      if (chromaRipple) {
        if (p > 0.35) {
          const ripP = (p - 0.35) / 0.65;
          const rx = 30 + 65 * ripP;
          const ry = 8 + 16 * ripP;
          chromaRipple.setAttribute('rx', rx.toFixed(1));
          chromaRipple.setAttribute('ry', ry.toFixed(1));
          chromaRipple.style.opacity = ((1 - ripP) * 0.9).toFixed(2);
        } else {
          chromaRipple.style.opacity = '0';
        }
      }

      // Persistence commit badge
      if (chromaCommitTag) {
        chromaCommitTag.style.opacity = p > 0.55 ? clamp01((p - 0.55) * 3).toFixed(2) : '0';
      }

      resetDownstream(4);
      return;
    }

    // =========================================================================
    // SCENE 6: RETRIEVE (13.8s – 16.0s) · Relevant passages are selected for your question
    // =========================================================================
    if (timeMs >= 13800 && timeMs < 16000) {
      const p = (timeMs - 13800) / 2200;
      if (stageLabelEl) stageLabelEl.textContent = '06 · RETRIEVE: Relevant passages selected for your question';

      if (chromaRipple) chromaRipple.style.opacity = '0';
      if (chromaCommitTag) chromaCommitTag.style.opacity = '0.5';

      // User question capsule appears in top-left zone (Y=12)
      if (queryCapsule) {
        queryCapsule.style.opacity = clamp01(p * 2.5).toFixed(2);
      }

      // Query ray flows down toward Chroma index
      if (queryRay) {
        if (p > 0.25) {
          queryRay.style.opacity = clamp01((p - 0.25) * 2.5).toFixed(2);
        } else {
          queryRay.style.opacity = '0';
        }
      }

      // Chunks highlight: selected evidence vs subdued non-relevant chunks
      if (currentOutcome === 'grounded') {
        if (chunkC1) {
          chunkC1.classList.add('is-retrieved');
          chunkC1.classList.remove('is-subdued');
        }
        if (chunkC2) {
          chunkC2.classList.add('is-retrieved');
          chunkC2.classList.remove('is-subdued');
        }
        if (chunkC0) {
          chunkC0.classList.remove('is-retrieved');
          chunkC0.classList.add('is-subdued');
        }
        if (chunkC3) {
          chunkC3.classList.remove('is-retrieved');
          chunkC3.classList.add('is-subdued');
        }

        // Citation badges [S1] and [S2] appear in clear zone above chunks (Y=175)
        if (citeS1) citeS1.style.opacity = clamp01(p * 2.5).toFixed(2);
        if (citeS2) citeS2.style.opacity = clamp01((p - 0.2) * 2.5).toFixed(2);
      } else {
        // Abstention case: evidence is insufficient, all chunks remain subdued
        [chunkC0, chunkC1, chunkC2, chunkC3].forEach(c => {
          if (c) {
            c.classList.remove('is-retrieved');
            c.classList.add('is-subdued');
          }
        });
        if (citeS1) citeS1.style.opacity = '0';
        if (citeS2) citeS2.style.opacity = '0';
      }

      resetDownstream(5);
      return;
    }

    // =========================================================================
    // SCENE 7: VERIFY (16.0s – 18.0s) · The system checks whether evidence is sufficient
    // =========================================================================
    if (timeMs >= 16000 && timeMs < 18000) {
      if (stageLabelEl) stageLabelEl.textContent = '07 · VERIFY: The system checks whether evidence is sufficient';
      if (queryCapsule) queryCapsule.style.opacity = '1';
      if (queryRay) queryRay.style.opacity = '0.35';

      resetDownstream(6);
      return;
    }

    // =========================================================================
    // SCENE 8: ANSWER (18.0s – 20.0s) · DocuMind provides supported info with citations or abstains
    // =========================================================================
    if (timeMs >= 18000 && timeMs <= 20000) {
      const p = (timeMs - 18000) / 2000;

      if (currentOutcome === 'grounded') {
        if (stageLabelEl) stageLabelEl.textContent = '08 · ANSWER: Supported answer verified with citations [S1][S2]';
        if (outcomeGrounded) outcomeGrounded.style.opacity = clamp01(p * 3).toFixed(2);
        if (outcomeAbstain) outcomeAbstain.style.opacity = '0';
        if (citeS1) citeS1.style.opacity = '1';
        if (citeS2) citeS2.style.opacity = '1';
      } else {
        if (stageLabelEl) stageLabelEl.textContent = '08 · ANSWER: DocuMind abstains (insufficient evidence in corpus)';
        if (outcomeAbstain) outcomeAbstain.style.opacity = clamp01(p * 3).toFixed(2);
        if (outcomeGrounded) outcomeGrounded.style.opacity = '0';
        if (citeS1) citeS1.style.opacity = '0';
        if (citeS2) citeS2.style.opacity = '0';
      }

      // Smooth fade transition at the very end to loop back to Scene 1
      if (p > 0.90) {
        const fadeP = 1 - (p - 0.90) / 0.10;
        if (queryCapsule) queryCapsule.style.opacity = fadeP.toFixed(2);
        if (outcomeGrounded) outcomeGrounded.style.opacity = fadeP.toFixed(2);
        if (outcomeAbstain) outcomeAbstain.style.opacity = fadeP.toFixed(2);
      }
    }
  }

  function resetDownstream(stageIndex) {
    if (stageIndex < 7) {
      if (outcomeGrounded) outcomeGrounded.style.opacity = '0';
      if (outcomeAbstain) outcomeAbstain.style.opacity = '0';
    }
    if (stageIndex < 6) {
      if (citeS1) citeS1.style.opacity = '0';
      if (citeS2) citeS2.style.opacity = '0';
      [chunkC0, chunkC1, chunkC2, chunkC3].forEach(c => {
        if (c) {
          c.classList.remove('is-retrieved');
          c.classList.remove('is-subdued');
        }
      });
    }
    if (stageIndex < 5) {
      if (queryCapsule) queryCapsule.style.opacity = '0';
      if (queryRay) queryRay.style.opacity = '0';
    }
    if (stageIndex < 4) {
      if (chromaRipple) chromaRipple.style.opacity = '0';
      if (chromaCommitTag) chromaCommitTag.style.opacity = '0';
      if (chromaTopEllipse) {
        chromaTopEllipse.setAttribute('stroke', '#e5e2e1');
        chromaTopEllipse.setAttribute('stroke-width', '1');
      }
    }
    if (stageIndex < 3) {
      if (vPulseBeam) vPulseBeam.style.opacity = '0';
      if (vDimTag) vDimTag.style.opacity = '0';
      vBars.forEach((bar, idx) => {
        const base = defaultBars[idx];
        if (base) {
          bar.setAttribute('y2', base.y2.toString());
          bar.setAttribute('stroke', '#ff571d');
          bar.setAttribute('stroke-width', idx === 3 ? '3' : '2.5');
        }
      });
    }
    if (stageIndex < 2) {
      if (chunkOverlap) chunkOverlap.style.opacity = '0';
      [chunkC0, chunkC1, chunkC2, chunkC3].forEach(c => {
        if (c) {
          c.setAttribute('transform', 'translate(0, 0)');
          const poly = c.querySelector('polygon');
          if (poly) {
            poly.setAttribute('stroke', '#e5e2e1');
            poly.setAttribute('stroke-width', '1');
          }
        }
      });
    }
    if (stageIndex < 1) {
      if (axisPulse) axisPulse.style.opacity = '0';
      if (docLine1) { docLine1.setAttribute('stroke', '#8A8690'); docLine1.setAttribute('stroke-width', '1.2'); }
      if (docLine2) { docLine2.setAttribute('stroke', '#8A8690'); docLine2.setAttribute('stroke-width', '1.2'); }
      if (docLine3) { docLine3.setAttribute('stroke', '#8A8690'); docLine3.setAttribute('stroke-width', '1.2'); }
    }
  }

  function tick(timestamp) {
    if (!lastTimestamp) lastTimestamp = timestamp;
    const dt = timestamp - lastTimestamp;
    lastTimestamp = timestamp;

    if (isPlaying) {
      currentTime += dt;
      if (currentTime >= TOTAL_DURATION) {
        currentTime = 0;
        cycleCount++;

        if (outcomePreference === 'auto') {
          currentOutcome = cycleCount % 2 === 0 ? 'grounded' : 'abstain';
        } else {
          currentOutcome = outcomePreference;
        }
      }
      renderFrame(currentTime);
    }

    animFrameId = requestAnimationFrame(tick);
  }

  function setPlayState(playing) {
    isPlaying = playing;
    if (playIcon) playIcon.textContent = isPlaying ? 'pause' : 'play_arrow';
    if (playText) playText.textContent = isPlaying ? 'PAUSE' : 'PLAY';
    if (liveDotEl) {
      if (isPlaying) {
        liveDotEl.classList.remove('is-paused');
      } else {
        liveDotEl.classList.add('is-paused');
      }
    }
    if (!isPlaying && stageLabelEl) {
      stageLabelEl.textContent = `[PAUSED] ${stageLabelEl.textContent.replace('[PAUSED] ', '')}`;
    }
  }

  function replay() {
    currentTime = 0;
    lastTimestamp = performance.now();
    setPlayState(true);
    renderFrame(0);
  }

  function toggleOutcome() {
    if (outcomePreference === 'auto') {
      outcomePreference = 'grounded';
      currentOutcome = 'grounded';
    } else if (outcomePreference === 'grounded') {
      outcomePreference = 'abstain';
      currentOutcome = 'abstain';
    } else {
      outcomePreference = 'auto';
      currentOutcome = cycleCount % 2 === 0 ? 'grounded' : 'abstain';
    }

    if (outcomeBtn) {
      outcomeBtn.textContent = `MODE: ${outcomePreference.toUpperCase()}`;
    }
  }

  function attachListeners() {
    if (playBtn) {
      playBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        setPlayState(!isPlaying);
      });
    }

    if (replayBtn) {
      replayBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        replay();
      });
    }

    if (outcomeBtn) {
      outcomeBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        toggleOutcome();
      });
    }

    if (scrubberTrack) {
      scrubberTrack.addEventListener('click', (e) => {
        const rect = scrubberTrack.getBoundingClientRect();
        const clickX = e.clientX - rect.left;
        const seekPct = Math.max(0, Math.min(1, clickX / rect.width));
        currentTime = seekPct * TOTAL_DURATION;
        renderFrame(currentTime);
      });
    }

    if (wrapEl) {
      wrapEl.setAttribute('tabindex', '0');
      wrapEl.addEventListener('keydown', (e) => {
        if (e.code === 'Space') {
          e.preventDefault();
          setPlayState(!isPlaying);
        } else if (e.code === 'KeyR') {
          e.preventDefault();
          replay();
        }
      });
    }

    try {
      const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
      if (motionQuery.matches) {
        setPlayState(false);
        currentTime = 9000;
        renderFrame(currentTime);
        if (stageLabelEl) stageLabelEl.textContent = 'MOTION REDUCED · STATIC REPOSITORY TOPOLOGY';
      }
      motionQuery.addEventListener('change', (e) => {
        if (e.matches) {
          setPlayState(false);
          renderFrame(9000);
          if (stageLabelEl) stageLabelEl.textContent = 'MOTION REDUCED · STATIC REPOSITORY TOPOLOGY';
        }
      });
    } catch (_) {}
  }

  function init() {
    if (!queryElements()) {
      setTimeout(init, 100);
      return;
    }

    attachListeners();
    renderFrame(0);
    lastTimestamp = performance.now();
    animFrameId = requestAnimationFrame(tick);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
