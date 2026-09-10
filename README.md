# AI Agent Project

AI Agent Project는 사용자의 프로젝트 요구사항을 바탕으로 **명세 생성 → 구현 계획 수립 → 단계별 코드 실행 → 요구사항 검증 → 체크포인트 승인 → 프로젝트 완료**까지 수행하는 lifecycle 기반 AI coding agent입니다.

CLI와 FastAPI 인터페이스를 제공하며, CLI에서는 프로젝트 실행 상태를 JSON snapshot으로 영속화하여 프로세스가 종료된 이후에도 이전 프로젝트 상태를 복원할 수 있습니다.

---

## 주요 기능

* 자연어 프로젝트 요구사항 기반 Specification 생성
* Specification 기반 Implementation Plan 생성
* 요구사항과 구현 작업 간 Traceability 검증
* 프로젝트를 여러 Phase로 분할하여 단계별 실행
* OpenAI 기반 Coding Agent
* Tool Calling 기반 파일 및 Shell 작업
* Workspace 탐색 및 변경
* Requirement Acceptance Validation
* 실패한 요구사항에 대한 Repair 처리
* Phase별 Checkpoint
* 명시적 lifecycle decision

  * `approve`
  * `retry`
  * `request-changes`
  * `stop`
* CLI 기반 프로젝트 실행
* FastAPI 기반 Project Lifecycle API
* CLI Project Run JSON 영속 저장
* 프로젝트 실행 상태 복원
* Unit / Integration / E2E 테스트

---

# Architecture

전체 프로젝트 실행 흐름은 다음과 같습니다.

```text
User Project Request
        │
        ▼
Specification
        │
        ▼
Implementation Plan
        │
        ▼
Project Run
        │
        ▼
┌───────────────────────┐
│       Phase P1        │
│                       │
│  Agent Execution      │
│        │              │
│        ▼              │
│  Tool Calls           │
│        │              │
│        ▼              │
│  Workspace Changes    │
│        │              │
│        ▼              │
│ Requirement Validation│
│        │              │
│        ▼              │
│ Repair (if required)  │
└──────────┬────────────┘
           │
           ▼
      Checkpoint
           │
    ┌──────┼───────────────┐
    │      │        │      │
 approve retry request   stop
                changes
    │
    ▼
Next Phase
    │
    ▼
   ...
    │
    ▼
Completed
```

CLI와 FastAPI는 동일한 Project Application Service를 사용하지만 저장 방식은 다릅니다.

```text
                 ProjectApplicationService
                           │
              ┌────────────┴────────────┐
              │                         │
             CLI                     FastAPI
              │                         │
              ▼                         ▼
    FileProjectRunStore      InMemoryProjectRunStore
              │
              ▼
       JSON Snapshots
```

---

# Requirements

* Python 3.12+
* `uv`
* OpenAI API Key

주요 dependency:

* FastAPI
* OpenAI Python SDK
* Pydantic
* HTTPX
* pytest
* Ruff

---

# Installation

저장소를 clone합니다.

```bash
git clone <repository-url>
cd ai-agent-project
```

의존성을 설치합니다.

```bash
uv sync
```

CLI가 정상적으로 등록됐는지 확인합니다.

```bash
uv run ai-agent --help
```

또는 활성화된 가상환경에서는:

```bash
ai-agent --help
```

---

# Environment Configuration

OpenAI API를 사용하기 위해 API Key를 환경변수로 설정합니다.

Linux / macOS:

```bash
export OPENAI_API_KEY="your-api-key"
```

현재 shell에서 확인:

```bash
test -n "$OPENAI_API_KEY" && echo "API key configured"
```

보안을 위해 API Key를 코드나 Git 저장소에 직접 저장하지 않는 것을 권장합니다.

예를 들어 `.env`를 사용하는 경우 `.gitignore`에 다음 항목을 추가합니다.

```gitignore
.env
```

---

# User LLM Provider Configuration (Phase 6A)

설정 서비스는 Desktop UI와 독립적입니다. CLI에서도 동일한 서비스를 사용합니다.

```bash
uv run ai-agent config llm set --base-url https://api.openai.com/v1 --model gpt-5-mini --timeout-seconds 90
uv run ai-agent config llm show
uv run ai-agent config llm test
```

