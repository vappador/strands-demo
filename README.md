
# Strands CodeOps Agent (Python) — with Async FastAPI

End-to-end automation from a **requirement template → PR**, exposed via an async FastAPI:

- Parse requirement YAML
- Clone repo, create feature branch
- Plan and generate code + tests via LLM (structured output)
- Build & test in ephemeral Docker runner
- Commit, push, and open a PR
- Return a structured response (status, pr_url, logs)

## REST API

- `GET /health` → `{"ok": true}`
- `POST /run` → body: `{ "requirement_source": "<path-or-raw-YAML>" }`

Example:
```bash
curl -sS localhost:8088/run -X POST -H "Content-Type: application/json"       -d '{"requirement_source":"templates/requirement.example.yaml"}' | jq .
```

## Quick start

```bash
cp .env.example .env
# configure STRANDS_MODEL_PROVIDER + GITHUB_TOKEN

docker compose up --build -d
# then call the API as shown above
```

## Notes
- Build/test isolation via Docker runner; configure image+command in the template.
- Optional OpenTelemetry export if `OTEL_EXPORTER_OTLP_ENDPOINT` is set.
- Swap providers: Bedrock (default with AWS creds), OpenAI, or local Ollama.
