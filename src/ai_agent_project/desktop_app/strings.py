"""Korean presentation only. Never translate code, paths, prompts or persisted values."""

TEXT = {
    "Dashboard": "대시보드",
    "Projects": "프로젝트",
    "Developer": "개발 에이전트",
    "Researcher": "리서치 에이전트",
    "Hybrid": "통합 작업",
    "Artifacts": "결과물",
    "Improvements": "개선 관리",
    "Settings": "설정",
    "Project Detail": "프로젝트 상세",
    "Total projects": "전체 프로젝트",
    "Active": "실행 중",
    "Completed": "완료",
    "Awaiting user": "사용자 확인 대기",
    "Project": "프로젝트",
    "WorkMode": "작업 유형",
    "ProjectMode": "프로젝트 유형",
    "Status": "상태",
    "Pending action": "필요한 작업",
    "Created": "생성됨",
    "Modified": "수정됨",
    "Deleted": "삭제됨",
    "Observed": "관측됨",
    "Observed Change": "관측된 변경",
    "New Project": "새 프로젝트 만들기",
    "Open Project": "선택한 프로젝트 열기",
    "Refresh": "새로고침",
    "Provider Settings": "제공자 설정",
    "Provider Type": "제공자 유형",
    "OpenAI-compatible": "OpenAI 호환",
    "Base URL": "기본 URL",
    "Model": "모델",
    "Timeout (seconds)": "응답 제한 시간(초)",
    "API key": "API Key",
    "Enter session API key; leave blank to retain current credential": "이번 실행에서 사용할 API Key를 입력하세요. 비워두면 현재 키를 유지합니다.",
    "API key is used for this application session and is not saved in the normal configuration file. OS credential storage is deferred.": "API Key는 현재 프로그램 세션의 메모리에서만 사용하며 설정 파일에 저장하지 않습니다. OS 자격 증명 저장은 지원하지 않습니다.",
    "Save Settings": "설정 저장",
    "Test Connection": "연결 확인",
    "Yes": "예",
    "No": "아니요",
    "None": "없음",
    "Not selected": "선택하지 않음",
    "No — configure in Settings": "없음 — 설정에서 입력하세요",
    "Awaiting mode confirmation": "작업 유형 확인 대기",
    "No project selected. Open a project from Projects.": "선택한 프로젝트가 없습니다. 프로젝트 화면에서 프로젝트를 여세요.",
    "No projects yet. Create a project to request a mode proposal.": "등록된 프로젝트가 없습니다. 새 프로젝트를 만들어 작업 유형을 제안받으세요.",
    "Lane not bound. Create a run, then explicitly bind its run ID.": "연결된 실행이 없습니다. 실행을 생성한 뒤 실행 ID 연결을 별도로 승인하세요.",
    "Evaluate Run": "실행 평가",
    "Give Feedback": "의견 남기기",
    "Research → Developer Handoffs": "리서치 → 개발 자료 전달",
    "Select a Researcher artifact in Artifacts to create a context handoff.": "결과물 화면에서 리서치 결과물을 선택해 개발에 전달할 자료를 만드세요.",
    "Create Developer Run From Research": "리서치 자료로 개발 실행 만들기",
    "No handoffs created.": "전달된 자료가 없습니다.",
    "Title / type": "제목 / 유형",
    "Domain": "작업 유형",
    "Source run": "원본 실행",
    "Version": "버전",
    "Media": "형식",
    "Copy Preview": "미리보기 복사",
    "Export JSON…": "JSON 내보내기…",
    "Create Developer Context Handoff": "개발 참고 자료 전달",
    "Select an artifact to preview.": "미리볼 결과물을 선택하세요.",
    "Artifact preview unavailable. Refresh and try again.": "결과물을 미리볼 수 없습니다. 새로고침 후 다시 시도하세요.",
    "Export to a new file (existing files are never overwritten)": "새 파일로 내보내기(기존 파일은 덮어쓰지 않음)",
    "Check URL, model, timeout and credential input.": "URL, 모델, 제한 시간과 API Key 입력을 확인하세요.",
    "Cancel": "취소",
    "Title": "제목",
    "Request / description": "요청 / 설명",
    "Request Mode Proposal": "작업 유형 제안받기",
    "A proposal is created first. Confirm its modes separately.": "먼저 작업 유형을 제안받습니다. 제안된 유형의 확정은 별도 승인이 필요합니다.",
    "Confirm Project Modes": "작업 유형 확정",
    "Proposed WorkMode": "제안된 작업 유형",
    "Proposed ProjectMode": "제안된 프로젝트 유형",
    "Research Direction": "리서치 방향",
    "Select Direction": "방향 선택",
    "Research Results": "리서치 결과",
    "Provide Research Results": "리서치 결과 제출",
    "Your observations / results": "사용자가 확인한 내용 / 결과",
    "Submitting records your observations. Analysis requires a separate action.": "제출한 관측 내용을 기록합니다. 결과 분석은 별도로 요청해야 합니다.",
    "Run Created": "실행 생성됨",
    "Run ID (copy to retain if you cancel)": "실행 ID(취소할 경우 보관하려면 복사하세요)",
    "The run is saved. Binding requires your explicit confirmation below.": "실행이 저장되었습니다. 프로젝트 연결은 아래에서 별도로 승인해야 합니다.",
    "Review Developer Checkpoint": "개발 단계별 승인 검토",
    "Submit Checkpoint Decision": "단계별 승인 결정 제출",
    "Choose a decision": "결정을 선택하세요",
    "Decision": "결정",
    "Optional note": "메모(선택)",
    "Review phase progress and acceptance artifacts before deciding.": "결정하기 전에 단계 진행 상황과 검증 결과물을 검토하세요.",
    "Pending human action": "사용자 승인 / 입력 필요",
    "Confirm WorkMode and ProjectMode": "작업 유형과 프로젝트 유형 확정",
    "Run ID to bind": "연결할 실행 ID",
    "Choose a research direction": "리서치 방향 선택",
    "Your research observations / results": "사용자가 확인한 리서치 내용 / 결과",
    "Explicit confirmation": "명시적 승인",
    "Bind Run": "실행 연결",
    "Run ID": "실행 ID",
    "Developer From Research": "리서치 자료로 개발 시작",
    "Developer request": "개발 요청",
    "AI Agent — Local Workspace": "AI Agent — 작업 폴더",
    "AI Agent  /  Local Workspace": "AI Agent / 작업 폴더",
    "Working on your requested operation…": "요청한 작업을 처리하고 있습니다…",
    "Requested operation completed.": "요청한 작업 처리가 완료되었습니다.",
    "Unable to load this view. Check local configuration and refresh.": "화면을 불러올 수 없습니다. 설정을 확인하고 새로고침하세요.",
    "Unable to prepare this action. Refresh and check its required input.": "작업을 준비할 수 없습니다. 새로고침하고 필요한 입력을 확인하세요.",
    "This action is unavailable in this desktop version.": "현재 Desktop 버전에서는 이 작업을 지원하지 않습니다.",
    "Wait for the requested operation to finish before closing.": "진행 중인 작업이 끝난 뒤 프로그램을 닫으세요.",
    "Operation failed. Check your input and settings, then refresh and try again.": "작업을 처리하지 못했습니다. 입력과 설정을 확인한 뒤 새로고침하고 다시 시도하세요.",
    "Cannot start AI Agent. Check installation and user-directory access.": "AI Agent를 시작할 수 없습니다. 설치 상태와 사용자 폴더 접근 권한을 확인하세요.",
    "Workspace · current disk files": "작업 폴더 · 실제 저장 파일",
    "Open Workspace Folder": "작업 폴더 열기",
    "File": "파일",
    "Disk": "저장 상태",
    "Plan": "계획",
    "Present": "저장됨",
    "No saved file": "저장된 파일 없음",
    "Planned": "계획됨",
    "Plan entries are intentions. Present means a file exists now; shared workspace files cannot be attributed to this run.": "계획은 실행 예정 내용입니다. 저장됨은 실제 파일이 있다는 뜻이며, 공유 작업 폴더의 파일을 이 실행이 만들었다고 단정하지 않습니다.",
    "Workspace folder does not exist. Saved run history does not imply saved files.": "작업 폴더가 없습니다. 실행 기록이 남아 있어도 실제 파일이 저장되어 있다는 뜻은 아닙니다.",
    "No public saved files found. Private and generated files are excluded.": "공개 가능한 저장 파일이 없습니다. 비공개 파일과 자동 생성 파일은 표시하지 않습니다.",
    "File listing is limited; some files are not shown.": "표시 개수 제한으로 일부 파일이 보이지 않을 수 있습니다.",
    "Select a file to inspect its current disk content.": "파일을 선택하면 현재 저장된 코드를 확인할 수 있습니다.",
    "The system file manager could not open the workspace folder.": "파일 관리자로 작업 폴더를 열 수 없습니다. 경로를 복사해 직접 여세요.",
    "Execution Timeline · recorded events": "실행 기록 · 실제 기록된 이벤트",
    "Sequence / time": "순서 / 시각",
    "Phase / attempt": "단계 / 시도",
    "Event": "이벤트",
    "No recorded execution events. Saved workflow state is shown above.": "기록된 실행 이벤트가 없습니다. 저장된 작업 상태는 위에서 확인할 수 있습니다.",
    "Agent completed means the Agent returned. Tool and Validation results provide execution evidence. File changes are observations with unconfirmed cause.": "에이전트 완료는 응답이 반환됐다는 뜻입니다. 실제 실행 여부는 도구와 검증 결과로 확인하세요. 파일 변경 원인은 확정하지 않습니다.",
    "Load earlier events": "이전 기록 보기",
    "Return to live events": "실시간 기록으로 돌아가기",
    "no recorded execution": "실행 기록 없음",
    "not available (rejected, timed out or not completed)": "확인 불가(거절·시간 초과·미완료)",
    "Code Changes / Diff · Observed Change": "코드 변경 내역 · 관측된 변경",
    "Historical Diff Unavailable: no recorded snapshots.": "과거 변경 비교 불가: 저장된 스냅샷이 없습니다.",
    "Recovery is read-only.": "복구 정보는 조회만 가능합니다.",
    "Phase baseline": "단계 실행 전 기준",
    "Previous recorded snapshot": "직전 스냅샷",
    "Follow latest recorded snapshot": "최신 스냅샷 따라가기",
    "Load older snapshots": "이전 스냅샷 보기",
    "Attribution": "변경 원인",
    "unavailable": "확인 불가",
    "absent/unknown": "없음 / 확인 불가",
    "Run Feedback": "실행 의견",
    "Save Feedback": "의견 저장",
    "Helpful": "도움이 됨",
    "Needs Improvement": "개선 필요",
    "Rating": "평가",
    "Comment": "의견",
    "Optional feedback (500 characters). Do not include credentials.": "의견을 입력하세요(선택, 500자). API Key 등 민감정보를 포함하지 마세요.",
    "Agent Improvement": "에이전트 개선 관리",
    "Candidates": "개선 후보",
    "Approved Rules": "승인된 규칙",
    "Evaluations": "평가 기록",
    "Feedback / Impact": "의견 / 관측 결과",
    "Domain / project": "작업 유형 / 프로젝트",
    "Category": "분류",
    "Confidence": "신뢰도",
    "Rule": "규칙",
    "Scope": "적용 범위",
    "Enabled": "사용 여부",
    "Run": "실행",
    "Evidence": "근거",
    "Target": "대상",
    "Source domain": "원본 작업 유형",
    "Approve Candidate": "후보 승인",
    "Reject Candidate": "후보 거절",
    "Enable Rule": "규칙 사용",
    "Disable Rule": "규칙 사용 중지",
    "User-approved experience-based guidance. Evaluation and approval are separate actions. Usage and outcomes are descriptive, not causal proof.": "사용자가 승인한 경험 기반 지침입니다. 평가와 승인은 별도 작업입니다. 사용 및 결과 기록만으로 인과관계를 입증할 수는 없습니다.",
    "Select a record to inspect its provenance and available actions.": "기록을 선택하면 출처와 가능한 작업을 확인할 수 있습니다.",
    "Cannot load improvement outcomes.": "개선 결과를 불러올 수 없습니다.",
    "Confirm the work mode and project mode.": "작업 유형과 프로젝트 유형을 확인하고 승인하세요.",
    "Create a Developer run explicitly, then bind its ID to this project.": "개발 실행을 생성한 뒤 실행 ID를 프로젝트에 연결하세요.",
    "Create a Researcher run explicitly, then bind its ID to this project.": "리서치 실행을 생성한 뒤 실행 ID를 프로젝트에 연결하세요.",
    "Review and explicitly approve or revise the Developer plan.": "개발 계획을 검토한 뒤 승인하거나 수정을 요청하세요.",
    "Invoke the appropriate explicit Developer lifecycle command.": "현재 상태를 검토한 뒤 필요한 개발 작업을 별도로 요청하세요.",
    "Select one of the available research directions explicitly.": "제안된 리서치 방향 중 하나를 선택하세요.",
    "Review and explicitly approve or revise the research plan.": "리서치 계획을 검토한 뒤 승인하거나 수정을 요청하세요.",
    "Run the package externally and explicitly submit the research results.": "패키지를 외부에서 직접 실행한 뒤 리서치 결과를 제출하세요.",
    "Invoke the appropriate explicit Researcher lifecycle command.": "현재 상태를 검토한 뒤 필요한 리서치 작업을 별도로 요청하세요.",
    "No recorded execution evidence.": "기록된 실행 근거가 없습니다.",
    "Recovery is read-only. No retry, repair or rollback is performed.": "복구 정보는 조회만 가능합니다. 재시도·수정·되돌리기를 자동으로 수행하지 않습니다.",
    "Terminal workflow evidence exists. This does not assert that all tools or tests succeeded.": "작업 종료 기록이 있습니다. 모든 도구와 테스트가 성공했다는 뜻은 아닙니다.",
    "An active execution lease exists; workflow outcome is not yet known.": "실행 잠금이 유지되고 있습니다. 최종 결과는 아직 확인되지 않았습니다.",
    "Phase start was recorded, no terminal event or active lease exists. Outcome Unknown.": "단계 시작 기록은 있지만 종료 기록과 실행 잠금이 없습니다. 결과를 확인할 수 없습니다.",
    "Start/end evidence or execution lease could not establish an outcome.": "시작·종료 기록 또는 실행 잠금으로 결과를 판정할 수 없습니다.",
    "Historical Diff Unavailable: a before or after snapshot was not recorded.": "과거 변경 비교 불가: 실행 전 또는 이후 스냅샷이 없습니다.",
    "Historical Diff Unavailable: verified snapshot reads are unavailable on this platform.": "과거 변경 비교 불가: 이 OS에서는 안전한 스냅샷 조회를 지원하지 않습니다.",
}

