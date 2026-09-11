# FINAL_PRODUCT_AUDIT

Audit date: 2026-09-11. Baseline: `main`, `5c3506d1523ff437cd246a3f1e6a0a93f771bb66` (`feat: add human-governed self-improvement`). The audit began with a clean committed worktree. Final results cover that baseline **plus the explicitly listed, unstaged audit fixes**, not unchanged HEAD alone.

## Executive release assessment

**APPLICATION_RELEASE_READY**

**WINDOWS_DISTRIBUTION_VERIFICATION_PENDING**

Five release-blocking defects were reproduced and fixed: missing desktop Developer checkpoint decisions, environment-file access through aliases/variants, option injection through command-path arguments, direct shell-command path escape through symlinks, and nested private agent transcripts in execution artifacts. No P0/P1 application finding remains open after verification. The complete provider-free test suite passes: **755 passed, 12 skipped**. Linux frozen startup and bundle inspection pass. No native Windows executable or installer was built or verified during this audit; this is not a fully verified public Windows release.

The Windows manual workflow is committed locally and present on remote `main`, but GitHub's default branch is `master`, which lacks it. That operational mismatch must be resolved before manual CI dispatch. Nothing was committed, pushed, installed on Windows, published, or changed in GitHub settings by this audit.

## Architecture and phase completion matrix

The product remains a single-user local native PySide6 application. Desktop widgets call the desktop facade, which delegates to authoritative application services. Domain runs, ProjectSession bindings, handoffs, provider settings and improvements have separate persistence responsibilities. CLI/API are supported secondary surfaces; desktop does not depend on an HTTP server.

| Feature | Independent evidence / assessment |
| --- | --- |
| Developer NEW | Full facade/GUI journey from mode proposal through run creation, binding, approval, phase execution, checkpoint decision, completion and disk reconstruction |
| Developer UPGRADE | Existing upgrade/application/provider regression verifies analyze → plan → approval before modification; no model-backed mutation during bootstrap |
| Researcher | Full explicit lifecycle to paper materials with process execution forbidden by test instrumentation |
| Project orchestration | Separate WorkMode/ProjectMode, explicit confirmation/binding, derived pending actions, explicit project completion |
| Hybrid / Phase 5 | Independent lanes, exact handoff/provenance, bootstrap at plan approval, concurrent winner/rollback regression |
| Phase 6A provider | Central construction, precedence, custom endpoint and credential handling regression |
| Phase 6B facade | 23 dedicated tests; repeated read/refresh invariants also exercised across product journeys |
| Phase 6C desktop | 20 dedicated offscreen tests, final checkpoint GUI journey, native source startup/navigation/close smoke |
| Phase 6D distribution | 25 packaging tests; current Linux frozen bundle rebuilt and verified; native Windows verification pending |
| Phase 7 improvement | 64 dedicated tests plus final production-provider injection, unrelated-project exclusion and restart journeys |

## Critical authority invariants

`LLM-generated data != authoritative application state` remains intact at the inspected boundaries. Provider proposals are parsed/validated; trusted services own run/project/handoff/improvement identity, binding, approval, provenance and state transitions. Model-proposed content identifiers such as research direction/task references are validated within their structured content; they do not authorize application transitions.

WorkMode (`developer`, `researcher`, `hybrid`) remains separate from ProjectMode (`new`, `upgrade`). Mode proposal creates no domain run and is not confirmation. ProjectSession stores run references rather than copied run state. Pending actions are derived deterministically from authoritative snapshots. No LLM chooses or executes the authoritative pending action.

No approval, direction selection, result submission, handoff consumption, improvement approval, background evaluation, or next-phase progression is automatically chained. A documented operation can contain bounded internal work, including Developer repair attempts, but cannot approve or launch a later workflow phase itself.

## Developer acceptance and checkpoint fix

The pre-audit GUI displayed Continue Developer after phase execution, but its facade had no way to submit the existing domain checkpoint decision. Continued execution then failed because the run awaited a decision. This broke the primary desktop completion journey.

The fix adds a typed `DecideDeveloperCheckpointCommand` and a thin project-action route to the existing `ProjectApplicationService.decide_current_phase`. The desktop facade delegates to it. The GUI displays **Review Developer checkpoint**, opens a dialog with no decision selected, and requires an explicit approve/request-changes/retry/stop selection before submission. The existing Qt worker performs the request. The authoritative checkpoint service still validates eligibility and performs the transition; no workflow state machine was duplicated or rewritten.

