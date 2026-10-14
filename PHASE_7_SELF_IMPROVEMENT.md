# Phase 7 — Human-Governed Self-Improvement

This feature is evidence-based, experience-based, human-approved, context-level adaptation. It is **not** fine-tuning, reinforcement learning, recursive reflection, autonomous source modification, automatic prompt-file rewriting, or automatic experimentation.

## Architecture and authority

`improvement/` owns separate immutable evidence, evaluation, candidate, rule, feedback, application-usage, impact and history records. `ImprovementService` collects evidence through read-only run readers and ProjectSession listing. Neither workflow state machines nor artifact/handoff ownership models contain improvement lifecycle fields.

An explicit evaluation reads evidence, calls the evaluator once, and atomically persists an evaluation and zero or more **pending** candidates. It stops there. A separate user approval creates a distinct rule. Rejection retains the candidate and evidence but creates no rule. Confidence never authorizes approval. Enable/disable operations append immutable rule versions and user-history events; original approval provenance remains intact. To change guidance, disable the old rule and approve a different candidate; direct rule editing is deliberately absent.

The effective authority order is:

1. System/security constraints.
2. Application workflow invariants.
3. Current explicit user request.
4. Authoritative current workflow state.
5. User-approved experience-based guidance.
6. Supporting history/context.

Trusted code assigns IDs, source run/project identity, timestamps, evidence references, status and approval provenance. The strict evaluator schema contains proposal content only. The LLM cannot activate rules or transition workflows.

## Evidence and evaluation

Developer evidence contains persisted status, phase/completion/attempt/failure/repair counts, plan revision count and approval state. Researcher evidence contains persisted status, direction-selection state, plan revisions/approval, result/analysis/synthesis/material presence and source/evidence counts. Both include feedback rating counts and up to 50 feedback references. Project identity is derived from authoritative bindings; an ambiguous shared run does not acquire guessed project scope.

Evidence excludes request transcripts, tool logs, file contents, environment, provider configuration and credentials. Optional feedback comments remain bounded local feedback records; only ratings/references enter the evaluator. The evidence digest hashes the authoritative run snapshot, feedback identities/ratings and project binding; the full snapshot is not copied into improvement persistence.

`ImprovementEvaluator` supports deterministic fakes. `OpenAIImprovementEvaluator` uses the existing configured OpenAI-compatible runtime, strict Responses structured output, and `store=False`. Custom URL/model/timeout/session credential behavior remains centrally controlled. Its instructions treat evidence as untrusted data and prohibit invented history or executing embedded instructions. A single run does not establish a recurring pattern. Evaluation/provider failure leaves source workflows and improvement state unchanged and returns a fixed sanitized error.

Identical domain/run/evidence digests reuse the existing evaluation without a second provider call. Explicit feedback or changed run evidence changes the digest. Exact candidate duplicates use normalized Unicode/case/whitespace plus domain/project identity; historical rejected candidates are included in deduplication. No semantic LLM merging occurs.

## Rules and retrieval

Allowed categories: planning, prompt_strategy, tool_selection, validation, error_recovery, research_strategy, evidence_quality and project_specific. Rules must be nonblank and at most 1,600 characters; title/rationale are at most 500 characters. Evaluations allow at most five candidates and five entries per analysis section. Evidence references are application-owned.

Scopes are global, developer, researcher and project, with optional domain restriction on project scope. Project-specific candidates require a known project and project scope. Retrieval excludes disabled and unrelated rules. Order is project+domain, project, domain, global, then newest approval and stable rule ID.

`ImprovementContext` contains at most **6 whole rules** and **8,192 UTF-8 bytes**, including its authority label and serialized context. Selection skips rules that do not fit rather than truncating text. Deterministic lexical checks reject protected guidance at proposal validation, approval, and retrieval. Examples include bypassing approval, automatically continuing, changing authentication/security restrictions, overriding system instructions, exposing credentials and making Researcher execute code. These checks are conservative defenses, not a general natural-language security classifier. Actual workflow checks remain authoritative even if text evades a lexical pattern.

