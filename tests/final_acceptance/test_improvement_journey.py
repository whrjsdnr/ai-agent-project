import json

import pytest

from ai_agent_project.improvement.file_store import FileImprovementStore
from ai_agent_project.improvement.service import ImprovementService


@pytest.mark.parametrize("domain", ["developer", "researcher"])
def test_actual_guidance_approval_feedback_disable_restart(
    env, monkeypatch, tmp_path, domain, actual_provider_operation
):
    _, operation, calls = actual_provider_operation(env, monkeypatch, tmp_path, domain)
    service = env.service
    run_id = getattr(env, domain)
    service.evaluate(domain, run_id)
    candidate = service.list_candidates()[0]
    operation()
    assert candidate.proposed_rule not in json.dumps(calls[-1])
    rule = service.approve_candidate(candidate.candidate_id)
    operation()
    assert rule.rule_text in json.dumps(calls[-1])
    before = len(env.evaluator.calls), len(calls)
    service.submit_feedback(domain, run_id, "helpful", "Interface review was useful")
    assert (len(env.evaluator.calls), len(calls)) == before
    service.set_enabled(rule.rule_id, False)
    operation()
    assert rule.rule_text not in json.dumps(calls[-1])
    fresh = ImprovementService(FileImprovementStore(service.store.root))
    assert fresh.overview() == service.overview()
    assert fresh.overview().rules[0] == rule


@pytest.mark.parametrize("domain", ["developer", "researcher"])
def test_actual_provider_excludes_other_project(
    env, monkeypatch, tmp_path, domain, actual_provider_operation
):
    _, operation, calls = actual_provider_operation(env, monkeypatch, tmp_path, domain)
    other = "researcher" if domain == "developer" else "developer"
    env.service.evaluate(other, getattr(env, other))
    rule = env.service.approve_candidate(
        env.service.list_candidates()[0].candidate_id, "project"
    )
    assert rule.domain is None
    operation()
    assert rule.rule_text not in json.dumps(calls[-1])
    assert not env.service.overview().applications
