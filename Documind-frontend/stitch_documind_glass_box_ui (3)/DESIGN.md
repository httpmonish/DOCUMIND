---
name: Obsidian Telemetry
colors:
  surface: '#131313'
  surface-dim: '#131313'
  surface-bright: '#3a3939'
  surface-container-lowest: '#0e0e0e'
  surface-container-low: '#1c1b1b'
  surface-container: '#201f1f'
  surface-container-high: '#2a2a2a'
  surface-container-highest: '#353534'
  on-surface: '#e5e2e1'
  on-surface-variant: '#e6beb2'
  inverse-surface: '#e5e2e1'
  inverse-on-surface: '#313030'
  outline: '#ad897e'
  outline-variant: '#5c4038'
  surface-tint: '#ffb59f'
  primary: '#ffb59f'
  on-primary: '#5f1600'
  primary-container: '#ff571d'
  on-primary-container: '#531200'
  inverse-primary: '#af3100'
  secondary: '#adc6ff'
  on-secondary: '#002e6a'
  secondary-container: '#0566d9'
  on-secondary-container: '#e6ecff'
  tertiary: '#4edea3'
  on-tertiary: '#003824'
  tertiary-container: '#00a572'
  on-tertiary-container: '#00311f'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#ffdbd1'
  primary-fixed-dim: '#ffb59f'
  on-primary-fixed: '#3a0a00'
  on-primary-fixed-variant: '#862300'
  secondary-fixed: '#d8e2ff'
  secondary-fixed-dim: '#adc6ff'
  on-secondary-fixed: '#001a42'
  on-secondary-fixed-variant: '#004395'
  tertiary-fixed: '#6ffbbe'
  tertiary-fixed-dim: '#4edea3'
  on-tertiary-fixed: '#002113'
  on-tertiary-fixed-variant: '#005236'
  background: '#131313'
  on-background: '#e5e2e1'
  surface-variant: '#353534'
typography:
  headline-xl:
    fontFamily: Inter
    fontSize: 32px
    fontWeight: '600'
    lineHeight: 38px
    letterSpacing: -0.03em
  headline-lg:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 30px
    letterSpacing: -0.025em
  headline-sm:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '500'
    lineHeight: 24px
    letterSpacing: -0.015em
  body-lg:
    fontFamily: Inter
    fontSize: 15px
    fontWeight: '400'
    lineHeight: 22px
    letterSpacing: -0.01em
  body-sm:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 18px
    letterSpacing: 0em
  code-lg:
    fontFamily: JetBrains Mono
    fontSize: 13px
    fontWeight: '500'
    lineHeight: 20px
    letterSpacing: -0.01em
  code-sm:
    fontFamily: JetBrains Mono
    fontSize: 11px
    fontWeight: '400'
    lineHeight: 16px
    letterSpacing: 0em
  label-caps:
    fontFamily: JetBrains Mono
    fontSize: 10px
    fontWeight: '600'
    lineHeight: 14px
    letterSpacing: 0.08em
  metric-display:
    fontFamily: JetBrains Mono
    fontSize: 28px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.04em
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  gutter: 1rem
  gutter-dense: 0.5rem
  margin: 1.5rem
  margin-mobile: 0.75rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 0.75rem
  space-lg: 1rem
  space-xl: 1.5rem
---

## Brand & Style

This design system embodies the "Glass Box" philosophy: total observability, zero decorative opacity, and high-density technical utility. Designed specifically for AI systems engineers, retrieval specialists, and machine learning infrastructure teams, the UI strips away soft consumer gradients in favor of an instrumentation-grade command terminal.

The aesthetic fuses **Modern Technical Brutalism** with **Telemetry Precision**:
- **Radical Transparency:** Surfaces present raw system telemetry, vector retrieval chunking paths, token dissipation rates, and latency cascades directly on the glass.
- **Instrument-Grade Contrast:** Deep black voids provide maximum kinetic separation for signal states, vector routes, and active inference clusters.
- **Micro-Engineered Craft:** Hairline borders, razor grid lines, and monospaced telemetry tokens impart the tactile accuracy of high-end optical diagnostic tooling.
- **High-Velocity State Signaling:** Color is deployed strictly as functional state—never for superficial decoration. Glowing nodes, dynamic pipelines, and sharp status rings immediately communicate runtime health.