`test`만 실제 provider 요청을 수행합니다. `show`와 `set`은 네트워크를 사용하지 않습니다.
Custom endpoint는 `--base-url http://localhost:8000/v1 --model my-model`처럼 설정합니다.
잘못된 URL, 모델 또는 provider 응답에 대해 OpenAI나 다른 모델로 fallback하지 않습니다.

- 기본 설정 파일: `$XDG_CONFIG_HOME/ai-agent/llm.json` (절대 경로인 경우), 아니면 `~/.config/ai-agent/llm.json`.
- 별도 파일로 CLI 설정을 검사하려면 `config llm --config-file PATH show|set|test`를 사용합니다. Workflow는 기본 사용자 설정 경로를 사용합니다.
- 필드별 우선순위: 명시적으로 지정한 runtime 필드 > 저장된 필드 > 환경변수 > 기본값. 기존 constructor의 `model`, `api_key`, `request_timeout_seconds` 인자는 runtime override입니다.
- 환경변수: `OPENAI_BASE_URL`, `OPENAI_MODEL`, `OPENAI_TIMEOUT_SECONDS`, `OPENAI_API_KEY`. 기본값은 OpenAI `/v1`, `gpt-5-mini`, timeout 90초입니다.
- API key는 runtime 인자 또는 `OPENAI_API_KEY`에서만 읽습니다. 일반 JSON에 저장하지 않으며 repr/공개 serialization에서도 제외합니다. CLI에는 key 인자를 두지 않습니다.
- 저장은 현재 유효한 비밀정보 제외 설정 전체를 기록합니다. 따라서 저장 후에는 해당 필드들이 환경변수보다 우선합니다.
- 기존과 같이 `.env`는 애플리케이션이 직접 읽지 않습니다. 필요하면 launcher에서 환경으로 전달합니다 (`uv run --env-file .env ai-agent ...`).
- URL에는 인증정보, query 또는 fragment를 넣지 않습니다. 인증은 API key header로만 전달합니다.
- 요청 실패는 원문 오류/응답 body 없이 안전한 오류로 전달하며 자동 재시도는 하지 않습니다.

Python UI/호출자는 `ProviderConfigService().save(config)`, `.resolve(config)`, `.test_connection(config)`를 사용할 수 있습니다.
`ProviderConfig(api_key=..., base_url=..., model=..., timeout_seconds=...)`를 기존 provider의 `config=` 또는
`create_default_*_service(..., provider_config=config)`에 전달할 수도 있습니다. 설정 변경은 새로 구성하는 서비스에 적용됩니다.

Developer, Researcher와 Hybrid는 모두 동일한 설정 경로를 사용합니다. 설정/credential은 workflow snapshot,
artifact catalog, handoff나 provenance에 추가되지 않습니다. Connection test는 짧은 Responses 요청만 보내며 workflow를 만들거나 진행하지 않습니다.

호환 endpoint에는 **Responses API** 지원이 필요합니다. Structured output, tool calling, Researcher web search 등은
해당 workflow가 기존에 요구하던 기능을 endpoint가 지원해야 합니다. Connection test 성공이 모든 기능의 지원을 보장하지는 않습니다.
Chat-Completions-only endpoint 변환, OS credential store, PySide6 UI 및 packaging은 이번 단계에 포함하지 않습니다.

Provider-free acceptance:

```bash
uv run pytest tests/llm/test_provider_config.py tests/integration/test_provider_config_acceptance.py -q
```

실제 provider acceptance는 명시적인 요청이 있을 때만 실행합니다.

---

# Quick Start

예제 프로젝트 요구사항이 다음 경로에 포함되어 있습니다.

```text
examples/todo_api.md
```

테스트용 workspace를 생성합니다.

```bash
mkdir -p /tmp/ai-agent-todo
```

프로젝트를 생성합니다.

```bash
ai-agent project create examples/todo_api.md \
  --workspace /tmp/ai-agent-todo
```

예시 출력:

```text
Project run: 741a52a7-0ae4-468c-b165-0a0436fe8eb4
Project: Todo API
Status: ready
Current phase: P1
Phases: 3
Workspace: /tmp/ai-agent-todo
```

출력된 Run ID를 이후 명령에서 사용합니다.

---

# CLI Usage

## Project Create

Markdown 요구사항을 읽어 새로운 Project Run을 생성합니다.

```bash
ai-agent project create <plan-file> \
  --workspace <workspace-path>
```

예:

```bash
ai-agent project create examples/todo_api.md \
  --workspace /tmp/ai-agent-todo
```

---

