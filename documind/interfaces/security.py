"""documind/interfaces/security.py
Security utilities: client IP resolution, IPv6 /64 normalization,
prompt delimiter escaping, and security response headers.
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
from collections.abc import Sequence

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint


def normalize_ip(ip_str: str) -> str:
    """Parse and normalize an IP address string.
    IPv6 addresses are masked to a /64 prefix to prevent subnet-rotation evasion.
    IPv4 addresses are normalized to standard dotted-decimal form.
    """
    cleaned = ip_str.strip()
    try:
        ip = ipaddress.ip_address(cleaned)
    except ValueError:
        return "127.0.0.1"

    if isinstance(ip, ipaddress.IPv6Address):
        # Mask to /64 network address
        net = ipaddress.IPv6Network(f"{ip}/64", strict=False)
        return str(net.network_address)
    return str(ip)


def client_ip(
    request: Request,
    trusted_proxies: Sequence[str] = ("127.0.0.1", "::1"),
) -> str:
    """Resolve the genuine client IP address inspecting trusted reverse proxies.
    Traverses X-Forwarded-For right-to-left: trusting proxies until the first untrusted IP.
    Normalizes IPv6 to /64 subnet prefix.
    """
    remote_host = request.client.host if request.client else "127.0.0.1"

    trusted_set = set(trusted_proxies)
    # Check if remote direct connection is from a trusted proxy
    if remote_host not in trusted_set:
        return normalize_ip(remote_host)

    # Inspect X-Forwarded-For if available
    xff = request.headers.get("X-Forwarded-For")
    if not xff:
        return normalize_ip(remote_host)

    # Right-to-left evaluation
    hops = [h.strip() for h in xff.split(",") if h.strip()]
    if not hops:
        return normalize_ip(remote_host)

    # Walk backwards from rightmost hop
    selected_ip = remote_host
    for hop in reversed(hops):
        if hop in trusted_set:
            continue
        selected_ip = hop
        break

    return normalize_ip(selected_ip)


def hash_ip(ip_str: str) -> str:
    """Produce SHA-256 digest of client IP to prevent raw PII retention."""
    norm = normalize_ip(ip_str)
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:32]


# Regular expression matching XML-style delimiter tags used in RAG prompts
_DELIMITER_TAG_RE = re.compile(
    r"</?(?:document|chunk|source|context|system|instructions|query)[^>]*>",
    re.IGNORECASE,
)


def escape_chunk_delimiters(text: str) -> str:
    """Escape prompt delimiter tags inside untrusted user document text.
    Prevents prompt-injection attacks from breaking out of document wrappers.
    """

    def _sanitize(match: re.Match[str]) -> str:
        tag = match.group(0)
        return tag.replace("<", "&lt;").replace(">", "&gt;")

    return _DELIMITER_TAG_RE.sub(_sanitize, text)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Enforce defensive HTTP response headers across all responses."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response: Response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), camera=(), microphone=()"
        )
        return response