## Colors

Color functions as an active telemetry signal within a high-density, low-luminance workspace. Every color corresponds to execution state, pipeline activity, or structural demarcation.

### Core Canvas & Structure
- **Canvas Base (`#050505`):** The absolute grounding layer for the canvas, terminal, and base viewport.
- **Sub-Surface Tier (`#0B0B0B`):** Elevation layer for node panels, card containers, and graph canvas backdrops.
- **Surface Elevation (`#121212` / `#1A1A1A`):** Inspector sidebars, nested parameter cards, and modal sheets.
- **Structural Lines (`#222222`):** Primary 1px hairline dividers and blueprint grid structures.
- **Interactive Boundaries (`#333333`):** Hover boundaries, focused input perimeters, and active container rings.

### Signal & State Accents
- **Electric / Safety Orange (`#FF4B00` / `#FF5100`):** System-level focal accent, target execution markers, critical triggers, and active graph cursors.
- **Cobalt / Process Cyan (`#3B82F6`):** Active embedding transformations, running vector sweeps, dynamic token streams, and pipeline connector glows.
- **Emerald Green (`#10B981`):** Cache hits, verified cosine similarity thresholds, live operational sockets (`● LIVE`), and validated inference steps.
- **Muted Amber (`#F59E0B`):** Context window saturation thresholds, fallback rerank triggers, model throttling, and degraded memory warnings.
- **System Crimson (`#EF4444`):** Context window overflows, null retrievals, API timeouts, and critical RAG pipeline breaks.

## Typography

The typographic hierarchy implements a high-efficiency dual-type approach: **Inter** handles structural clarity and interface hierarchy, while **JetBrains Mono** powers operational logs, code telemetry, latency values, and node indices.

- **Tabular Figures & Alignment:** All numerical outputs, metrics, latency trackers, and token tallies must enforce `font-variant-numeric: tabular-nums` to eliminate jitter during real-time streaming.
- **Label Capitalization:** Micro-meta labels (e.g., `LATENCY_P99`, `SIM_SCORE`, `TOP_K`) must render in `label-caps` using full uppercase with expanded letter-spacing (`0.08em`) to guarantee scanability at micro-scales.
- **Terminal & Logs:** System stdout/stderr and raw chunk embeddings are rendered in `code-sm` with rigid vertical rhythm to preserve tabular column alignment.

## Layout & Spacing

The layout is built for high information density, multi-panel orchestration, and split-screen telemetry:

- **Structural Canvas:** Operates on an edge-to-edge docking model. The primary viewport accommodates collapsible parameter panels (320px fixed width), a dynamic interactive SVG node graph canvas (fluid width), and an inspectable log console (360px fixed or bottom-docked at 240px).
- **Blueprint Grid:** Graph surfaces feature a programmatic background mesh: 16px × 16px sub-grid dots (`rgba(255, 255, 255, 0.04)`) overlaid on 64px × 64px grid rules (`#141414`).
- **Density Modes:** 
  - Standard spacing (`space-md` / `space-lg`) applies to top-level command bars and parameter forms.
  - Dense spacing (`space-xs` / `space-sm`) governs vector candidate lists, token payload spans, and terminal lines to maximize vertical data visibility.

## Elevation & Depth

This system avoids blurred drop shadows and heavy skeumorphism, creating spatial depth instead through **Tonal Stacking**, **Razor Hairlines**, and **Luminescent States**:

- **Layer 0 (Canvas Base - `#050505`):** The infinite canvas background host for node architectures and trace visualizers.
- **Layer 1 (Tonal Panel - `#0B0B0B`):** Docked sidebars, canvas control bars, and terminal log viewports. Delimited by a crisp `1px solid #222222` border.
- **Layer 2 (Floating Instrument - `#121212`):** Inspectable cards, prompt chunk viewers, and pipeline node bodies. Edges feature a subtle top inset highlight: `box-shadow: inset 0 1px 0 0 rgba(255, 255, 255, 0.06)`.
- **Layer 3 (Overlays & Menus - `#1A1A1A`):** Quick-filter overlays, command palettes, and contextual inspector popovers. Framed by `1px solid #333333` with a focused dark ambient drop: `box-shadow: 0 12px 32px rgba(0, 0, 0, 0.85)`.
- **Luminescence (Active Signals):** When an SVG node or edge is actively processing or streaming tokens, it emits an electrical luminescence: `box-shadow: 0 0 16px -2px rgba(59, 130, 246, 0.45)`. Critical exceptions utilize: `box-shadow: 0 0 16px -2px rgba(255, 75, 0, 0.5)`.