## Project Status

현재 프로젝트 lifecycle 상태를 확인합니다.

```bash
ai-agent project status <RUN_ID>
```

예:

```bash
ai-agent project status \
  741a52a7-0ae4-468c-b165-0a0436fe8eb4
```

예시:

```text
Project: Todo API
Run ID: 741a52a7-0ae4-468c-b165-0a0436fe8eb4
Status: ready
Workspace: /tmp/ai-agent-todo
Current phase: P1

Phases:
[ ] P1 Core API Implementation (attempts=0)
[ ] P2 Automated Tests (attempts=0)
[ ] P3 Documentation (README) (attempts=0)
```

JSON 형식으로 확인할 수도 있습니다.

```bash
ai-agent project status <RUN_ID> --json
```

---

## Execute Phase

현재 Phase를 실행합니다.

```bash
ai-agent project execute <RUN_ID>
```

예시:

```text
Phase: P1 Core API Implementation
Execution status: completed
Requirements: passed:4 failed:0 unknown:0
Repairs: 0
Checkpoint: awaiting_decision
Recommended decisions: approve, request_changes
Workspace: /tmp/ai-agent-todo
```

`execute`는 현재 phase만 실행합니다.

다음 phase로 자동 진행하지 않으며 checkpoint decision이 필요합니다.

---

# Checkpoint Decisions

Phase 실행이 완료되면 프로젝트는 checkpoint에서 사용자 결정을 기다립니다.

## Approve

현재 Phase를 승인하고 다음 Phase로 진행합니다.

```bash
ai-agent project approve <RUN_ID>
```

예:

```text
Project status: ready
Current phase: P2
Workspace: /tmp/ai-agent-todo
```

---

## Retry

현재 Phase를 다시 실행하도록 설정합니다.

```bash
ai-agent project retry <RUN_ID>
```

메모를 함께 전달할 수도 있습니다.

```bash
ai-agent project retry <RUN_ID> \
  --note "Validation failed. Retry implementation."
```

---

## Request Changes

현재 결과에 대한 변경을 요청합니다.

```bash
ai-agent project request-changes <RUN_ID>
```

변경 내용을 전달할 수도 있습니다.

```bash
ai-agent project request-changes <RUN_ID> \
  --note "Add validation for empty todo titles."
```

---

## Stop

프로젝트 실행을 중단합니다.

```bash
ai-agent project stop <RUN_ID>
```

이유를 함께 기록할 수도 있습니다.

```bash
ai-agent project stop <RUN_ID> \
  --note "Project cancelled."
```

---

# Typical Lifecycle

일반적인 프로젝트 실행은 다음 패턴을 반복합니다.

```bash
ai-agent project create plan.md --workspace ./workspace
```

새 Project Run은 즉시 실행되지 않고 `awaiting_plan_approval` 상태가 됩니다.
먼저 생성된 plan을 검토합니다.

```bash
ai-agent project plan <RUN_ID>
```

Phase 구조나 책임을 조정하려면, 기존 requirement와 implementation task를 유지한 채
plan만 반복해서 수정할 수 있습니다.

```bash
ai-agent project revise-plan <RUN_ID> \
  --note "Move automated tests before documentation and clarify phase responsibilities."
```

수정이 끝나면 명시적으로 plan을 승인합니다. 이 명령은 Phase를 실행하지 않습니다.

```bash
ai-agent project approve-plan <RUN_ID>
```

```bash
ai-agent project status <RUN_ID>
```

```bash
ai-agent project execute <RUN_ID>
```

결과를 확인하고:

```bash
ai-agent project approve <RUN_ID>
```

다음 Phase 실행:

```bash
ai-agent project execute <RUN_ID>
```

다시 승인:

```bash
ai-agent project approve <RUN_ID>
```

모든 Phase가 승인될 때까지 이 과정을 반복합니다.

최종적으로:

```bash
ai-agent project status <RUN_ID>
```

에서 프로젝트 완료 상태를 확인합니다.

`revise-plan`은 아직 실행되지 않은 project plan의 phase grouping만 변경합니다.
새 requirement 또는 implementation task가 필요한 요청은 향후 Specification Revision의
범위입니다. 반면 `request-changes`는 이미 실행된 현재 Phase의 checkpoint에서 구현 변경을
요청하는 별도 lifecycle 동작입니다.

## Existing Project Upgrade