Final acceptance proves:

- Creating/binding the run does not approve it or modify its workspace.
- Execution before plan approval fails.
- One explicit continuation executes one phase and stops at `awaiting_checkpoint`.
- The dialog has no preselected decision and cannot submit without a choice.
- An explicit checkpoint approval completes the one-phase fixture without another execution.
- Explicit project completion and service reconstruction preserve the result.

Existing multi-phase, retry, failed-validation, checkpoint and upgrade regression tests pass. CLI/API domain checkpoint operations remain available unchanged. Developer projects still require the external tools their validation plans use; the packaged GUI itself requires neither Python nor uv on the end-user machine. A tool allowlist is not an OS sandbox for arbitrary project test code.

## Researcher acceptance and authorship boundary

The final Researcher journey uses real application services, stores and facade routing with deterministic discovery/generation boundaries. It explicitly selects a direction, generates a plan, approves the plan, generates implementation artifacts, submits an external observation, analyzes, synthesizes, and produces paper materials. Submission leaves analysis pending until the next explicit request.

Process launch is instrumented to fail during this journey; no launch occurs and the workspace remains empty until the user's explicit artifact export. The Researcher application has no shell/code/experiment execution method. Provider inputs and output validation do not grant execution authority. Generated files remain persisted inert content. The final output remains structured paper/research materials, not autonomous manuscript authorship. Dedicated no-execution and closed-reference/support-escalation tests pass.

## Hybrid, artifacts and handoffs

The final Hybrid journey creates HYBRID + NEW, binds Researcher, explicitly produces a supported research-plan artifact, registers its handoff, then separately bootstraps Developer. The new Developer run records handoff provenance and stops at plan approval. Bootstrap does not change Researcher. Subsequent Researcher actions leave Developer unchanged; explicit Developer approval leaves Researcher unchanged.

Artifact lookup checks exact project/run ownership and trusted catalog identity. Generated Researcher content is retrieved from persisted snapshots. The audit additionally reproduced private primary/repair agent conversations in execution artifacts. The shared catalog projection now excludes these AgentState objects for all artifact consumers without rewriting historical runs; a preview/export test verifies this boundary and unchanged source persistence. Catalog projections exclude private tool conversations; Developer live workspace files are not advertised as immutable historical generated files. JSON/Markdown/text rendering remains deterministic within supported formats. Desktop export is explicit, no-overwrite and symlink-safe; the API does not accept arbitrary server filesystem export destinations.

Handoff consumption checks project ownership, active Hybrid state, current Researcher binding, supported artifact type, exact artifact/run identity and canonical-content digest. No latest fallback exists. Final acceptance tests digest tampering and source rebinding; neither creates a Developer run or mutates workflows. The existing concurrent bootstrap test runs with both memory and file-backed project stores and proves one winner, one binding, rollback of the losing run, unchanged workspace and plan approval still pending. Local locking is sufficient; no distributed infrastructure was added.

## Provider configuration, credentials and error handling

Inspection found one production `OpenAI(...)` construction site, in `llm/runtime.py`. Configuration remains explicit runtime > saved non-secret fields > environment > defaults. Runtime/environment credentials are handled separately and never loaded from saved JSON. Custom URLs remain authoritative; provider-specific fallback was not introduced. The current Responses API/structured-output compatibility requirement remains a distribution prerequisite.

Config serialization, repr/str, desktop display, connection errors and improvement evaluation errors are covered by deterministic credential tests. Fresh-start acceptance saves a synthetic session key, verifies it is absent from `llm.json`, reconstructs services and verifies the credential is gone while model settings remain. No real `.env` content or credential value was read or printed during audit.

Missing keys, invalid URLs/timeouts, malformed provider responses, missing project/run/artifact, stale handoffs, digest mismatch, invalid candidate and export failures are exercised by the existing suites. Final acceptance specifically checks provider failure before run creation, rejected export overwrite, and invalid handoff consumption without unintended mutation. Evaluator failure is atomic with respect to evaluation/candidate persistence. Startup errors and worker errors use safe user messages; startup diagnostic text is fixed rather than a raw exception dump.