VALUES = {
    "developer": "개발 에이전트",
    "researcher": "리서치 에이전트",
    "hybrid": "통합 작업",
    "project": "프로젝트",
    "global": "전체",
    "new": "새 프로젝트",
    "upgrade": "기존 프로젝트 개선",
    "active": "진행 중",
    "running": "실행 중",
    "completed": "완료",
    "failed": "실패",
    "awaiting_mode_confirmation": "작업 유형 확인 대기",
    "awaiting_plan_approval": "계획 승인 대기",
    "awaiting_approval": "승인 대기",
    "approved": "승인됨",
    "ready": "실행 준비됨",
    "awaiting_checkpoint": "단계별 승인 대기",
    "revision_requested": "수정 요청됨",
    "retry_requested": "재시도 요청됨",
    "stopped": "중지됨",
    "pending": "검토 대기",
    "rejected": "거절됨",
    "helpful": "도움이 됨",
    "not_helpful": "개선 필요",
    "Active": "실행 중",
    "Finished": "종료됨",
    "Failed": "실패",
    "Interrupted": "실행 중단",
    "Outcome Unknown": "결과 확인 불가",
    "Created": "생성됨",
    "Modified": "수정됨",
    "Deleted": "삭제됨",
    "Observed": "관측됨",
    "Observed Change": "관측된 변경",
    "created": "생성됨",
    "modified": "수정됨",
    "deleted": "삭제됨",
    "observed": "관측됨",
    "started": "시작됨",
    "finished": "종료됨",
    "succeeded": "성공",
    "before": "실행 전",
    "after": "실행 후",
    "tool": "도구 실행 후",
    "approve": "승인",
    "reject": "거절",
    "retry": "다시 시도",
    "stop": "중지",
    "revise": "수정 요청",
    "approve_and_continue": "승인 후 계속",
    "request_revision": "수정 요청",
    "retry_phase": "단계 다시 시도",
    "awaiting_direction_selection": "리서치 방향 선택 대기",
    "direction_selected": "방향 선택됨",
    "discovering": "탐색 중",
    "completed_discovery": "탐색 완료",
    "awaiting_research_plan_approval": "리서치 계획 승인 대기",
    "research_plan_approved": "리서치 계획 승인됨",
    "implementation_generation_started": "구현 자료 생성 중",
    "implementation_package_ready": "구현 자료 준비됨",
    "awaiting_user_results": "사용자 결과 대기",
    "research_results_submitted": "결과 제출됨",
    "research_results_analyzed": "결과 분석됨",
    "synthesis_generation_started": "종합 자료 생성 중",
    "research_synthesis_ready": "종합 자료 준비됨",
    "paper_materials_ready": "논문 자료 준비됨",
    "not_submitted": "제출되지 않음",
    "not_generated": "생성되지 않음",
    "available": "조회 가능",
    "none": "없음",
    "unbound": "연결되지 않음",
    "binary": "바이너리 파일(내용 미저장)",
    "too_large": "파일 크기 제한",
    "total_limit": "전체 크기 제한",
    "sensitive_content": "민감정보로 내용 제외",
    "changed_during_capture": "저장 중 파일 변경 감지",
    "metadata_only": "파일 정보만 저장",
    "complete": "전체 저장됨",
    "platform_unverified": "OS 안전 조회 미지원",
    "confirm_mode": "작업 유형 확정",
    "bind_developer_run": "개발 실행 연결",
    "bind_research_run": "리서치 실행 연결",
    "approve_developer_plan": "개발 계획 승인",
    "continue_developer": "개발 작업 계속",
    "select_research_direction": "리서치 방향 선택",
    "approve_research_plan": "리서치 계획 승인",
    "provide_research_results": "리서치 결과 제출",
    "continue_researcher": "리서치 작업 계속",
}

