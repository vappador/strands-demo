
# syntax=docker/dockerfile:1.7
FROM python:3.11-slim

ARG DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 LANG=C.UTF-8 TZ=UTC

RUN apt-get update && apt-get install -y --no-install-recommends         git curl ca-certificates bash &&         rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

COPY requirements.txt /workspace/requirements.txt
RUN pip install --no-cache-dir -r /workspace/requirements.txt

COPY . /workspace

ENV WORKSPACE_DIR=/workspace/jobs OTEL_SERVICE_NAME=strands-codeops-agent

# Expose FastAPI on 8088
EXPOSE 8088

CMD ["uvicorn", "fastapi_app:app", "--host", "0.0.0.0", "--port", "8088"]
