# DocuMind Baseline Security Assessment Report

**Execution Date:** 2026-10-13  
**Branch:** `security/hardening`  
**Assessment Phase:** S0 - Threat Model and Baseline Audit  
**Tools Evaluated:**
1. **Bandit** (v1.9.4) - AST Static Application Security Testing (SAST) for Python
2. **Semgrep** (v1.180.0) - Multi-rule Semantic Static Analysis (`p/python`, `p/owasp-top-ten`)
3. **pip-audit** (v2.10.1) - Known CVE Software Composition Analysis (SCA) via OSV / PyPI
4. **Gitleaks** (v8.30.1) - Full Git Commit History Secret and Credential Scanner
5. **Trivy** (v0.75.0) - Container, Filesystem, and Dependency Security Scanner
6. **OWASP ZAP Baseline Scanner** (v2.16.0 / Docker Automation Framework) - Dynamic Application Security Testing (DAST) on live instance
7. **HTTP Security Header Audit** - Transport and Perimeter Response Inspection

---

## 1. Executive Summary & Severity Ranking

Across the pre-hardening baseline audit, a total of **32 findings** were identified across static code analysis, software supply chain, git history, and dynamic security controls.

### Findings Breakdown by Severity

| Severity | Count | Primary Impact Areas | Key Vulnerabilities Identified |
|:---|:---:|:---|:---|
| **CRITICAL** | 2 | Dependency Vulnerabilities | Remote code execution in ChromaDB standalone server components (CVE-2026-45829, CVE-2026-45833). |
| **HIGH** | 2 | Access Control & Dependency | Cross-tenant manipulation and authorization bypass in upstream ChromaDB (CVE-2026-45830, CVE-2026-45831). |
| **MEDIUM** | 7 | Dynamic Application Security & Network | Potential SSRF / URL scheme bypass in OAuth handler (`urllib.request.urlopen`), missing Content-Security-Policy (CSP) (ZAP 10038), missing Subresource Integrity (SRI) attributes (ZAP 90003), missing HSTS header, lack of `__Host-` / `Secure` flags on auth cookies, client-side token storage in `localStorage`. |
| **LOW** | 15 | Code Quality, Headers, & DOM Sinks | Subprocess invocation (`_extract_worker`), pseudo-random RNG in evals, over 60 unfiltered `innerHTML` sinks across frontend, missing `Permissions-Policy` (ZAP 10063), missing COOP/CORP/COEP headers (ZAP 90004), cross-domain script inclusions without hash verification (ZAP 10017), suspicious comments (ZAP 10027), `Server: uvicorn` header banner disclosure. |
| **INFORMATIONAL** | 6 | Git Repository Hygiene | Dummy test API keys and sample curl tokens in `README.md` and automated test fixtures. |

---

## 2. Ranked Findings Catalog

### [CRITICAL] SEC-01: Upstream ChromaDB Pre-Auth Remote Code Execution
- **Scanner:** Trivy (`CVE-2026-45829`, `CVE-2026-45833`) / pip-audit (`PYSEC-2026-311`)
- **Component:** `chromadb==1.5.9` (`requirements.txt`)
- **Impact:** Upstream ChromaDB standalone HTTP server contains vulnerabilities enabling arbitrary pre-authentication code injection.
- **Current Status / Evaluation:** DocuMind exclusively consumes ChromaDB in embedded library mode (`PersistentClient`) with 0 instances of `HttpClient` or `chroma run`. While the network attack surface is dormant, the dependency remains flagged in scanners until an updated safe release is published and pinned.

---

### [HIGH] SEC-02: Upstream ChromaDB Cross-Tenant Authorization Bypass
- **Scanner:** Trivy (`CVE-2026-45830`, `CVE-2026-45831`) / pip-audit (`PYSEC-2026-3813`, `3814`, `3815`)
- **Component:** `chromadb==1.5.9`
- **Impact:** Flaws in Chroma server multi-tenant authorization checks.
- **Current Status / Evaluation:** DocuMind currently relies on collection partitioning (`dm.store._collection`). Tenant-level isolation must be rigorously enforced at the application data access layer before querying vector collections.

---

### [MEDIUM] SEC-03: SSRF Risk in OAuth Token & Userinfo Retrieval
- **Scanner:** Bandit (`B310:blacklist:urllib-urlopen`)
- **Locations:** `documind/interfaces/api.py:2456`, `documind/interfaces/api.py:2468`
- **Code:**
  ```python
  with urllib.request.urlopen(token_req, timeout=10.0) as resp:
  ...
  with urllib.request.urlopen(userinfo_req, timeout=10.0) as resp:
  ```
- **Impact:** `urllib.request.urlopen` does not enforce permitted URI schemes (`https://` only) or validate against DNS rebinding / internal metadata endpoints.
- **Target Mitigation:** Enforce explicit HTTPS URL validation and migrate to hardened, timeout-bound outbound HTTP clients with strict scheme checking.

