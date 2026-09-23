<div align="center">

# Human-Governed AI Agent Desktop Platform

### Plan · Approve · Execute · Learn

**개발·리서치 업무를 계획하고, 사용자 승인에 따라 실행하며,  
작업 경험과 피드백을 다음 실행에 반영하는 로컬 AI Agent Desktop Platform**

<br>

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-Application_Service-009688?logo=fastapi&logoColor=white)
![PySide6](https://img.shields.io/badge/Desktop-PySide6-41CD52?logo=qt&logoColor=white)
![Pytest](https://img.shields.io/badge/Test-755_Passed-0A9EDC?logo=pytest&logoColor=white)
![Windows](https://img.shields.io/badge/Windows-x64-0078D4?logo=windows11&logoColor=white)
![Human Governed](https://img.shields.io/badge/AI-Human--Governed-6C63FF)

</div>

---

> [!IMPORTANT]
> **LLM Generated Data ≠ Authoritative State**  
> LLM은 제안(Proposal)을 생성하지만 시스템 상태를 직접 결정하지 않습니다.  
> 상태 변경과 실행 권한은 Validation, Workflow Invariant, Trusted Application, User Approval을 통해 통제됩니다.

---

## Contents

`Overview` · `Core Principle` · `Developer Agent` · `Researcher Agent` · `Hybrid Workflow` · `Self-Improvement` · `Architecture` · `Desktop` · `Security` · `Testing` · `Windows Distribution`

---

## Overview

기존 LLM은 코드와 문서를 생성하는 데 뛰어나지만, 장기간의 실제 프로젝트에서는 단순 대화만으로 다음 문제를 안정적으로 해결하기 어렵습니다.

- 대화 종료 후 작업 상태 유지
- 실패 후 정확한 재개 지점 관리
- 계획과 실제 실행 권한의 분리
- 사용자 승인 기반의 단계별 진행
- Developer / Researcher 간 결과물 연계
- 과거 실패와 피드백의 체계적인 재사용
- Desktop Application 수준의 배포 및 운영

이 프로젝트는 이러한 문제를 해결하기 위해 **LLM의 생성 능력과 애플리케이션의 실행 권한을 분리**하고,  
`Human-in-the-Loop`, `Persistent State`, `Artifact Handoff`, `Human-Governed Self-Improvement`를 중심으로 설계했습니다.

---

## Core Principle

### LLM Generated Data ≠ Authoritative State

이 프로젝트에서 가장 중요한 설계 원칙입니다.

LLM은 시스템 상태를 직접 결정하지 않습니다.

```text
LLM
 │
 │ Structured Proposal
 ▼
Validation
 │
 ▼
Trusted Application
 │
 ▼
Authoritative State
```

LLM이 생성한 응답은 **제안(Proposal)** 으로 취급하고,

1. Schema Validation
2. Workflow Invariant Validation
3. Application Policy
4. User Approval

을 거쳐 Trusted Application이 최종 상태를 확정합니다.

### Human Approval Boundary

```text
PLAN
 ↓
USER APPROVAL
 ↓
EXECUTE ONE PHASE
 ↓
CHECKPOINT
 ↓
USER DECISION
 ↓
CONTINUE
```

중요한 상태 변경과 실행은 명시적인 사용자 결정을 요구합니다.

---

## Main Features

| Developer Agent | Researcher Agent | Hybrid Workflow | Self-Improvement |
|---|---|---|---|
| 계획 → 승인 → 단계별 실행 | 탐색 → 방향 선택 → 계획 → 분석 | Artifact 기반 명시적 Handoff | 후보 → 사람 승인 → Future Context |
| NEW / UPGRADE | 실행 환경 제어 없음 | Exact ID + SHA-256 | Self-Improving, Not Self-Modifying |

### 1. Developer Agent

개발 요청을 분석하고 구현 계획을 생성한 뒤, 사용자 승인에 따라 한 단계씩 작업을 진행합니다.

```text
Development Request
        ↓
Requirement Analysis
        ↓
Implementation Plan
        ↓
USER APPROVAL
        ↓
Execute Current Phase
        ↓
Validation
        ↓
Checkpoint
        ↓
USER DECISION
        ↓
Next Phase
```

#### NEW Mode

새로운 프로젝트에 대해 요구사항 분석부터 구현 계획과 단계별 개발까지 진행합니다.

#### UPGRADE Mode

기존 프로젝트를 대상으로 다음 순서를 강제합니다.

```text
ANALYZE → PLAN → USER APPROVAL → MODIFY
```

#### Developer Features

- Plan Revision
- Persistent Project State
- Phase Checkpoint
- Explicit User Approval
- Workspace Safety
- Validation
- Rollback-oriented workflow
- Upgrade Analysis

---

### 2. Researcher Agent

Researcher Agent는 연구를 대신 실행하는 Agent가 아니라,  
**연구 탐색·방향 결정 지원·연구 계획·결과 분석을 담당하는 Agent**입니다.

```text
Research Request
      ↓
Preliminary Research
      ↓
Related Work / Landscape
      ↓
Direction Candidates
      ↓
USER SELECTS DIRECTION
      ↓
Research Plan
      ↓
USER APPROVAL
      ↓
Code / Experiment Scaffold
      ↓
USER EXECUTES EXPERIMENT
      ↓
Result Intake
      ↓
Result Analysis
      ↓
Research Synthesis
      ↓
Paper Materials
```

#### Researcher Agent가 하지 않는 것

- Shell Command 실행
- Experiment 자동 실행
- Model Training
- 사용자 Server / Environment 제어
- 연구 방향 자동 확정

#### Researcher Agent가 담당하는 것

- Research Discovery
- Related Work / Landscape 정리
- Research Direction Candidate 생성
- Research Planning
- Code / Configuration / Scaffold 생성
- User-Supplied Result Intake
- Result Analysis
- Research Synthesis
- Paper Material Preparation

> 연구 방향은 Agent가 결정하지 않고 반드시 사용자가 선택합니다.

---

### 3. Hybrid Workflow

Developer와 Researcher를 하나의 거대한 workflow로 합치지 않습니다.

두 Agent는 **독립적인 권한과 상태를 유지**하고, 사용자가 선택한 Research Artifact만 명시적으로 Developer Context로 전달합니다.

```text
RESEARCHER
    │
    │ Selected Artifact
    ▼
┌─────────────────────────┐
│ Explicit Artifact       │
│ Handoff                 │
│                         │
│ artifact_id             │
│ source_run_id           │
│ content_sha256          │
│ purpose                 │
└────────────┬────────────┘
             │
             ▼
        DEVELOPER
```

Handoff는 다음 정보를 기반으로 무결성을 확인합니다.

- `artifact_id`
- `source_run_id`
- `content_sha256`
- `purpose`

> **Agent Collaboration ≠ Shared Authority**

Agent는 정보를 공유할 수 있지만 서로의 workflow 권한을 대신 행사하지 않습니다.

---

### 4. Human-Governed Self-Improvement

이 프로젝트의 Self-Improvement는 Agent가 자신의 소스코드를 자동 수정하는 방식이 아닙니다.

```text
Agent Run
    ↓
Result / Error / Feedback
    ↓
Evaluation
    ↓
Improvement Candidate
    ↓
HUMAN APPROVAL
    ↓
Approved Rule
    ↓
Future Agent Context
    ↓
Next Run
```

과거 작업의 결과와 사용자 피드백에서 개선 후보를 생성하고,  
**사용자가 승인한 Improvement만 이후 Agent Context에 제한적으로 반영**합니다.

#### Safety Boundary

다음 동작은 허용하지 않습니다.

- Self Source Modification
- Automatic Approval
- Automatic Fine-Tuning
- Automatic Experiment Execution
- Credential Exposure
- Researcher Code Execution
- Autonomous Workflow Progression

> **Self-Improving, Not Self-Modifying**

---

## Architecture

```text
┌──────────────────────────────────────────────────────┐
│                  PySide6 Desktop UI                  │
│                                                      │
│ Dashboard · Projects · Developer · Researcher        │
│ Hybrid · Artifacts · Improvements · Settings         │
└─────────────────────────┬────────────────────────────┘
                          │
                   Desktop Facade
                          │
                  Project Orchestrator
                          │
             ┌────────────┼────────────┐
             ▼            ▼            ▼
       Developer       Researcher    Hybrid
         Agent            Agent      Handoff
             │            │
             └──────┬─────┘
                    ▼
             LLM Provider Layer
           OpenAI-Compatible API

          ┌────────────────────┐
          │ Persistence Store  │
          └────────────────────┘

          ┌────────────────────┐
          │  Artifact System   │
          └────────────────────┘

                    ▲
                    │
       Human-Governed Improvement
```

### Architecture Characteristics

- UI / Domain Layer Separation
- Application Service 중심의 workflow 관리
- OpenAI-Compatible Provider Abstraction
- Persistent Project / Research State
- Explicit Human Checkpoint
- Artifact-based Agent Collaboration
- Desktop / CLI / API 인터페이스 분리
- Local-first data management

---

## Desktop Application

PySide6 기반의 Desktop Application을 제공합니다.

### Pages

- Dashboard
- Projects
- Developer
- Researcher
- Hybrid
- Artifacts
- Improvements
- Settings

Desktop UI는 Agent Domain Logic을 직접 구현하지 않고, Desktop Facade / Application Service를 통해 기존 authoritative workflow를 사용합니다.

---

## LLM Provider Configuration

OpenAI-Compatible API Provider를 지원합니다.

사용자는 다음 설정을 지정할 수 있습니다.

- Base URL
- Model
- API Key
- Timeout

### Configuration Policy

Credential과 일반 configuration을 분리합니다.

일반 설정은 사용자 configuration directory에 저장하며, API Key는 일반 JSON 설정에 평문으로 저장하지 않는 방향으로 설계했습니다.

Provider configuration precedence:

```text
Runtime Configuration
        ↓
Saved Configuration
        ↓
Environment Variable
        ↓
Default
```

---

## Artifact System

Developer / Researcher workflow에서 생성된 결과는 Artifact로 관리됩니다.

### Examples

#### Developer

- Specification
- Project Specification
- Implementation Plan
- Plan Revision
- Execution State
- Upgrade Context

#### Researcher

- Research Request
- Discovery Report
- Selected Direction
- Research Plan
- Implementation Plan
- Generated File
- Research Results
- Result Analysis
- Research Synthesis
- Paper Materials

Artifact 조회와 export는 workflow execution과 분리되며, read-only 작업이 hidden state mutation을 일으키지 않도록 설계했습니다.

---

## Security & Safety

Final Product Audit에서 기능뿐 아니라 권한 경계와 filesystem safety를 검증했습니다.

주요 보호 항목:

- Approval Bypass 방지
- `.env` / Secret Protection
- Symlink 기반 workspace escape 차단
- Shell option-like path 검증
- Artifact export path validation
- Agent internal transcript 노출 방지
- Researcher execution boundary
- Self-modification 방지
- Credential 노출 방지

---

## Tech Stack

| Category | Technology |
|---|---|
| Language | Python 3.12 |
| LLM | OpenAI-Compatible API |
| Validation | Pydantic |
| API | FastAPI |
| Desktop | PySide6 / Qt |
| Testing | Pytest |
| Lint / Format | Ruff |
| Packaging | PyInstaller |
| Windows Installer | Inno Setup |
| CI/CD | GitHub Actions |

---

## Project Structure

```text
ai-agent-project/
├── src/
│   └── ai_agent_project/
│       ├── agent/
│       │   ├── developer/
│       │   ├── researcher/
│       │   ├── project orchestration
│       │   ├── artifact
│       │   └── handoff
│       │
│       ├── desktop/
│       ├── improvement/
│       ├── llm/
│       ├── api/
│       └── cli.py
│
├── tests/
│   ├── agent/
│   ├── integration/
│   ├── desktop/
│   ├── improvement/
│   └── packaging/
│
├── packaging/
├── .github/
│   └── workflows/
└── pyproject.toml
```

> 실제 repository의 세부 구조는 개발 과정에서 변경될 수 있습니다.

---

## Development Setup

### Requirements

- Python 3.12+
- `uv`

### Install

```bash
git clone https://github.com/whrjsdnr/ai-agent-project.git
cd ai-agent-project

uv sync
```

### Run CLI

```bash
uv run ai-agent --help
```

### Run Desktop

```bash
uv run ai-agent-desktop
```

### Run API

FastAPI application은 프로젝트의 API entrypoint를 통해 실행할 수 있습니다.

```bash
uv run uvicorn ai_agent_project.api.app:app --reload
```

---

## Testing

### Full Test Suite

```bash
uv run pytest
```

Final Product Audit 기준:

```text
Full Test Suite       755 passed / 12 skipped
Broad Regression      547 passed / 12 skipped

Final Acceptance       22 passed
Self-Improvement       64 passed
Desktop GUI            20 passed
Desktop Facade         23 passed
Packaging              25 passed

Ruff                   PASS
Formatting             PASS
Linux Frozen Build     PASS
Windows CI Build       PASS
Windows Application    PASS
```

### Lint

```bash
uv run ruff check .
```

### Format Check

```bash
uv run ruff format --check .
```

---

## Windows Distribution

Desktop Application은 PyInstaller one-directory 방식으로 패키징합니다.

```text
Source
  ↓
PyInstaller
  ↓
Windows x64 Application
  ↓
GitHub Actions
  ↓
Inno Setup
  ↓
Windows Installer
```

실제 Windows CI 결과물:

```text
AI-Agent-Windows-x64/
└── AI-Agent.exe

AI-Agent-Installer/
└── AI-Agent-Setup.exe
```

Windows GitHub Actions에서 다음 검증을 완료했습니다.

- Windows x64 Build
- PE Executable Verification
- Frozen GUI Acceptance
- Inno Setup Installer Build
- Artifact Upload

실제 Windows 환경에서 application 실행도 확인했습니다.

---

## Data Paths

Windows 배포 기준:

```text
Configuration
%APPDATA%\ai-agent\llm.json

Application Data
%LOCALAPPDATA%\ai-agent\data

Cache
%LOCALAPPDATA%\ai-agent\cache
```

사용자 데이터는 application binary와 분리하여 관리합니다.

---

## Design Decisions

### Why not fully autonomous?

이 프로젝트의 목표는 가능한 많은 작업을 자동화하는 것이 아니라,  
**잘못된 Agent 판단이 실제 시스템 변경으로 직결되지 않는 구조를 만드는 것**입니다.

따라서 다음 원칙을 사용합니다.

```text
LLM proposes
User approves
Application validates
System executes
```

### Why separate Developer and Researcher?

개발과 연구는 서로 다른 안전 경계가 필요합니다.

- Developer는 승인된 계획에 따라 workspace를 수정할 수 있음
- Researcher는 연구를 설계하고 결과를 분석하지만 실행 environment를 직접 제어하지 않음

두 workflow를 분리함으로써 역할과 권한을 명확하게 유지합니다.

### Why artifact-based handoff?

전체 Agent state를 공유하면 불필요한 내부 정보와 과거 context가 함께 전달될 수 있습니다.

따라서 명시적으로 선택된 Artifact만 exact ID + digest 기반으로 전달합니다.

---

## Final Outcome

### What this project demonstrates

**Agent Architecture** · **Human-in-the-Loop** · **Persistent Workflow** · **Security Boundary** · **Desktop Engineering** · **Automated Testing** · **Windows Distribution**

이 프로젝트를 통해 단순한 Chat / Prompt Wrapper가 아니라 다음 요소를 포함한 AI Agent Platform을 구현했습니다.

- Persistent Workflow State
- Developer Agent
- Researcher Agent
- Hybrid Agent Coordination
- Human Approval Checkpoints
- Artifact Management
- Explicit Cross-Agent Handoff
- Human-Governed Self-Improvement
- Desktop Application
- Windows Packaging / Installer
- Automated Test / Release Pipeline
- Final Security & Product Audit

> **LLM의 생성 능력은 활용하되, 상태·권한·승인은 애플리케이션과 사용자가 통제한다.**

---

## Status

```text
Application Architecture        ✅
Developer Agent                 ✅
Researcher Agent                ✅
Hybrid Workflow                 ✅
Artifact System                 ✅
Human-Governed Self-Improvement ✅
PySide6 Desktop                 ✅
Windows Packaging               ✅
Windows Installer               ✅
Windows CI                      ✅
Windows Application Execution   ✅
```

---

## License

This project is currently maintained as a personal portfolio project.