기존 코드베이스는 새 프로젝트와 별도로 명시적인 upgrade run으로 시작합니다. 이 명령은
workspace를 분석하고 upgrade specification, implementation plan, phase plan을 만들지만
파일을 수정하거나 phase를 실행하지 않습니다.

```bash
ai-agent project upgrade upgrade.md --workspace ~/projects/todo-api
ai-agent project analysis <RUN_ID>
ai-agent project plan <RUN_ID>
ai-agent project revise-plan <RUN_ID> --note "Separate migration work from API changes."
ai-agent project approve-plan <RUN_ID>
ai-agent project execute <RUN_ID>
```

Upgrade plan revision은 기존 implementation task의 phase 구성만 바꿉니다. 새로운 기능
요구사항을 추가하는 specification revision은 아직 지원하지 않습니다.

---

# Persistent CLI State

CLI는 각 Project Run을 JSON snapshot으로 저장합니다.

기본 저장 위치:

```text
~/.local/share/ai-agent/project-runs
```

각 Run은 UUID를 기준으로 저장됩니다.

예:

```text
~/.local/share/ai-agent/project-runs/
└── 741a52a7-0ae4-468c-b165-0a0436fe8eb4.json
```

저장되는 정보에는 다음과 같은 project lifecycle 정보가 포함됩니다.

* Project Run ID
* Project Specification
* Project Plan
* 현재 Phase
* Phase execution 상태
* Requirement validation 결과
* Checkpoint 상태
* Decision
* Workspace absolute path

따라서 다음처럼 서로 다른 CLI invocation에서도 동일한 프로젝트 상태를 유지할 수 있습니다.

```text
process 1
    │
    └── project create
            │
            ▼
        JSON snapshot

process 종료

process 2
    │
    └── project status
            │
            ▼
        snapshot restore

process 3
    │
    └── project execute
```

snapshot 저장 시 temporary sibling file과 `fsync`, `os.replace()`를 이용하여 whole-snapshot atomic replacement 방식으로 저장합니다.

---

# FastAPI

CLI뿐 아니라 FastAPI 기반 프로젝트 lifecycle API도 제공합니다.

FastAPI에서는 기본적으로 app-scoped `InMemoryProjectRunStore`를 사용합니다.

```text
FastAPI
   │
   ▼
ProjectApplicationService
   │
   ▼
InMemoryProjectRunStore
```

CLI는 동일한 production composition을 재사용하면서 `FileProjectRunStore`를 주입합니다.

```text
CLI
 │
 ▼
ProjectApplicationService
 │
 ▼
FileProjectRunStore
```

이를 통해 business logic은 공유하면서 interface별 storage policy만 다르게 유지합니다.

---

# Agent Components

주요 Agent 구성 요소는 다음과 같습니다.

```text
agent/
├── acceptance.py
├── acceptance_validator.py
├── checkpoint.py
├── coding_service.py
├── phase_execution.py
├── plan.py
├── project.py
├── project_application.py
├── project_execution.py
├── project_file_store.py
├── project_runner.py
├── service.py
├── specification.py
├── specification_parser.py
├── state.py
├── workspace.py
└── workspace_acceptance.py
```

### Specification

사용자의 원본 요구사항을 구조화된 Specification으로 변환합니다.

### Implementation Plan

Specification을 실제 실행 가능한 task와 phase로 변환합니다.

### Agent Service

LLM response를 처리하고 Tool Call을 실행하는 agent loop를 담당합니다.

### Coding Service

workspace를 대상으로 실제 코드 작성 및 수정 작업을 수행합니다.

### Acceptance Validation

구현 결과가 Specification 요구사항을 만족하는지 검증합니다.

### Repair

검증 실패가 발생한 경우 요구사항을 만족시키기 위한 수정 작업을 수행합니다.

### Checkpoint

각 Phase가 종료된 뒤 자동으로 다음 단계로 이동하지 않고 사용자에게 decision을 요청합니다.

### Project Application Service

CLI와 API가 사용하는 프로젝트 lifecycle orchestration 계층입니다.

---

# LLM Layer

OpenAI 기반 provider 구현은 다음 위치에 있습니다.

```text
src/ai_agent_project/llm/
├── base.py
└── providers/
    ├── openai.py
    ├── openai_planner.py
    ├── openai_project_planner.py
    ├── openai_specification.py
    └── structured_schema.py
```

각 단계의 역할을 분리하여 Specification, Planning, Agent execution 등을 독립적으로 구성합니다.