## Shapes

The geometry balances technical angularity with high-precision pill primitives:

- **Base Containers & Structural Paneling:** Retain a sharp, engineered posture using soft corners (`0.25rem` / 4px). This preserves grid discipline across dense modular arrays.
- **Functional Chips & Interactive Pills:** Status badges, interactive triggers, pill buttons, and filter chips utilize a full capsule radius (`9999px`). The pill shape acts as an instant visual signifier for interactive actions or ephemeral system telemetry amidst the rigid, squared chassis.
- **Connector Nodes:** Circular anchor ports (8px diameter) with 2px borders, pinned strictly to geometric intersection points on pipeline nodes.

## Components

### Action Buttons
- **Pill Buttons:** Full capsule radius (`9999px`), 32px height for standard or 24px for compact inline actions.
  - *Primary (Trigger/Run):* Solid `#FF4B00` fill, `#050505` text, bold `code-sm` font. Hover shifts to `#FF5100` with `0 0 12px rgba(255, 75, 0, 0.4)`.
  - *Secondary (Inspect/Trace):* Background `#121212`, border `1px solid #333333`, text `#E5E5E5`. Hover shifts border to `#FF4B00` and text to `#FFFFFF`.
  - *Ghost / Monospace:* Zero background, `code-sm` text, `px-2 py-1`. Hover highlights to `#1A1A1A`.

### Status Indicators & Badges
- **Runtime Pills:** Pill-shaped badge (`9999px`) with `1px solid` border and `#0B0B0B` backdrop.
  - *Live State:* Border `#10B98133`, text `#10B981`. Prepends a pulsing status dot: `● LIVE` with an active 1.5s CSS pulse ring.
  - *Replay / Stepping State:* Border `#3B82F633`, text `#3B82F6`. Prefixes a phase glyph: `◐ REPLAY`.
  - *Context Warning:* Border `#F59E0B33`, text `#F59E0B`. Label specifies token saturation (e.g., `WARN: 98% CTX`).

### Pipeline Nodes & Connectors
- **Architecture Nodes:** Rectangular cards (`#121212`) framed in `1px solid #222222`. Header includes step type (`RETRIEVER`, `RERANKER`, `GENERATOR`) in `label-caps` alongside micro latency badges.
- **Vector Connectors:** Bezier SVG strokes connecting nodes.
  - *Idle:* 1.5px stroke `#222222`.
  - *Active Ingestion:* 2px stroke `#3B82F6` with animated dash-array flow (`stroke-dashoffset`) and cyan anchor rings.
  - *Fallback / Error:* 2px stroke `#FF4B00` with static highlight.

### Terminal Logs & Chunk Viewers
- Monospace output panels enclosed in `#080808` with `1px solid #1F1F1F`.
- Strict left gutter showing monotonic execution timestamps and line counts (`#555555`).
- Semantic syntax highlighting: Embeddings and vector IDs in `#3B82F6`, cosine metrics in `#10B981`, and query text in `#E5E5E5`.

### Metric Displays & Tabular Data
- **Telemetry Readouts:** Card container displaying single key metric (`metric-display`) with micro metric description (`label-caps`) docked at top-left and real-time delta indicators at bottom-right.
- **Data Tables:** Dense borders (`1px solid #1A1A1A`), stripped alternating row backgrounds (`#0B0B0B` / `#050505`). Header labels in `label-caps`. Hovering a table row spotlights matching vector nodes on the active canvas.

### Input Fields & Controls
- **Terminal Inputs:** Flat `#0B0B0B` background, `1px solid #222222` outline, inset `code-sm` typography with an active cursor in `#FF4B00`. Focused state intensifies border to `#FF4B00` without soft ring halos.
- **Toggles & Checkboxes:** Sharp 2px rounded checkboxes with high-contrast `#FF4B00` check state; pill switch sliders with dual green/gray telemetry states.