EVENTS = {
    "phase_started": "단계 시작",
    "phase_finished": "단계 종료",
    "phase_failed": "단계 실패",
    "agent_started": "에이전트 시작",
    "agent_finished": "에이전트 응답 완료",
    "agent_failed": "에이전트 실패",
    "tool_started": "도구 호출 시작",
    "tool_finished": "도구 호출 완료",
    "tool_failed": "도구 호출 실패",
    "file_observed": "파일 변경 관측",
    "validation_started": "검증 시작",
    "validation_finished": "검증 완료",
    "validation_failed": "검증 실패",
    "checkpoint_created": "단계별 승인 요청",
    "checkpoint_decided": "단계별 승인 결정",
    "plan_approved": "계획 승인",
    "snapshot_saved": "스냅샷 저장",
    "snapshot_failed": "스냅샷 저장 실패",
}


def tr(text: str) -> str:
    """Only known application messages; arbitrary content is preserved."""
    if not isinstance(text, str):
        return text
    if text in TEXT:
        return TEXT[text]
    if text.startswith("Observed Change comparison. "):
        return (
            "관측된 파일을 비교한 결과입니다. 에이전트가 변경했다고 단정하지 않습니다."
            + (
                " 파일 목록이 불완전하므로 누락된 파일의 생성·삭제 여부는 확인할 수 없습니다."
                if "incomplete" in text
                else ""
            )
        )
    if text.startswith("Unified Diff unavailable: "):
        reasons = text.removeprefix("Unified Diff unavailable: ").split(", ")
        return "변경 비교 불가: " + ", ".join(value(reason) for reason in reasons)
    return text