---

# Tools

Agent가 사용할 수 있는 Tool abstraction을 제공합니다.

```text
src/ai_agent_project/tools/
├── base.py
├── calculator.py
├── file.py
├── registry.py
└── shell.py
```

현재 주요 tool:

* File operations
* Shell command execution
* Calculator

Shell command는 command policy를 통해 허용 가능한 명령인지 검사한 후 실행됩니다.

---

# Project Structure

```text
ai-agent-project/
├── examples/
│   └── todo_api.md
│
├── src/
│   └── ai_agent_project/
│       ├── agent/
│       │   ├── acceptance.py
│       │   ├── acceptance_validator.py
│       │   ├── checkpoint.py
│       │   ├── coding_service.py
│       │   ├── phase_execution.py
│       │   ├── plan.py
│       │   ├── project.py
│       │   ├── project_application.py
│       │   ├── project_execution.py
│       │   ├── project_file_store.py
│       │   ├── project_runner.py
│       │   ├── service.py
│       │   ├── specification.py
│       │   ├── specification_parser.py
│       │   ├── state.py
│       │   ├── workspace.py
│       │   └── workspace_acceptance.py
│       │
│       ├── api/
│       │   └── app.py
│       │
│       ├── llm/
│       │   ├── base.py
│       │   └── providers/
│       │
│       ├── tools/
│       │   ├── base.py
│       │   ├── calculator.py
│       │   ├── file.py
│       │   ├── registry.py
│       │   └── shell.py
│       │
│       ├── cli.py
│       ├── command_policy.py
│       └── string_utils.py
│
├── tests/
│   ├── agent/
│   ├── api/
│   ├── integration/
│   ├── llm/
│   └── tools/
│
├── pyproject.toml
└── README.md
```

---

# Testing

전체 테스트:

```bash
uv run pytest
```

상세 출력:

```bash
uv run pytest -vv
```

특정 영역:

```bash
uv run pytest tests/agent
```

```bash
uv run pytest tests/api
```

```bash
uv run pytest tests/integration
```

CLI 테스트:

```bash
uv run pytest tests/test_cli.py
```

File Store 테스트:

```bash
uv run pytest tests/agent/test_project_file_store.py
```

---

# Lint & Format

Ruff 검사:

```bash
uv run ruff check .
```

자동 formatting:

```bash
uv run ruff format .
```

format 상태만 확인:

```bash
uv run ruff format --check .
```

Git whitespace 검사:

```bash
git diff --check
```

---

# End-to-End Acceptance Test

실제 CLI를 이용하여 빈 workspace에서 Todo API 프로젝트를 생성하는 acceptance test를 수행했습니다.

사용한 요구사항:

```text
examples/todo_api.md
```

Workspace:

```text
/tmp/ai-agent-todo
```

실제 lifecycle:

```text
Project Create
      │
      ▼
P1 Core API Implementation
      │
      ├── requirements 4/4 passed
      │
      ▼
Checkpoint
      │
    approve
      │
      ▼
P2 Automated Tests
      │
      ├── requirements passed
      │
      ▼
Checkpoint
      │
    approve
      │
      ▼
P3 Documentation
      │
      ├── README generated
      │
      ▼
Checkpoint
      │
    approve
      │
      ▼
Completed
```

실제 workspace에는 다음과 같은 산출물이 생성되었습니다.

```text
app/
├── __init__.py
├── main.py
├── schemas.py
└── store.py

tests/
├── test_api.py
└── test_todos.py

README.md
```

이를 통해 다음 동작을 실제 CLI 환경에서 확인했습니다.

* Project 생성
* Process 종료 후 state restore
* Phase 실행
* Workspace 코드 생성
* Requirement validation
* Checkpoint 생성
* 사용자 승인
* 다음 Phase 이동
* 테스트 생성
* README 생성
* 전체 Project lifecycle 완료

---

# Current Limitations

현재 버전은 MVP 단계이며 다음과 같은 제한사항이 있습니다.

* CLI persistence는 local JSON file 기반입니다.
* FastAPI Project Run은 기본적으로 memory에 저장됩니다.
* 분산 실행을 위한 database-backed storage는 아직 제공하지 않습니다.
* 여러 agent가 동시에 하나의 workspace를 수정하는 orchestration은 지원하지 않습니다.
* 장기 실행 project를 위한 job queue / worker 구조는 아직 포함되어 있지 않습니다.
* 사람의 checkpoint decision이 필요한 lifecycle을 기본으로 합니다.
* 모델 품질과 실행 결과는 사용하는 LLM 및 프로젝트 요구사항에 영향을 받습니다.

