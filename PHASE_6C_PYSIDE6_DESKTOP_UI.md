# Phase 6C — PySide6 Desktop UI

Native local desktop UI implemented. No commit or push was performed.

## Delivery

| Area | Implementation |
| --- | --- |
| Dependency | `pyside6>=6.11.2` application dependency added with `uv`; `uv.lock` includes Essentials, Addons and Shiboken. |
| Launch | `uv run ai-agent-desktop`, console script `ai_agent_project.desktop_app.main:main`. Existing CLI entry points retained. |
| Window | `QMainWindow`, controlled 180px sidebar, top provider status, stacked scrollable pages, status/progress bar, centralized light stylesheet. |
| Pages | Dashboard metric cards/recent projects; Projects table; Project Detail; Developer; Researcher; independent Hybrid lanes and handoffs; Artifacts; Settings. |
| Dialogs | New project request; explicit mode confirmation; direction selection with no default choice; multiline research results; run-ID binding; created-run explicit binding; Developer-from-research request. |
| Controller state | Only selected project ID and current page. No mutable workflow snapshots or authoritative lane state in GUI state. |
| Worker | One explicitly supplied callable in a `QRunnable`/`QThreadPool`; success/error signals return to GUI-thread slots. A busy window blocks duplicate operations, navigation and close until completion. No autonomous looping or phase chaining. |
| Composition | Shared production factories extracted to server-independent `composition.py`, retained as API imports and reused by CLI. Desktop builds file stores, provider settings, sessions, actions, artifacts, handoffs, coordination and bootstrap once; production providers are constructed lazily per explicit operation. |
| Facade | Uses the existing Phase 6B `DesktopService` (the repository's desktop application facade). Added immutable Researcher presentation fields, bootstrap availability, safe export/handoff availability and explicit create-run commands. |
| Settings | Endpoint/model/timeout persisted through Phase 6A. Connection result sanitized by Phase 6A/6B. Test uses form values without saving. Save retains a supplied key for the current application instance. |
| Credentials | Password echo mode; never populate the field from stored/runtime credentials; field cleared on submission/refresh. Runtime key is a `SecretStr`, excluded from JSON and repr/str. No environment-variable mutation, key logging or plaintext credential storage. |
| Hybrid | Both lanes render their own authoritative pending action. Approving Developer does not progress Researcher; Researcher selection does not require Developer approval. Handoff creation and bootstrap are distinct user requests; bootstrap leaves the Developer plan approval checkpoint intact. |
| Artifacts | Ownership-checked facade list/preview; JSON shown as plain text, safe metadata and clipboard copy. Export delegates to existing atomic no-overwrite/no-symlink export service; GUI never writes artifact files directly or executes their contents. |
| Persistence | Existing file stores remain authoritative across full service/window reconstruction. UI refresh/navigation do not update workflow records. |
| Shutdown | A busy operation must finish; thread pool is joined on normal close. Each desktop provider-call scope closes its lazy clients on success/error. Closing does not mutate workflows. |

## Changes

Added:

- `src/ai_agent_project/composition.py`
- `src/ai_agent_project/desktop_app/__init__.py`
- `src/ai_agent_project/desktop_app/main.py`
- `src/ai_agent_project/desktop_app/application.py`
- `src/ai_agent_project/desktop_app/window.py`
- `src/ai_agent_project/desktop_app/pages.py`
- `src/ai_agent_project/desktop_app/dialogs.py`
- `src/ai_agent_project/desktop_app/widgets.py`
- `src/ai_agent_project/desktop_app/worker.py`
- `src/ai_agent_project/desktop_app/theme.py`
- `tests/desktop_app/conftest.py`
- `tests/desktop_app/test_desktop_app.py`
- This report.

Modified:

- `pyproject.toml`, `uv.lock`: dependency and desktop script.
- `src/ai_agent_project/api/app.py`: imports shared production factories; HTTP routes retained.
- `src/ai_agent_project/cli.py`: imports shared factories without importing the API module.
- `src/ai_agent_project/desktop/models.py`: immutable direction, result/version and handoff presentation metadata.
- `src/ai_agent_project/desktop/service.py`: read projections and explicit service delegation for GUI gaps.
- `src/ai_agent_project/desktop/errors.py`: safe normalization for artifact-export failures.
- `src/ai_agent_project/llm/runtime.py`: scoped client cleanup for explicitly requested desktop operations.
- `README.md`: desktop launch and usage.

## Proof of workflow isolation

Widgets call the facade, never stores. Action routing maps named buttons to named
facade methods. Direction/results dialogs collect inputs only. New project
creation stores a proposal without confirming it. Run creation does not bind;
the subsequent binding dialog requires another user confirmation. There is no
`Next`, polling timer, scheduler, subprocess, terminal, generated-code execution,
auto-approval or workflow executor in the desktop modules. Existing Developer
execution tools are reused solely through existing application services.

The acceptance test seeds real persisted Developer, Researcher and Hybrid
projects and artifacts. It verifies all project views, artifact content and
credential-free settings, then compares file bytes and timestamps after repeated
navigation/refresh. Clicking Developer approval changes exactly one persisted
run file, leaves the Researcher run unchanged, and survives full service/window
reconstruction. Additional real-store tests cover result intake without
analysis, explicit handoff creation, and separate authoritative bootstrap.

Acceptance marker: `PHASE_6C_PYSIDE6_DESKTOP_UI=PASSED`.

## Verification

- Offscreen GUI suite: **20 passed**. No real provider calls.
- Existing regression: **570 passed, 12 skipped** (opt-in live-provider tests).
- `uv run ai-agent --help`: passed.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed.
- `git diff --check`: passed.
- The sandbox stalls the existing Starlette/AnyIO TestClient thread handoff;
  the same regression suite completes outside the sandbox. No tests were weakened.

Commands:

```bash
QT_QPA_PLATFORM=offscreen uv run pytest tests/desktop_app -q -p no:cacheprovider
uv run pytest tests/desktop tests/agent tests/llm tests/integration tests/api tests/test_cli.py -q -p no:cacheprovider
uv run ruff check .
uv run ruff format --check .
git diff --check
```

The GUI tests collectively cover all 30 requested behaviors: server-independent
composition/import, window creation, navigation, seeded Dashboard/project list,
selection/no-project views, both lanes and Hybrid, authoritative action labels,
no auto-next, explicit direction and result intake, one Developer approval,
separate handoff/bootstrap, safe artifacts/export, password/credential safety,
sanitation, read-only refresh/navigation, one-call worker and GUI-thread delivery,
no research execution, CLI-compatible composition and reconstructed persistence.

## Native / visual smoke test

`uv run ai-agent-desktop` launched on the configured native display and exited
normally with code 0. A separate temporary native Qt smoke driver clicked
Dashboard, Projects and Settings through the sidebar and closed normally, using
isolated storage and no provider calls. All four checks passed. Native Settings
and offscreen seeded 1366×768 Dashboard/Hybrid screenshots were visually reviewed.
This is native automated clicking plus visual inspection, not a claimed human
mouse/keyboard walkthrough; user feedback was requested separately.

## Security and hygiene

`.env` is ignored and untracked; its contents were not read. No credential is
written to regular configuration, rendered from saved state, logged, or included
in config repr/str. No raw provider error body or transcript is displayed. Export
retains backend ownership, symlink and no-overwrite checks. No new shell commands,
subprocess use, arbitrary execution, personal absolute paths, or temporary debug
code were added to the product. Smoke drivers/screenshots were kept outside the
repository. No credentials or workflow snapshots are written to QSettings.

## Limitations / Phase 6D

- Installer/executable packaging, OS credential storage, window preference
  persistence and richer run-history selection remain deferred.
- A cancelled binding leaves its newly created run saved; retain its displayed
  run ID for explicit later binding. There is no unbound-run browser yet.
- Workspace selection uses the launch working directory for new Developer runs;
  existing runs retain their saved workspace. A workspace-picker UX is deferred.
- Preview/export initially uses JSON/plain text; a rich Markdown viewer/editor
  and additional export format controls are deferred.
- Results entry records multiline user observations with authoritative plan
  versions; richer structured measurement forms remain deferred.
- Operations are serialized per window and cannot be cancelled halfway through
  an authoritative service call. There is no background engine or autonomous
  progression. No real-provider connection was made during verification.
- Multi-user/distributed services, execution of Researcher artifacts, packaging,
  schedulers and the other stated non-goals remain outside this phase.

Git status at delivery: only the added/modified paths listed above; no staged
changes, commit or push.