def value(text: object) -> str:
    raw = str(text or "—")
    return VALUES.get(raw, TEXT.get(raw, raw))


def event_name(kind: str) -> str:
    return EVENTS.get(kind, kind)


TEXT.update(
    {
        "Requested project, run, direction or artifact was not found.": "요청한 프로젝트·실행·방향 또는 결과물을 찾을 수 없습니다.",
        "This action is not currently allowed. Refresh the project and review its pending actions.": "현재 허용되지 않는 작업입니다. 새로고침하고 필요한 승인과 입력을 확인하세요.",
        "Previous execution is interrupted or its outcome is unknown. Recovery is read-only; retry requires a separately authorized workflow.": "이전 실행이 중단되었거나 결과를 확인할 수 없습니다. 기록은 조회만 가능하며 재시도에는 별도 승인이 필요합니다.",
        "Snapshot cannot be safely inspected or stored. No automatic recovery action was performed.": "스냅샷을 안전하게 조회하거나 저장할 수 없습니다. 자동 복구는 수행하지 않았습니다.",
        "Execution is busy or its public event storage is unavailable. Refresh and try again.": "실행 중이거나 실행 기록 저장소에 접근할 수 없습니다. 상태를 확인하고 새로고침하세요.",
        "Check provider settings, endpoint, model and credential configuration.": "제공자 설정에서 URL·모델·API Key를 확인하세요.",
        "Provider request failed. Check connection and provider settings.": "제공자 요청이 실패했습니다. 네트워크 연결과 제공자 설정을 확인하세요.",
        "Invalid input. Check required fields, artifact format, or a new export filename in an existing folder.": "입력이 올바르지 않습니다. 필수 항목과 결과물 형식을 확인하세요. 내보내기는 기존 폴더에 새 파일명을 지정해야 합니다.",
        "Operation cannot be completed in the current project or lane state. Check bindings and approvals.": "현재 상태에서는 작업을 완료할 수 없습니다. 실행 연결과 승인 상태를 확인하세요.",
        "Snapshot does not belong to this project's Developer run.": "이 프로젝트의 개발 실행에 속한 스냅샷이 아닙니다.",
        "Comparison must remain within one ordered execution attempt": "같은 실행 시도의 스냅샷을 시간순으로 비교해야 합니다.",
        "No Developer workspace is bound to this project.": "이 프로젝트에 연결된 개발 작업 폴더가 없습니다.",
        "Developer run was not found.": "개발 실행을 찾을 수 없습니다.",
        "This run has no saved workspace path.": "이 실행에는 저장된 작업 폴더 경로가 없습니다.",
        "Developer bootstrap service is not configured.": "리서치 자료로 개발을 시작하는 서비스가 구성되지 않았습니다.",
        "Confirm a Developer or Hybrid mode first.": "먼저 개발 에이전트 또는 통합 작업 유형을 승인하세요.",
        "Confirm a Researcher or Hybrid mode first.": "먼저 리서치 에이전트 또는 통합 작업 유형을 승인하세요.",
        "Workspace could not be inspected. Refresh and check that it is accessible.": "작업 폴더를 조회할 수 없습니다. 폴더 접근 권한을 확인하고 새로고침하세요.",
        "Current disk content. Sensitive lines are masked; this is not proof of creation by this run.": "현재 저장된 코드입니다. 민감한 내용은 가렸으며 이 실행이 파일을 생성했다는 증거는 아닙니다.",
        "File is unavailable or cannot be displayed as UTF-8 code.": "파일에 접근할 수 없거나 UTF-8 코드로 표시할 수 없습니다.",
        "Workspace folder does not exist.": "작업 폴더가 없습니다. 저장된 경로를 확인하세요.",
        "Workspace folder is unavailable.": "작업 폴더에 접근할 수 없습니다. 경로와 권한을 확인하세요.",
        "Linked run was not found.": "연결된 실행을 찾을 수 없습니다.",
        "No saved file exists at this workspace path.": "이 작업 폴더 경로에 저장된 파일이 없습니다.",
        "This workspace path is unavailable for public inspection.": "이 경로는 공개 파일 조회에 사용할 수 없습니다.",
        "This file type cannot be displayed as code.": "이 파일 형식은 코드로 표시할 수 없습니다.",
        "Connection successful": "연결에 성공했습니다.",
        "Provider returned no text response": "제공자가 텍스트 응답을 반환하지 않았습니다.",
        "Invalid configuration or missing credential": "설정이 올바르지 않거나 API Key가 없습니다.",
        "Connection failed; check endpoint, credential, model and Responses API support": "연결에 실패했습니다. URL·API Key·모델과 Responses API 지원 여부를 확인하세요.",
        "Unified Diff of public text; causation is unconfirmed.": "공개 가능한 텍스트의 변경 비교입니다. 변경 원인은 확정하지 않습니다.",
        "\nNo public file changes were observed in this comparison.": "\n이번 비교에서 공개 가능한 파일 변경이 관측되지 않았습니다.",
        "\nPossible conflicting rules: ": "\n충돌할 수 있는 규칙: ",
        "\nWhen both apply, neither is injected. Review and explicitly disable one.": "\n두 규칙이 함께 적용되면 어느 규칙도 전달하지 않습니다. 검토 후 하나를 직접 사용 중지하세요.",
        "\nObserved usage / post-application outcomes:\n": "\n관측된 사용 / 적용 이후 결과:\n",
    }
)
VALUES.update(
    {
        "passed": "통과",
        "unknown": "확인 불가",
        "timeout": "시간 초과",
        "request_changes": "수정 요청",
        "incomplete inventory; absence does not prove creation or deletion": "파일 목록이 불완전하여 생성·삭제를 확인할 수 없음",
        "not available": "확인 불가",
        "not selected": "선택되지 않음",
    }
)
EVENTS.update(
    {
        "agent_completed": "에이전트 응답 완료",
        "tool_completed": "도구 호출 완료",
        "observation_unavailable": "파일 관측 불가",
        "repair_started": "수정 시도 시작",
    }
)