---

### [MEDIUM] SEC-04: Missing Content-Security-Policy (CSP) & Defense Headers
- **Scanner:** OWASP ZAP (`10038: Content Security Policy (CSP) Header Not Set`) / HTTP Header Audit
- **Locations:** `http://host.docker.internal:8000/`, `/app/chat.html`, `/app/console/code.html`
- **Impact:** Browsers loading `Documind-frontend` have zero CSP protections. Any injected XSS payload can execute arbitrary inline scripts and exfiltrate document tokens or user prompts.
- **Observed Response Headers:**
  - `Content-Security-Policy`: Missing
  - `Strict-Transport-Security`: Missing
  - `Permissions-Policy`: Missing
  - `Cross-Origin-Opener-Policy` (COOP): Missing
  - `Cross-Origin-Resource-Policy` (CORP): Missing
  - `Cross-Origin-Embedder-Policy` (COEP): Missing (ZAP 90004)
  - `Referrer-Policy`: Set to `strict-origin-when-cross-origin` instead of strict `no-referrer`.

---

### [MEDIUM] SEC-05: Missing Subresource Integrity (SRI) on Third-Party CDN Scripts
- **Scanner:** OWASP ZAP (`90003: Sub Resource Integrity Attribute Missing`, `10017: Cross-Domain JavaScript Source File Inclusion`)
- **Locations:** `/app/chat.html`, `/app/console/code.html`
- **Impact:** The application includes external CDN assets (e.g., Tailwind scripts, Material icons, fonts) without `integrity="..."` hashes, leaving clients vulnerable to CDN compromise or DNS hijacking.
- **Target Mitigation:** Self-host all fonts and scripts or enforce SRI hashes with strict fallback.

---

### [MEDIUM] SEC-06: Unhardened Session Cookies & JS-Readable Token Storage
- **Scanner:** HTTP Header Audit / Code Inspection
- **Locations:** `documind/interfaces/api.py` (`POST /api/demo/session`), `Documind-frontend/api.js`
- **Observed Behavior:**
  - `set-cookie: documind_session=...; HttpOnly; Max-Age=7200; Path=/; SameSite=lax` lacks the `Secure` flag and does not use the `__Host-` prefix.
  - The API returns the raw session token in the JSON response body (`{"session_id": "..."}`), which the frontend writes directly to `localStorage.setItem("documind_session_id", ...)` and reads in JavaScript.
- **Impact:** Compromise of the frontend environment via XSS leads immediately to full session theft.

---

### [LOW] SEC-07: Pervasive `innerHTML` Sinks Across Frontend
- **Scanner:** Static DOM Grep
- **Locations:** Over 60 occurrences across `chat-drawer.js`, `api.js`, `console/code.html`, `library/code.html`, `auth.html`
- **Observed Sinks:**
  - `tokenSpan.innerHTML = formattedText;` (Model stream output)
  - `citationsTray.innerHTML = citations.map(...)` (Citation markers and sources)
  - `uploadingCard.innerHTML = ...` (Untrusted filenames)
  - `eventsLogContainer.innerHTML = ...` (Unfiltered event parameters)
- **Impact:** Severe DOM-based XSS exposure whenever untrusted documents, filenames, or model outputs are rendered.

---

### [LOW] SEC-08: Subprocess Invocation Without OS Sandbox
- **Scanner:** Bandit (`B603`, `B404`)
- **Location:** `documind/interfaces/api.py:866` -> `documind/core/_extract_worker.py`
- **Impact:** While `_extract_worker.py` enforces a 60-second execution timeout and POSIX `RLIMIT_AS`, it currently executes under standard process privileges with network capabilities intact and read access to the entire host workspace.

---

### [LOW] SEC-09: Missing Permissions-Policy Header
- **Scanner:** OWASP ZAP (`10063: Permissions Policy Header Not Set`)
- **Locations:** `http://host.docker.internal:8000/app/api.js`, `chat-drawer.js`, `chat.html`, `console/code.html`
- **Impact:** Browser features (camera, microphone, geolocation, usb, payment) are not explicitly denied.

---

### [LOW] SEC-10: Non-Cryptographic Random Generator in Evaluation Metrics
- **Scanner:** Bandit (`B311`)
- **Location:** `documind/core/eval_metrics.py:156` (`random.Random(seed)`)
- **Impact:** Low risk; used exclusively for deterministic bootstrapping in offline metrics evaluation.

---

### [INFORMATIONAL] SEC-11: Hardcoded Test Keys in Repository History
- **Scanner:** Gitleaks (`v8.30.1`)
- **Findings:** 6 occurrences detected in `tests/test_api.py`, `tests/security/test_auth.py`, and `README.md` curl documentation.
- **Evaluation:** Verified to be synthetic dummy keys (`test_key_minimum_32_characters_long_for_security_checks`, `sk-documind-test-secret-key-32chars`) used for unit test assertions and usage examples. No live production credentials detected.
