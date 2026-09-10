from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_agent_project.api.improvements import register_improvement_routes


def test_api_explicit_lifecycle(env):
    app = FastAPI()
    register_improvement_routes(app, env.service)
    with TestClient(app) as client:
        prefix = "/v1/improvements"
        before = env.seed.snapshot()
        assert client.get(prefix + "/candidates").json() == []
        assert client.get(prefix + "/rules").json() == []
        assert not env.evaluator.calls and env.seed.snapshot() == before
        result = client.post(
            prefix + "/evaluations",
            json={"domain": "developer", "run_id": env.developer},
        )
        assert result.status_code == 200
        candidate = client.get(prefix + "/candidates").json()[0]
        assert candidate["status"] == "pending" and not env.service.list_rules()
        result = client.post(
            prefix + f"/candidates/{candidate['candidate_id']}/approve", json={}
        )
        assert result.status_code == 200
        rule = result.json()
        assert rule["approved_by"] == "user" and len(env.evaluator.calls) == 1
        assert (
            client.post(prefix + f"/rules/{rule['rule_id']}/disable").status_code == 200
        )
        assert not env.service.get_rule(rule["rule_id"]).enabled
        assert (
            client.post(prefix + f"/rules/{rule['rule_id']}/enable").status_code == 200
        )
        assert (
            client.get(prefix + f"/rules/{rule['rule_id']}/impact").json()[
                "times_applied"
            ]
            == 0
        )
        assert (
            client.post(
                prefix + "/feedback",
                json={
                    "target_type": "developer",
                    "target_id": env.developer,
                    "rating": "helpful",
                },
            ).status_code
            == 200
        )
        assert len(env.evaluator.calls) == 1
        assert (
            client.post(
                prefix + "/evaluations",
                json={"domain": "researcher", "run_id": env.researcher},
            ).status_code
            == 200
        )
        candidate = env.service.list_candidates()[-1]
        assert (
            client.post(
                prefix + f"/candidates/{candidate.candidate_id}/reject"
            ).status_code
            == 200
        )
        assert len(env.service.list_rules()) == 1


def test_api_rejects_authority_fields_and_sanitizes_failure(env):
    app = FastAPI()
    register_improvement_routes(app, env.service)
    with TestClient(app) as client:
        result = client.post(
            "/v1/improvements/evaluations",
            json={"domain": "developer", "run_id": env.developer, "status": "approved"},
        )
        assert result.status_code == 422 and not env.evaluator.calls
        env.evaluator.failure = True
        result = client.post(
            "/v1/improvements/evaluations",
            json={"domain": "developer", "run_id": env.developer},
        )
        assert result.status_code == 400
        assert "private provider" not in result.text
        assert not env.service.list_candidates()