VALUES.update(
    {
        "bound": "연결됨",
        "not_available": "조회 불가",
        "not_started": "시작 전",
        "stale": "이전 버전",
        "accepted": "승인됨",
        "blocked": "차단됨",
        "stop_project": "프로젝트 중지",
    }
)


def install_qt_translation(app) -> None:
    """Keep Qt's built-in dialogs and message-box buttons in Korean too."""
    if getattr(app, "_korean_translation", None) is not None:
        return
    from pathlib import Path

    from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator

    from ai_agent_project.desktop_app.resources import resource_path

    class KoreanQtTranslator(QTranslator):
        def translate(
            self,
            context: str,
            source_text: str,
            disambiguation: str | None = None,
            n: int = -1,
        ) -> str:
            supplemental = {
                "Look in:": "찾을 위치:",
                "&Look in:": "찾을 위치:",
                "Files of type:": "폴더 유형:",
                "Files of &type:": "폴더 유형:",
                "Folder": "폴더",
                "File Folder": "폴더",
                "Directory": "폴더",
            }
            if (
                context in {"QFileDialog", "QFileSystemModel"}
                and source_text in supplemental
            ):
                return supplemental[source_text]
            return (
                super().translate(context, source_text, disambiguation, n)
                or source_text
            )

    translator = KoreanQtTranslator(app)
    locations = (
        resource_path("qtbase_ko.qm"),
        Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath))
        / "qtbase_ko.qm",
    )
    for path in locations:
        if translator.load(str(path)):
            app.installTranslator(translator)
            app._korean_translation = translator
            break
    QLocale.setDefault(QLocale("ko_KR"))