## Self-Improvement

The loop remains explicit evidence collection → evaluation → pending candidate → user approval → enabled rule → bounded future guidance. Trusted code supplies identity/provenance/approval. Rejection creates no rule; enable/disable is explicit and retains history. Exact evidence digests reuse evaluations. Feedback persists without evaluator/provider calls. Impact is descriptive usage and subsequent outcomes, not causal percentages.

The actual production composition factories and actual Developer plan-reviser / Researcher plan-generator request paths are exercised with fake SDK responses. Approved guidance reaches both requests. Pending, rejected, disabled, wrong-domain and unrelated-project guidance is excluded across the dedicated and final suites. Rules remain below system/security constraints, workflow invariants, explicit user requests and authoritative state. Developer approval and Researcher no-execution survive adversarial guidance tests.

Context is limited to six whole rules and 8,192 UTF-8 bytes with deterministic scope ordering. Improvement persistence uses exactly `runtime_paths().data / "improvements"`. No independent XDG/AppData resolver, provider-on-refresh, recursive evaluation, automatic source rewriting, package installation or git operation was introduced.

## Desktop, first run and persistence

All eight navigation surfaces are exercised offscreen: Dashboard, Projects, Developer, Researcher, Hybrid, Artifacts, Improvements and Settings. Existing GUI tests cover creation/confirmation/binding, direction choice, result input, artifact preview/export, explicit handoff/bootstrap, improvement review, provider settings, worker threading, duplicate-request suppression and normal close. The new final journey covers the previously missing phase-checkpoint decision.

Fresh-start acceptance uses temporary XDG roots and simulated frozen workspace selection, with no existing configuration, workspace, projects or improvements. It proves writable directories are created, pages construct, empty states are usable, no provider is called, and no run/evaluation appears on startup. Persisted project sessions, both domain runs, handoff provenance, provider non-secret settings and improvement history are reconstructed in the cross-feature suites. Navigation/reconstruction does not progress workflows or consume tokens.

Central locations remain:

| Location | Windows | Linux |
| --- | --- | --- |
| Config | `%APPDATA%/ai-agent/llm.json` | XDG config root / `ai-agent/llm.json`, with home fallback |
| Data | `%LOCALAPPDATA%/ai-agent/data` | XDG data root / `ai-agent`, with home fallback |
| Frozen workspace | Data root / `workspaces/default` | Data root / `workspaces/default` |
| Cache | `%LOCALAPPDATA%/ai-agent/cache` | XDG cache root / `ai-agent` |
| Improvements | Data root / `improvements` | Data root / `improvements` |

Source-launch cwd workspace behavior is intentional development behavior; packaged persistence/workspace does not default to the installation directory. The default workspace is shared, not an isolation boundary between projects. Explicit existing workspace settings remain supported at service/CLI boundaries.

## Security and file safety audit

The audit reproduced and repaired these direct boundary violations using synthetic files only:

| Severity | Finding | Smallest repair / proof |
| --- | --- | --- |
| P0, closed | FileTool could read `.env.local` and reach secret files through an in-workspace alias | Apply secret-path checks to both requested and resolved paths; protect environment variants, case-insensitive spelling, Windows stream suffixes and trailing-dot/space normalization |
| P0, closed | A shell command's supposed path argument could actually be an option | Reject leading `-` in allowed path variants before launch |
| P0, closed | An allowed command could target a symlink outside its workspace | Resolve explicit pytest/ruff targets, require workspace containment, and apply the same environment-file checks before launch |
| P0, closed | Execution artifacts serialized nested agent conversations and tool state | Exclude primary and repair AgentState objects at the shared artifact projection; preview/export regression verifies synthetic private text absent and persisted run unchanged |
| P1, closed | Desktop could not decide a Developer phase checkpoint | Explicit dialog → facade → project-action validation → existing domain decision service |

Regression verifies traversal/absolute-path/symlink rejection and legitimate in-workspace list/read/write/command behavior. Export retains atomic no-overwrite publishing and existing platform-specific symlink/reparse-point protections. Snapshot stores retain canonical identifier validation, atomic replacement and existing cross-platform local locking. Windows filesystem behavior beyond simulated path/lexical tests still requires native acceptance.

Search classification:

