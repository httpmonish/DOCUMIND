# syntax=docker/dockerfile:1
# DocuMind Production Hardened Container
# Implements:
# - Multi-stage build for minimal attack surface
# - Dedicated non-privileged user (documind, UID 10001)
# - Read-only root filesystem support
# - Drop all capabilities with no-new-privileges
# - Safe isolated storage directory under /app/data

FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install --no-install-recommends -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir --user -r requirements.txt

# Final minimal runtime image
FROM python:3.11-slim AS runner

# Security: Install runtime libraries only, purge package manager caches
RUN apt-get update && apt-get install --no-install-recommends -y \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create unprivileged system group & user
RUN groupadd -g 10001 documind && \
    useradd -u 10001 -g documind -s /sbin/nologin -M -d /app documind

WORKDIR /app

# Copy installed python site-packages from builder stage
COPY --from=builder /root/.local /home/documind/.local
ENV PATH=/home/documind/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Copy application source code
COPY --chown=documind:documind documind ./documind
COPY --chown=documind:documind Documind-frontend ./Documind-frontend
COPY --chown=documind:documind pyproject.toml ./

# Create dedicated persistent storage and temp directories with non-root ownership
RUN mkdir -p /app/data /app/tmp && \
    chown -R documind:documind /app/data /app/tmp && \
    chmod 700 /app/data /app/tmp

USER documind:documind

ENV DOCUMIND_HOME=/app/data
ENV DOCUMIND_ENV=production
ENV TMPDIR=/app/tmp

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://127.0.0.1:8000/healthz || exit 1

ENTRYPOINT ["python", "-m", "uvicorn", "documind.interfaces.api:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
