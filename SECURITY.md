# Security Policy

## Reporting Security Issues

We take the security of DocuMind seriously. If you discover a vulnerability, please report it responsibly following the guidelines below.

### Supported Reporting Methods
1. **GitHub Private Vulnerability Reporting**:
   Please submit a private report via the [Security Advisories](https://github.com/httpmonish/DOCUMIND/security/advisories) tab on GitHub.
2. **Security Contact Placeholder**:
   Direct security inquiries may be sent to `security-disclosure@documind.example` (placeholder awaiting repository owner configuration).

> [!IMPORTANT]
> **Please do not report security vulnerabilities via public GitHub issues, discussions, or pull requests.**

---

## Response Timeline and SLA
- **Initial Acknowledgment:** Within **48 business hours** of receipt.
- **Triage & Reproduction Assessment:** Within **5 business days**.
- **Fix & Advisory Release:** Coordinated disclosure target within **30 days**, or sooner depending on severity.

---

## Scope & Ground Rules
### In Scope
- Core RAG engine prompt injection vulnerabilities that bypass evidence isolation.
- Authentication, session lifecycle, and authorization bypasses (IDOR, privilege escalation).
- Server-Side Request Forgery (SSRF) and path traversal in upload or extraction pipelines.
- Browser security issues (Cross-Site Scripting, Content Security Policy bypasses).
- Unauthenticated access to private documents or vector indices.

### Out of Scope & Limitations
- Attacks requiring physical device access or root compromise of the host machine.
- Denial of service attacks caused by exhausting external paid LLM rate limits without a software defect.
- Theoretical vulnerabilities without a reproducible proof-of-concept.
- Note: No malware scanner or sanitizer detects 100% of malicious files or prompt injections. The application does not claim absolute security.

---

## Sensitive Data Guidelines
When preparing a report:
- **Do NOT** include real user documents, private PII, or actual production API keys.
- Use synthetic or redacted demonstration data.
- Include step-by-step reproduction instructions and minimal test fixtures.
