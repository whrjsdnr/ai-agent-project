"""Narrow explicit improvement endpoints; desktop does not import this adapter."""

from fastapi import FastAPI, HTTPException
from pydantic import Field

from ai_agent_project.improvement.errors import ImprovementError
from ai_agent_project.improvement.models import Domain, Model, Scope
from ai_agent_project.improvement.service import ImprovementService
from ai_agent_project.llm.runtime import provider_client_scope


class EvaluationRequest(Model):
    domain: Domain
    run_id: str = Field(min_length=1, max_length=100)


class ApprovalRequest(Model):
    scope: Scope | None = None


class FeedbackRequest(Model):
    target_type: str = Field(max_length=20)
    target_id: str = Field(min_length=1, max_length=100)
    rating: str = Field(max_length=20)
    text: str = Field(default="", max_length=500, repr=False)


def register_improvement_routes(router: FastAPI, service: ImprovementService) -> None:

    def invoke(operation):
        try:
            with provider_client_scope():
                return operation()
        except ImprovementError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        except Exception:  # noqa: BLE001 -- fixed error never returns input/provider bodies
            raise HTTPException(
                status_code=500, detail="Improvement operation failed."
            ) from None

    @router.get("/v1/improvements/candidates")
    def candidates():
        return invoke(service.list_candidates)

    @router.get("/v1/improvements/rules")
    def rules():
        return invoke(service.list_rules)

    @router.get("/v1/improvements/evaluations")
    def evaluations():
        return invoke(lambda: service.overview().evaluations)

    @router.post("/v1/improvements/evaluations")
    def evaluate(request: EvaluationRequest):
        return invoke(lambda: service.evaluate(request.domain, request.run_id))

    @router.post("/v1/improvements/candidates/{candidate_id}/approve")
    def approve(candidate_id: str, request: ApprovalRequest | None = None):
        return invoke(
            lambda: service.approve_candidate(
                candidate_id, request.scope if request else None
            )
        )

    @router.post("/v1/improvements/candidates/{candidate_id}/reject")
    def reject(candidate_id: str):
        invoke(lambda: service.reject_candidate(candidate_id))
        return {"status": "rejected"}

    @router.post("/v1/improvements/rules/{rule_id}/enable")
    def enable(rule_id: str):
        invoke(lambda: service.set_enabled(rule_id, True))
        return {"status": "enabled"}

    @router.post("/v1/improvements/rules/{rule_id}/disable")
    def disable(rule_id: str):
        invoke(lambda: service.set_enabled(rule_id, False))
        return {"status": "disabled"}

    @router.get("/v1/improvements/rules/{rule_id}/impact")
    def impact(rule_id: str):
        return invoke(lambda: service.impact(rule_id))

    @router.post("/v1/improvements/feedback")
    def feedback(request: FeedbackRequest):
        return invoke(
            lambda: service.submit_feedback(
                request.target_type, request.target_id, request.rating, request.text
            )
        )