VALUES.update(
    {
        "tool_failed": "도구 실행 실패",
        "execution_failed": "실행 실패",
        "observation_unavailable": "파일 관측 불가",
        "candidate": "개선 후보",
        "rule": "규칙",
        "validation_failed": "검증 실패",
        "planning_quality": "계획 품질",
        "tool_usage": "도구 사용",
        "error_handling": "오류 처리",
        "validation_quality": "검증 품질",
        "research_quality": "리서치 품질",
        "workflow": "작업 흐름",
        "communication": "의사소통",
    }
)

TEXT.update(
    {
        "Developer specification": "개발 요구사항",
        "Developer project specification": "개발 프로젝트 요구사항",
        "Developer implementation plan": "개발 구현 계획",
        "Developer plan revision history": "개발 계획 수정 기록",
        "Developer execution state": "개발 실행 상태",
        "Developer upgrade context": "기존 코드 분석 자료",
        "Research request": "리서치 요청",
        "Research discovery report": "리서치 탐색 보고서",
        "Research plan revision history": "리서치 계획 수정 기록",
        "Research implementation plan": "리서치 구현 계획",
        "Research implementation package": "리서치 구현 자료",
        "Research result submission": "리서치 결과 제출 내용",
        "Research result analysis": "리서치 결과 분석",
        "Research result synthesis": "리서치 종합 결과",
        "Research paper materials": "리서치 논문 자료",
    }
)
VALUES.update(
    {
        "planning": "계획 수립",
        "prompt_strategy": "요청 전략",
        "tool_selection": "도구 선택",
        "validation": "검증",
        "error_recovery": "오류 복구",
        "research_strategy": "리서치 전략",
        "evidence_quality": "근거 품질",
        "project_specific": "프로젝트별 지침",
        "draft": "초안",
    }
)


