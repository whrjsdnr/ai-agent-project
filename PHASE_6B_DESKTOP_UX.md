# Phase 6B desktop application boundary

`ai_agent_project.desktop.DesktopService` is a synchronous local facade. Construct
it with the existing session, action, artifact, handoff, Hybrid coordination,
provider configuration services, and the same Developer/Researcher readers used
by those services. Optionally inject the existing Developer bootstrap service.
No HTTP server, FastAPI import, Qt dependency or workflow runner is introduced.

```python
view = desktop_service.get_project_view(project_id)
# After a user explicitly approves the displayed Developer plan:
desktop_service.approve_developer_plan(project_id)
view = desktop_service.get_project_view(project_id)
```

## Views and delegation

| Desktop API | Authoritative dependency |
| --- | --- |
| `list_projects()` | `ProjectSessionService.list_projects()` and `get_pending_actions()` |
| `get_dashboard()` | Project summaries and Phase 6A configuration resolution |
| `get_project_view(project_id)` | Session/get_pending_actions, run readers, `HybridCoordinationService.get_coordination()`, artifact and handoff services |
| `list_project_artifacts(project_id)` | `ProjectArtifactService.list_artifacts()` |
| `get_artifact_view(project_id, artifact_id, artifact_format)` | `ProjectArtifactService.get_artifact()` ownership checks and `render_project_artifact()` |
| `list_handoffs(project_id)` | `ProjectHandoffService.list_handoffs()` derived reference status |
| `get_provider_config()` | `ProviderConfigService.resolve()` |
| `save_provider_config(config)` | `ProviderConfigService.save()` |
| `test_provider_connection(config=None)` | `ProviderConfigService.test_connection()`; explicitly permits a provider call |
| `create_project(request, title=None)` | `ProjectSessionService.create_project_request()`; proposal only, returns project ID |
| `confirm_project_mode()`, `bind_developer_run()`, `bind_research_run()`, `complete_project()` | Same named `ProjectSessionService` methods |
| `approve_developer_plan()`, `continue_developer()`, `select_research_direction()`, `approve_research_plan()`, `provide_research_results()`, `continue_researcher()` | Same named `ProjectActionService` methods with existing command models |
| `create_handoff()` | `ProjectHandoffService.create()`; returns handoff ID |
| `bootstrap_developer_from_handoff()` | `ProjectDeveloperBootstrapService.bootstrap()`; returns Developer run ID |

Actions returning no ID return `None`; refresh separately after success. There is
no implicit refresh after mutation, so an unrelated read failure cannot obscure
whether the explicit command succeeded. Bootstrap retains its existing bounded
planning/binding behavior; it is not a single filesystem write.

All presentation models are frozen Pydantic models containing scalar values,
other desktop models and tuples. Artifact bodies are rendered strings, never
mutable domain objects. Models include `DesktopProjectSummary`,
`DesktopProjectView`, `DesktopLaneView`, `DesktopPendingActionView`,
`DesktopArtifactSummary`, `DesktopArtifactView`, `DesktopHandoffSummary`,
`DesktopHybridView`, `DesktopProviderView`, `DesktopConnectionView`, and
`DesktopDashboardView`.

Project lists sort by `(created_at, project_id)` descending, including stable ties.
Dashboard recent projects are the first ten; awaiting-user count counts projects
with at least one pending action, not the number of individual lane actions.
Pending-action tuples are explicitly empty when absent; each lane's absent action
is `None`. `available_actions` is resolver guidance, not authorization or a promise
that every continuation status is executable. The authoritative action service
rejects unsupported bounded continuations. Both Hybrid lanes remain independently
addressable. No desktop transition rules are added.

## Refresh and data safety

Reads call only snapshot getters, the existing pure resolvers/renderers, and
configuration resolution. They do not prepare result submissions, create IDs,
write files, change timestamps, bind runs or call providers. The acceptance test
compares file bytes and modification times across repeated refreshes of Developer,
Researcher and Hybrid projects. It then selects a Hybrid research direction while
Developer approval is pending and proves only that Researcher snapshot changed.

Artifact content is limited to the Phase 4 catalog and its rendering rules. The
facade does not expose entire runs, workspace roots, private transcripts or tool
call envelopes, and does not read arbitrary artifact paths. Existing authored
artifact text is preserved, not redacted or reinterpreted. Phase 6C should display
rendered strings as text; generated artifacts must never execute on inspection.

Provider configuration is separate from workflow storage. The safe view contains
only provider type, base URL, model, timeout and a boolean credential indicator.
Phase 6A saves non-secret settings; API keys remain runtime/environment inputs and
are not persisted by `save_provider_config`. UI callers can pass the existing
`ProviderConfig` and `ResearchResultSubmission` validated input models.

Expected application/provider exceptions become `DesktopError` with a stable
`DesktopErrorCode` and fixed actionable message. Arbitrary exception text is never
copied into the user-facing error. Unknown programming errors propagate for
application-level diagnostics. Phase 6C should show `code`/`message`, not exception
tracebacks or internal exception context.

## Deferred work

Phase 6C owns widgets, event handling, rendering, input forms, and service composition
at launch. This phase adds no workers, scheduling, automatic approvals, automatic
continuation or Researcher execution. Reads are deterministic for unchanged local
snapshots; they are not a transaction spanning concurrent external writers.
Custom session stores need the new read-only `list_projects()` capability to use
the dashboard. Existing CLI/API operations retain their interfaces.

Run the provider-free acceptance and focused tests with:

```sh
uv run pytest tests/desktop -q -p no:cacheprovider
```

Acceptance marker: `PHASE_6B_DESKTOP_UX_LAYER=PASSED`.

## Verification results

- Desktop: `uv run pytest tests/desktop -q -p no:cacheprovider` — **23 passed in 1.46s**.
- Regression: `uv run pytest tests/agent tests/llm tests/integration tests/api tests/test_cli.py -q -p no:cacheprovider` — **547 passed, 12 skipped in 5.10s**.
- `uv run ruff check .` — **All checks passed**.
- `uv run ruff format --check .` — **170 files already formatted**.
- `git diff --check` — clean.

The initial sandboxed regression run stalled inside the existing TestClient/AnyIO
thread bridge. It and the diagnostic reproduction were interrupted; the same
regression suite passed outside the sandbox. No compatibility workaround or
unrelated dependency change was added.

`.env` remains ignored and untracked; its contents were not read. Credential-pattern
scanning of tracked/new non-environment source files found no key-like credentials.
Tests use generated dummy credential values and verify their absence from provider
views, settings JSON, repr/str and normalized error messages. Desktop source scans
found no subprocess/shell execution, FastAPI/Qt dependency or personal absolute
paths. No commit or push was performed.