- `OPENAI_API_KEY`, `.env`, environment access: central configuration/paths, security rejection logic, or packaging smoke environment sanitization; not new credential persistence.
- `Path.cwd()`: source CLI/development workspace and explicit local export resolution; not packaged application state or improvement defaults.
- `subprocess`: existing approved Developer command execution and isolated build-time bundle smoke. No Researcher/improvement subprocess facility.
- Qt `app.exec()` / `dialog.exec()`: event loops/dialogs, not Python `exec`.
- `ast.literal_eval`: literal acceptance parsing, not unrestricted evaluation.
- git/package/process words in improvement context: deterministic rejection patterns.
- Resource handling uses one resolver based on packaged `__file__`; no scattered `_MEIPASS` special cases.
- No production personal `/home/...` or `/tmp/...` default was added. Temporary audit/test/build paths are test or build artifacts.

A value-withholding scan of tracked text found no plausible OpenAI/GitHub/AWS/private-key patterns. Synthetic test credentials are intentional fixtures. `.env` is ignored and untracked. Nothing is staged. No build/dist output, executable, installer, screenshot or temporary debug source was added to tracked changes. No source self-modification or automatic approval/progression facility was found.

These protections are not a claim of OS-level containment for malicious approved Developer test code, arbitrary third-party dependencies, or concurrent hostile filesystem replacement. Run Developer work only in trusted, reviewed workspaces under the user's normal permissions. The local app is not designed as an adversarial multi-user sandbox.

## Distribution, dependencies and smoke evidence

PySide6 is a justified runtime dependency. PyInstaller is isolated in the build dependency group; pytest/Ruff are development dependencies. No competing packaging framework or dependency upgrade was introduced. FastAPI remains a source dependency for the supported API but is excluded from the GUI bundle. The explicit one-directory spec uses `console=False`, standard PySide6 hooks, a repository-owned icon, minimal package version metadata and an explicit asset list. User data, `.env`, tests, editable-install URLs and build tooling are excluded/audited.

Source native smoke `uv run ai-agent-desktop --packaging-smoke` ran successfully on the available WSL display using temporary stores: Qt initialized, Dashboard/Projects/Settings constructed, and the window closed with exit 0. This is an automated native smoke, not a human visual/usability sign-off. Full offscreen tests cover the remaining pages and actions.

The Linux package was rebuilt after the final code fix:

```sh
uv run --group build python -m PyInstaller --noconfirm --distpath dist/final-audit-linux --workpath build/final-audit-linux packaging/pyinstaller/ai-agent.spec
uv run --group build python packaging/verify_bundle.py dist/final-audit-linux/AI-Agent --smoke
file dist/final-audit-linux/AI-Agent/AI-Agent
```

Result: **LINUX PACKAGING SMOKE** passed. The executable is **ELF 64-bit x86-64 for Linux**, not a Windows executable. Frozen GUI startup, resources/version, clean exit and embedded bundle/module hygiene pass. The bundle includes the audit fixes on top of baseline HEAD. Generated outputs stay ignored/unstaged.

Windows packaging is structurally configured for `AI-Agent.exe` and Inno Setup `AI-Agent-Setup.exe`: locked uv dependencies, native Windows/x64 guard, per-user install, Start Menu shortcut, optional desktop shortcut, uninstall entry and preserved user state. The workflow uses `windows-2022`, Python 3.12, uv, packaging tests, PyInstaller, PE/Qt/frozen bundle acceptance, Inno Setup and artifact uploads. No signing secret is assumed. PowerShell 5.1.26100.9444 and uv were found; ISCC was not available via the inspected command lookup. No Inno Setup installation or native artifact build was performed.

Builds are unsigned. SmartScreen or organizational application control may warn/block them. No security protection was disabled. Trusted signing and a normal-user Windows install/launch/restart/uninstall smoke remain distribution work.

## Windows workflow 404: concrete cause

Read-only GitHub inspection established:

- Local `main` and remote `main`: `5c3506d1523ff437cd246a3f1e6a0a93f771bb66`.
- Workflow introduced in `c5356c2`; tracked path is exactly `.github/workflows/windows-package.yml`.
- The same path exists on remote `main` (blob `bd2f35cf6d2f56ac72e1081244f833193a6930e4`). It was **not merely an unpushed local file**.
- Repository default branch is **`master`**, not `main`.
- Reading the workflow at `ref=master` returns 404.
- Repository is neither archived nor disabled. Actions is enabled with actions allowed. Workflow listing contains only the dynamic Dependency Graph workflow.