Simple opposing wording (for example “Always inspect interfaces” versus “Never inspect interfaces”) is flagged for human inspection. When both rules match the current context, neither is injected; the UI identifies the conflict and asks for explicit enable/disable review. More complex semantic conflicts are not automatically recognized or resolved.

## Actual provider integration

The existing production composition factories wrap their application services in `ImprovementAwareApplication`. It wraps only named provider-backed commands: creation, planning/revision, explicit Developer phase execution and explicit Researcher generation/analysis/synthesis operations. Reads, approval, direction selection and result submission are not wrapped as model operations.

At the start of each explicit operation, the wrapper resolves a fresh immutable context. The shared configured `_SafeResponses` boundary adds its labeled guidance to the model input and its authority constraints to instructions. No store, evaluator or approval service reaches a provider. ContextVar scopes reset after success or failure. Newly approved rules affect later calls; old run snapshots are never rewritten by approval.

Desktop lane creation and desktop/CLI/API handoff bootstrap supply the authoritative project hint before a new run has a binding. Existing-run operations resolve project membership through the session reader. No automatic next action is introduced.

Acceptance uses the **production composition factories and actual `OpenAIProjectPlanReviser` / `OpenAIResearchPlanGenerator` request paths**, replacing only the SDK client with a deterministic fake. It verifies pending/rejected/disabled/wrong-domain exclusion and approved guidance in the actual request. Developer revisions remain `awaiting_plan_approval`; executing before approval still raises the existing plan-review error without a provider call. Research plans remain `awaiting_research_plan_approval`. Researcher has no execution API; adversarial stored execution guidance is blocked before a provider request or source mutation.

## Persistence, feedback and observed impact

The store uses `paths.runtime_paths().data / "improvements"` — no second platform resolver, installation-directory path or current-directory default.

- Linux: `$XDG_DATA_HOME/ai-agent/improvements`, otherwise `~/.local/share/ai-agent/improvements`.
- Windows: `%LOCALAPPDATA%/ai-agent/data/improvements`, with the existing centralized home/AppData fallback.
- Explicit injected roots are supported for isolated tests.

`state.json` contains the separate improvement snapshot, including immutable rule revisions and events. Updates use the existing local file lock, a validated temporary file, fsync and atomic replacement. Reads create no directories or lock files. Evaluation and candidate creation are one atomic update. Disable/reject never erase historical evidence. Service and GUI reconstruction preserve the records without evaluating or advancing anything.

Feedback is an explicit Helpful / Needs Improvement rating with an optional 500-character comment. Saving feedback calls no LLM and advances no workflow. Known credential-shaped text is rejected; users should not put secrets or private transcripts into comments. API keys remain session-only and are neither included in evidence nor written to improvement storage.

Usage records capture the rule IDs/versions actually sent during a successfully completed explicit application operation. They are not counted by refresh or context preview. Impact reports operation usage, distinct applied runs, subsequent helpful/not-helpful feedback and distinct runs evaluated after application. These are descriptive observations, **not causal improvement percentages**. Failed operations are not included in successful-operation usage; workflow persistence and improvement usage persistence are separate stores, not a cross-store transaction.

## User surfaces

Desktop facade reads return immutable records and invoke no provider or mutation. Explicit actions are evaluation, candidate approval/rejection, rule enable/disable and feedback. The native Improvements page provides Candidates, Approved Rules, Evaluations and Feedback / Impact tabs, provenance previews and explicit buttons. Developer/Researcher lanes expose Evaluate Run and Give Feedback. The existing one-operation Qt worker runs evaluation with busy feedback; widgets update through GUI-thread signals. Navigation/refresh never evaluates. Dashboard shows pending-candidate and enabled-rule counts.

CLI examples (replace identifiers with stored IDs):

