
# syntax=docker/dockerfile:1.7
FROM python:3.11-slim

ARG DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 LANG=C.UTF-8 TZ=UTC

RUN apt-get update && apt-get install -y --no-install-recommends         git curl ca-certificates bash &&         rm -rf /var/lib/apt/lists/*

# Basic tools (curl/jq)
RUN set -eux; \
  if command -v apt-get >/dev/null 2>&1; then \
    apt-get update && apt-get install -y --no-install-recommends curl jq && \
    rm -rf /var/lib/apt/lists/*; \
  elif command -v apk >/dev/null 2>&1; then \
    apk add --no-cache curl jq; \
  elif command -v microdnf >/dev/null 2>&1; then \
    microdnf -y update && microdnf -y install curl jq && microdnf clean all; \
  elif command -v dnf >/dev/null 2>&1; then \
    dnf -y install curl jq && dnf clean all; \
  elif command -v yum >/dev/null 2>&1; then \
    yum -y install curl jq && yum clean all; \
  else \
    echo "No supported package manager found to install curl/jq" >&2; exit 1; \
  fi

# Build deps for psycopg2 et al.
RUN --mount=type=cache,target=/var/cache/apt \
    apt-get update && apt-get install -y --no-install-recommends \
      git ca-certificates build-essential pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

COPY requirements.txt /workspace/requirements.txt
RUN pip install --no-cache-dir -r /workspace/requirements.txt

COPY . /workspace

ENV WORKSPACE_DIR=/workspace/jobs OTEL_SERVICE_NAME=strands-codeops-agent

# Expose FastAPI on 8088
EXPOSE 8088

CMD ["uvicorn", "fastapi_app:app", "--host", "0.0.0.0", "--port", "8088"]