This is a default-branch/workflow-presence mismatch, not a filename mismatch or disabled Actions. GitHub requires the manual-dispatch workflow on the default branch before it can be manually triggered. See [GitHub's manual workflow documentation](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow). No workflow run or artifact success is claimed; no settings were changed and no workflow was dispatched.

## Final verification results

All final verification below ran after the fixes, including the final environment-path spelling repair. Commands used `UV_CACHE_DIR=/tmp/ai-agent-uv-cache` and `-p no:cacheprovider`. GUI runs used `QT_QPA_PLATFORM=offscreen`. Broad/full runs unset `RUN_OPENAI_E2E`. API/full suites ran outside the sandbox because TestClient had previously stalled under sandbox restrictions.

| Check | Result |
| --- | --- |
| `pytest tests/final_acceptance -q` | **22 passed** |
| `pytest tests/improvement -q` | **64 passed** |
| `pytest tests/desktop_app -q` | **20 passed** |
| `pytest tests/desktop -q` | **23 passed** |
| `pytest tests/packaging -q` | **25 passed** |
| `pytest tests/agent tests/llm tests/integration tests/api tests/test_cli.py -q` | **547 passed, 12 skipped** |
| `pytest -q` | **755 passed, 12 skipped** |
| `ruff check .` | Passed |
| `ruff format --check .` | 214 files already formatted |
| `git diff --check` | Passed |
| `uv run ai-agent --help` | Exit 0 |
| Source native packaging smoke | Exit 0, success marker, frozen=false |
| Rebuilt Linux frozen acceptance | `LINUX_PACKAGING_SMOKE=PASSED` |

**LIVE_PROVIDER_E2E_NOT_RUN.** The skipped tests require explicit paid-provider opt-in. Deterministic SDK/provider integration passed; the audit did not change provider protocol construction.

## Remaining findings and release conditions

- **P0:** None open; four direct security boundary findings closed above.
- **P1 application:** None open; desktop checkpoint journey repaired and reverified.
- **P2:** Shared default workspace and limited workspace-selection UX; long-running requests cannot be cancelled and close waits for completion; status/error messages can be generic; improvement lexical/conflict filters are conservative; existing README opening/older architecture inventories emphasize historical CLI scope. These do not prevent the tested primary journeys and were not expanded/refactored.
- **P3:** Optional OS credential storage, richer previews/observed-impact UI and other nonessential polish remain deferred. No implementation was undertaken.
- **Windows release conditions:** Align default-branch workflow availability, include the reviewed audit fixes in the release revision, run native Windows CI, verify both artifacts, then perform real normal-user installation/configuration/restart/uninstall/data-preservation acceptance. Signing is a separate distribution decision; unsigned status must remain explicit.
- **Operational prerequisites:** A compatible Responses/structured-output provider and the toolchain required by the user's Developer project. Researcher execution stays external. These are not bundled model services, compilers or an IDE.

Retain version **0.1.0** for the first release candidate; no version bump or invented release history is justified by this audit.

## Audit changes and next operational action

Modified only:

- `src/ai_agent_project/agent/project_action_application.py`
- `src/ai_agent_project/agent/project_artifact_application.py`
- `src/ai_agent_project/command_policy.py`
- `src/ai_agent_project/desktop/service.py`
- `src/ai_agent_project/desktop_app/dialogs.py`
- `src/ai_agent_project/desktop_app/window.py`
- `src/ai_agent_project/tools/file.py`
- `src/ai_agent_project/tools/shell.py`

Added four files under `tests/final_acceptance/` and this report. Existing regression tests and historical phase documents were not rewritten. All changes remain unstaged; baseline HEAD is unchanged.

The maintainer's next action is operational: review/record these fixes in the intended release revision, align GitHub's default branch with the release branch (or otherwise place the workflow on the default branch), then run **Windows desktop distribution** and verify both native artifacts. Alternatively, use a suitable local Windows checkout with Inno Setup already provisioned and run `powershell -ExecutionPolicy Bypass -File packaging/windows/build.ps1 -Installer`. Do not publish a fully verified Windows release before those checks. No new implementation phase is proposed.
