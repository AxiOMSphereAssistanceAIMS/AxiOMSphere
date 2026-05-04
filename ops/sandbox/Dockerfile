# AIMS Sandbox Container — Isolated Code Execution
# Purpose: Run untrusted/generated Python code with:
#   - No network access (no DNS, no outbound TCP/UDP)
#   - Strict resource limits (memory, CPU, file descriptors)
#   - Hard wall-clock timeout (enforced by parent process)
#   - Data processing libraries: pandas, openpyxl, numpy, scipy
#
# Build: docker build -f ops/sandbox/Dockerfile -t aims-sandbox:latest .
# Run:   docker run --rm --net=none --memory=1g --cpus=1 aims-sandbox:latest
#
# Based on: alpine-python minimal + data stack
FROM python:3.11-alpine AS base

LABEL maintainer="AxiOMSphere"
LABEL description="AIMS isolated code sandbox"

# Install build dependencies + runtime essentials (minimal)
RUN apk add --no-cache \
    build-base \
    libffi-dev \
    openssl-dev \
    musl-dev \
    gcc \
    g++ \
    gfortran \
    lapack-dev \
    openblas-dev

# Create non-root user for execution (security best practice)
RUN addgroup -g 1000 sandbox && \
    adduser -D -u 1000 -G sandbox -h /tmp -s /sbin/nologin sandbox

WORKDIR /tmp

# Copy requirements
COPY ops/sandbox/requirements.txt .

# Install Python packages
RUN pip install --no-cache-dir -r requirements.txt

# Final stage: minimal runtime image
FROM python:3.11-alpine

LABEL maintainer="AxiOMSphere"
LABEL description="AIMS isolated code sandbox (runtime)"

# Install runtime libraries only (no build tools)
RUN apk add --no-cache \
    libffi \
    openssl \
    lapack \
    openblas

# Copy Python site-packages from builder
COPY --from=base /usr/local/lib/python3.11 /usr/local/lib/python3.11

# Copy pip binary
COPY --from=base /usr/local/bin/pip* /usr/local/bin/

# Create non-root user
RUN addgroup -g 1000 sandbox && \
    adduser -D -u 1000 -G sandbox -h /tmp -s /sbin/nologin sandbox

# Create isolated temp working directory
RUN mkdir -p /tmp/sandbox-work && \
    chown -R sandbox:sandbox /tmp/sandbox-work

WORKDIR /tmp/sandbox-work

# Switch to non-root
USER sandbox

# Default command (entrypoint is empty to allow flexible command passing)
# Usage: docker run --rm --net=none aims-sandbox python3 -c "print('hello')"
CMD ["python3", "-u"]

# Security annotations
HEALTHCHECK NONE
