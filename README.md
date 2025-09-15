
# Strands CodeOps Agent (Python) — with Async FastAPI

End-to-end automation from a **requirement template → PR**, exposed via an async FastAPI:

- Parse requirement YAML
- Clone repo, create feature branch
- Plan and generate code + tests via LLM (structured output)
- Optional codebase search tool for additional context to generation
- Build & test in ephemeral Docker runner
- Commit, push, and open a PR
- Return a structured response (status, pr_url, logs)


## Project Structure
```
strands-demo
├── agent_main.py
├── app
│   ├── __init__.py
│   ├── models.py
│   ├── orchestrator.py
│   ├── runners.py
│   ├── runtime.py
│   ├── tools
│   │   ├── code_tools.py
│   │   ├── git_tools.py
│   │   ├── github_tools.py
│   │   ├── requirements_tool.py
│   │   └── search_context.py
│   └── utils.py
├── docker-compose.yml
├── Dockerfile
├── fastapi_app.py
├── jobs/
├── LICENSE
├── README.md
├── requirements.txt
├── templates
│   ├── requirement.example.yaml
│   └── requirement.write-tests.yaml
└── tests
    └── Dockerfile.polytest

```
## Class Diagram
```mermaid
classDiagram
    direction LR

    %% ----------------- Schemas / Models -----------------
    class Requirement {
      +str id
      +str title
      +str language
      +RepoSpec repo
      +BranchSpec branch
      +BuildSpec build
      +CodegenSpec codegen
      +GitHubSpec github
    }

    class BuildSpec {
      +str container_image
      +str workdir
      +str command
      +dict env
      +int timeout_seconds
      +int? cpu_shares
      +str? mem_limit
    }

    class ChangePlan {
      +str summary
      +List~str~ touched_files
    }

    class FileEdit {
      +str action  <<create|modify|delete>>
      +str path
      +str content
    }

    class TestResult {
      +bool passed
      +str logs
      +float duration_s
    }

    %% ----------------- Agent / Orchestration -----------------
    class AgentMain {
      +run_requirement(source) RequirementResult
    }

    class Orchestrator {
      +orchestrate(req: Requirement) RequirementResult
      -_plan_and_edit()
      -_build_and_test()
      -_open_pr()
    }

    class Runtime {
      +init_run_context()
      +logger
      +run_id
    }

    %% ----------------- Tools / Infra -----------------
    class RequirementsTool {
      +load_and_validate(source) Requirement
    }

    class CodeTools {
      +scan_repo(path) Inventory
      +plan_changes(req, inventory) ChangePlan
      +apply_edits(plan) List~FileEdit~
    }

    class GitTools {
      +clone(url, branch) str
      +create_branch(name) bool
      +commit_and_push(edits, message) str
    }

    class GitHubTools {
      +create_pr(base, head, title, body, labels, draft) str  <<pr_url>>
    }

    class DockerRunner {
      +build_and_test(spec: BuildSpec, workdir: str) TestResult
    }

    %% ----------------- External LLM Provider -----------------
    class StrandsAgents {
      <<external>>
      +tool decorators / ToolContext
      +LLM calls (Ollama/OpenAI/Bedrock)
    }

    %% ----------------- Relationships -----------------
    AgentMain --> RequirementsTool : uses
    AgentMain --> Orchestrator : invokes
    AgentMain --> Runtime : uses

    Orchestrator --> CodeTools : uses
    Orchestrator --> GitTools : uses
    Orchestrator --> DockerRunner : uses
    Orchestrator --> GitHubTools : uses
    Orchestrator --> Requirement : consumes
    Orchestrator --> BuildSpec : consumes
    Orchestrator --> ChangePlan : produces
    Orchestrator --> TestResult : consumes

    RequirementsTool --> Requirement : returns
    CodeTools --> ChangePlan : returns
    CodeTools --> FileEdit : returns
    CodeTools --> StrandsAgents : uses   %% LLM usage via @tool / ToolContext
    DockerRunner --> TestResult : returns



```

