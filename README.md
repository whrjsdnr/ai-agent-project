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
echo $OPENAI_API_KEY
```

보안을 위해 API Key를 코드나 Git 저장소에 직접 저장하지 않는 것을 권장합니다.

예를 들어 `.env`를 사용하는 경우 `.gitignore`에 다음 항목을 추가합니다.

```gitignore
.env
```

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