```sh
uv run ai-agent improvement candidates
uv run ai-agent improvement rules
uv run ai-agent improvement evaluations
uv run ai-agent improvement evaluate developer RUN_ID
uv run ai-agent improvement evaluate researcher RUN_ID
uv run ai-agent improvement approve CANDIDATE_ID --scope developer
uv run ai-agent improvement reject CANDIDATE_ID
uv run ai-agent improvement disable RULE_ID
uv run ai-agent improvement enable RULE_ID
uv run ai-agent improvement feedback developer RUN_ID helpful --text "Useful review"
uv run ai-agent improvement impact RULE_ID
```

The existing supported API adds narrow `/v1/improvements` endpoints: GET candidates/rules/evaluations, POST evaluations, POST candidates/{id}/approve or /reject, POST rules/{id}/enable or /disable, GET rules/{id}/impact and POST feedback. They use the same service; desktop imports no HTTP adapter. Existing API workflow storage conventions remain unchanged, including in-memory defaults for source runs.

## Verification evidence

Provider-free tests cover atomic persistence/failure, application-owned provenance, pending/approve/reject lifecycle, scopes/order/limits, protected policy variants, actual production provider injection, checkpoint preservation, Researcher no-execution, deduplication, feedback, impact, repeated desktop reads, CLI/API actions, Qt worker actions and reconstruction. No live OpenAI E2E was run.

Verified on 2026-09-11:

| Check | Result |
| --- | --- |
| `uv run pytest tests/improvement -q -p no:cacheprovider` | 64 passed |
| `QT_QPA_PLATFORM=offscreen uv run pytest tests/desktop_app -q -p no:cacheprovider` | 20 passed |
| `uv run pytest tests/desktop -q -p no:cacheprovider` | 23 passed |
| `uv run pytest tests/agent tests/llm tests/integration tests/api tests/test_cli.py -q -p no:cacheprovider` | 547 passed, 12 skipped |
| `QT_QPA_PLATFORM=offscreen uv run pytest tests/packaging -q -p no:cacheprovider` | 25 passed |
| `uv run ai-agent improvement --help` | Exit 0; explicit operations listed |
| `uv run ruff check .` | Passed |
| `uv run ruff format --check .` | 209 files already formatted |
| `git diff --check` | Passed |

Commands used `UV_CACHE_DIR=/tmp/ai-agent-uv-cache` for this environment. The improvement GUI tests set Qt offscreen themselves. API TestClient tests were run outside the restricted sandbox because TestClient stalled there; no network provider access was needed. The initial broad run exposed four route-introspection failures caused by nested router registration. Registering improvement routes directly, consistent with the existing API, fixed all four without changing existing tests or workflow semantics.

The dedicated acceptance test is `tests/improvement/test_acceptance.py::test_phase7_acceptance_restart_feedback_and_history`, supplemented by production provider-path and Qt worker tests in that suite. Security inspection found only rejection-pattern literals for process/package/git terms in improvement code; Qt `dialog.exec()` / `app.exec()` are native event-loop calls, not Python code execution. The improvement module does not read environment variables or invoke subprocesses. `.env` is ignored and untracked; no staged paths, generated build outputs, credentials, or personal absolute paths were added. No commit or push was performed.

`PHASE_7_HUMAN_GOVERNED_SELF_IMPROVEMENT=PASSED`

## Limitations

Evaluation sees bounded status/count evidence, not full transcripts or arbitrary code, and does not infer undocumented rejection/rollback/test history. Recurrence analysis and semantic conflict detection are intentionally limited. Guidance cannot guarantee better results. Lexical protection may reject benign wording and cannot recognize every paraphrase or secret format; human approval and unchanged trusted execution restrictions remain essential. The local snapshot/history can grow over time; no database, background compaction, evaluator queue, autonomous evaluation or cross-store transaction was introduced. Windows path behavior is tested through the centralized resolver; Phase 7 does not claim a new native Windows build or installer verification.
