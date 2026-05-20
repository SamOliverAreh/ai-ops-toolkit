# github-actions/docker/Dockerfile
# Multi-stage build for lean production image

# ── Stage 1: Builder ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

# System deps for building packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ curl git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt


# ── Stage 2: Runtime ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

LABEL org.opencontainers.image.title="AI Ops Toolkit"
LABEL org.opencontainers.image.description="Automated ML ops pipeline toolkit"
LABEL org.opencontainers.image.source="https://github.com/YOUR_USERNAME/ai-ops-toolkit"

WORKDIR /app

# Runtime system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl bash \
    && rm -rf /var/lib/apt/lists/*

# Non-root user
RUN useradd -m -u 1001 aiops
USER aiops

# Copy installed packages from builder
COPY --from=builder --chown=aiops:aiops /root/.local /home/aiops/.local
ENV PATH=/home/aiops/.local/bin:$PATH

# Copy source
COPY --chown=aiops:aiops scripts/ scripts/
COPY --chown=aiops:aiops configs/ configs/

# Create runtime dirs
RUN mkdir -p logs output logs/monitoring

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python -c "import sys; sys.exit(0)"

# Default: run health check
CMD ["bash", "scripts/bash/health_check.sh", "--json"]