---

# Roadmap

향후 확장 후보:

* SQLite / PostgreSQL 기반 ProjectRunStore
* Async background worker
* Job Queue
* WebSocket / SSE progress streaming
* Web Dashboard
* Project history UI
* Phase execution log
* Token / API cost tracking
* Git branch / commit integration
* Automatic rollback
* Multi-agent orchestration
* Human-in-the-loop approval UI
* Docker sandbox execution
* Remote workspace support
* GitHub repository integration
* CI/CD integration

---

# Development Status

Current version:

```text
0.1.0
```

현재 단계에서는 lifecycle 기반 AI coding agent의 MVP 구현과 CLI end-to-end acceptance validation까지 완료된 상태입니다.

## Phase 6C — Native desktop application

Launch the local PySide6 application:

```bash
uv run ai-agent-desktop
```

The existing `uv run ai-agent ...` CLI remains available. The desktop requires
no browser or FastAPI server. Dashboard and project navigation work without a
provider credential. Use Settings to save an OpenAI-compatible endpoint, model
and timeout. A supplied API key remains in memory for this app session; it is
never saved to the regular JSON settings file. Save Settings retains the runtime
key; Test Connection tests the entered configuration without saving it.

Create a project to request a mode proposal, then explicitly confirm WorkMode
and ProjectMode. For an unbound lane, create its run and explicitly confirm
binding in the resulting dialog, or bind an existing run by ID. If binding is
cancelled, copy the saved run ID to bind it later. Approvals, direction selection,
result submission, continuation, handoff creation and bootstrap remain separate
user actions. Researcher artifacts are never executed by the UI.

The desktop uses the existing local project/run/handoff stores and user provider
configuration. New Developer runs use the launch working directory; continuing
an existing Developer run honors its saved workspace. A running operation must
finish before the window can close. Navigation and Refresh only read state.
Artifacts offer safe JSON preview, copy and no-overwrite JSON export.

Verification and Phase 6D deferrals are documented in
[PHASE_6C_PYSIDE6_DESKTOP_UI.md](PHASE_6C_PYSIDE6_DESKTOP_UI.md).

## Windows distribution

The Windows product is a per-user **AI Agent** installation, launched from the
Start Menu or optional desktop shortcut. End users do not need Python, uv, a
browser or a server. Portable users must keep the entire `AI-Agent` directory
alongside `AI-Agent.exe`; do not distribute the executable by itself.

Builders need Windows 10 (1809+) / Windows 11 x64, uv, and Inno Setup 6 for the
installer. From a checkout on a **local Windows drive** (not a WSL UNC path):

```powershell
powershell -ExecutionPolicy Bypass -File packaging/windows/build.ps1
powershell -ExecutionPolicy Bypass -File packaging/windows/build.ps1 -Installer
```

The script obtains Python 3.12 through uv, syncs locked dependencies into an
isolated build environment, runs packaging tests, and builds/audits the app.
Outputs: `dist/AI-Agent/AI-Agent.exe` and, with `-Installer`,
`dist/installer/AI-Agent-Setup.exe`. Alternatively, run the manual **Windows desktop
distribution** GitHub Actions workflow and download its two artifacts. Development
launch remains `uv run ai-agent-desktop`.

Windows config is `%APPDATA%/ai-agent/llm.json`; projects/research/handoffs are
under `%LOCALAPPDATA%/ai-agent/data`, and the frozen app's default workspace is
`data/workspaces/default`. Linux uses the corresponding XDG config/data/cache
roots, with standard home-directory fallbacks. Installation and ordinary uninstall
leave user config and project data intact.

Enter your compatible endpoint, model, timeout and session API key in Settings.
The endpoint must support the Responses API and the structured outputs used by
this application. Custom endpoints remain authoritative. Keys are not saved in
normal JSON configuration. Generated projects may still need their own external
build/test toolchains; these are not application runtime dependencies.

Development builds are **unsigned**: Windows may display SmartScreen warnings or
organizational application-control policy may block them. Do not disable those
protections. Production releases should use trusted code signing. See
[distribution verification and limitations](PHASE_6D_DESKTOP_DISTRIBUTION.md) for
the exact local versus native Windows acceptance status.