def artifact_title(title: str) -> str:
    """Translate only the app-owned wrapper around artifact contents."""
    import re

    for prefix, korean in (
        ("Developer project plan revision v", "개발 계획 수정 버전 "),
        ("Developer project plan v", "개발 프로젝트 계획 버전 "),
        ("Research plan revision v", "리서치 계획 수정 버전 "),
        ("Research plan v", "리서치 계획 버전 "),
    ):
        if title.startswith(prefix) and re.fullmatch(r"\d+", title[len(prefix) :]):
            return korean + title[len(prefix) :]
    if title.startswith("Generated research file: "):
        return "생성된 리서치 파일: " + title.removeprefix("Generated research file: ")
    if title.startswith("Selected research direction: "):
        return "선택한 리서치 방향: " + title.removeprefix(
            "Selected research direction: "
        )
    return tr(title)


TEXT.update(
    {
        "Cannot read improvement records.": "개선 기록을 읽을 수 없습니다. 저장소 접근 권한을 확인하세요.",
        "Cannot persist improvement records.": "개선 기록을 저장할 수 없습니다. 디스크 공간과 접근 권한을 확인하세요.",
        "Improvement record not found.": "개선 기록을 찾을 수 없습니다.",
        "Unknown evidence domain.": "지원하지 않는 근거 유형입니다.",
        "Source run not found.": "원본 실행을 찾을 수 없습니다.",
        "Improvement evaluator is not configured.": "개선 평가 기능이 구성되지 않았습니다.",
        "Cannot read source run.": "원본 실행 기록을 읽을 수 없습니다.",
        "Evaluation failed or returned unsafe guidance. No improvement was activated.": "평가가 실패했거나 안전하지 않은 지침이 반환되었습니다. 개선 규칙은 활성화하지 않았습니다.",
        "Only pending candidates can be approved.": "검토 대기 상태인 후보만 승인할 수 있습니다.",
        "An identical rule already exists in this scope.": "이 적용 범위에 동일한 규칙이 이미 있습니다.",
        "Only pending candidates can be rejected.": "검토 대기 상태인 후보만 거절할 수 있습니다.",
        "Invalid or sensitive feedback. Do not include credentials.": "의견이 올바르지 않거나 민감정보가 포함되어 있습니다. API Key 등 자격 증명을 제거하세요.",
        "Invalid or protected rule scope/content.": "규칙의 적용 범위나 내용이 올바르지 않거나 보호 정책에 위배됩니다.",
        "Stored guidance violates protected constraints. Disable it before proceeding.": "저장된 지침이 보호 정책에 위배됩니다. 진행 전에 해당 규칙을 사용 중지하세요.",
        "Research results": "리서치 결과",
        "Research synthesis": "리서치 종합 자료",
    }
)
VALUES.update(
    {
        "Provided": "제출됨",
        "Not provided": "제출되지 않음",
        "Materials available": "논문 자료 준비됨",
        "Synthesis available": "종합 자료 준비됨",
        "Not generated": "생성되지 않음",
        "specification": "요구사항",
        "project_specification": "프로젝트 요구사항",
        "implementation_plan": "구현 계획",
        "project_plan": "프로젝트 계획",
        "project_plan_revision": "프로젝트 계획 수정",
        "plan_revision_history": "계획 수정 기록",
        "execution_state": "실행 상태",
        "upgrade_context": "기존 코드 분석 자료",
        "research_request": "리서치 요청",
        "discovery_report": "탐색 보고서",
        "selected_direction": "선택한 방향",
        "research_plan": "리서치 계획",
        "research_plan_revision": "리서치 계획 수정",
        "research_plan_history": "리서치 계획 수정 기록",
        "research_implementation_plan": "리서치 구현 계획",
        "research_implementation_package": "리서치 구현 자료",
        "research_generated_file": "리서치 생성 파일",
        "research_results": "리서치 결과",
        "research_result_analysis": "리서치 결과 분석",
        "research_synthesis": "리서치 종합 자료",
        "paper_materials": "논문 자료",
        "developer_bootstrap_context": "개발 참고 자료",
    }
)