## Sequence Diagrams
```mermaid
sequenceDiagram
    autonumber
    participant Client as Client/CLI
    participant API as FastAPI (fastapi_app.py)
    participant Agent as agent_main.py
    participant Orchestrator as orchestrator.py
    participant ReqTool as tools/requirements_tool.py
    participant CodeTools as tools/code_tools.py
    participant LLM as Ollama / LLM Provider
    participant Git as tools/git_tools.py
    participant GitHub as tools/github_tools.py
    participant Runner as runners.py (DockerRunner)
    participant Models as models.py
    participant Runtime as runtime.py

    Client->>API: POST /run { requirement_source }
    API->>Agent: run_requirement(requirement_source)
    Agent->>ReqTool: load_and_validate(requirement_source)
    ReqTool-->>Agent: Requirement (Pydantic)
    Agent->>Runtime: init_run_context() / logging, IDs
    Agent->>Orchestrator: orchestrate(Requirement)

    Orchestrator->>Git: clone(repo.url, branch=default)
    Git-->>Orchestrator: local_repo_path

    Orchestrator->>CodeTools: scan_repo(local_repo_path)
    CodeTools-->>Orchestrator: inventory/summary

    Orchestrator->>CodeTools: plan_changes(Requirement, inventory)
    CodeTools->>LLM: prompt(requirement + inventory)
    LLM-->>CodeTools: ChangePlan (JSON)
    CodeTools-->>Orchestrator: ChangePlan (touched_files)

    Orchestrator->>Git: create_branch(feature/{id})
    Git-->>Orchestrator: branch_created

    Orchestrator->>CodeTools: apply_edits(ChangePlan)
    CodeTools->>LLM: prompt(diff/edits)
    LLM-->>CodeTools: list<FileEdit>
    CodeTools-->>Orchestrator: list<FileEdit>

    Orchestrator->>Git: commit_and_push(edits, message)
    Git-->>Orchestrator: pushed_ref

    Orchestrator->>Runner: build_and_test(buildSpec, workdir)
    Runner-->>Orchestrator: TestResult (pass/fail, logs)

    alt tests passed
      Orchestrator->>GitHub: create_pr(base=main, head=feature/{id}, labels)
      GitHub-->>Orchestrator: pr_url
      Orchestrator-->>Agent: success(status, pr_url, logs)
      Agent-->>API: JSON { status:"ok", pr_url, logs }
      API-->>Client: 200 { status:"ok", pr_url, logs }
    else tests failed
      Orchestrator-->>Agent: failure(status, logs)
      Agent-->>API: JSON { status:"failed", logs }
      API-->>Client: 200 { status:"failed", logs }
    end


```

# Strands Demo Project Architecture

The **Strands Demo** project is an autonomous code-ops agent built on [Strands Agents](https://strandsagents.com/).  
It takes structured requirements (YAML), edits repositories, runs builds/tests inside Docker, and opens GitHub PRs automatically.

---

# Strands Demo Project Architecture

The **Strands Demo** project is an autonomous code-ops agent built on [Strands Agents](https://strandsagents.com/).  
It takes structured requirements (YAML), edits repositories, runs builds/tests inside Docker, and opens GitHub PRs automatically.

---


---

# Option B — With Mermaid init (useful if your renderer needs it)

```markdown
# Strands Demo Project Architecture

# Strands Demo Project Architecture

## High-Level Workflow

flowchart TD
    A["Requirement YAML"] --> B["FastAPI Agent (fastapi_app.py)"]
    B --> C["Orchestrator (agent_main.py / orchestrator.py)"]
    C --> D["Code Tools (code_tools.py)"]
    C --> E["DockerRunner (runners.py)"]
    C --> F["GitHub Tools (git_tools.py + github_tools.py)"]

    E -->|"BuildSpec"| H["Jobs Workspace"]
    D --> H
    F --> G["GitHub Repo (branch + PR)"]

    subgraph Config_Infra
        I["Dockerfile / docker-compose.yml"]
        J["requirements.txt"]
        K["templates/"]
    end

    I --> E
    J --> E
    K --> D


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
- Configure search-context limits via `SEARCH_CONTEXT_MAX_RESULTS`,
  `SEARCH_CONTEXT_MAX_CHARS`, and `SEARCH_CONTEXT_LINES` (see `.env.example`).
