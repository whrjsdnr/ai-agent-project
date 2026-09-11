"""Tests for immutable pre-execution project plan review history."""

import pytest
from pydantic import ValidationError

from ai_agent_project.agent.plan import ImplementationPlan
from ai_agent_project.agent.plan_revision import (
    PlanReviewStatus,
    PlanRevisionState,
)
from ai_agent_project.agent.project import ProjectPhase, ProjectPlan


def make_plan(title: str = "Initial phase") -> ProjectPlan:
    implementation_plan = ImplementationPlan.model_validate(
        {
            "tasks": [
                {
                    "id": "TASK-001",
                    "title": "Build",
                    "description": "Build feature.",
                    "requirement_ids": ["REQ-001"],
                }
            ]
        }
    )
    return ProjectPlan(
        project_title="Demo",
        phases=(
            ProjectPhase(
                id="PHASE-001",
                title=title,
                objective="Build feature.",
                requirement_ids=("REQ-001",),
                task_ids=("TASK-001",),
            ),
        ),
        implementation_plan=implementation_plan,
    )


def test_initial_plan_revision_is_version_one_and_awaits_approval() -> None:
    state = PlanRevisionState.from_plan(make_plan())

    assert state.active_version == 1
    assert state.status is PlanReviewStatus.AWAITING_APPROVAL
    assert state.revisions[0].feedback is None
    assert state.active_plan == state.revisions[0].plan
    with pytest.raises(ValidationError):
        state.active_version = 2  # type: ignore[misc]


def test_revisions_preserve_history_and_require_nonblank_feedback() -> None:
    initial = PlanRevisionState.from_plan(make_plan())
    second_plan = make_plan("Clear responsibilities")
    revised = initial.revise(second_plan, " Clarify responsibilities. ")
    third = revised.revise(make_plan("Validation first"), "Move tests earlier.")

    assert initial.active_version == 1
    assert revised.active_version == 2
    assert revised.revisions[0].plan == initial.active_plan
    assert revised.revisions[1].feedback == "Clarify responsibilities."
    assert third.active_version == 3
    assert tuple(item.version for item in third.revisions) == (1, 2, 3)
    with pytest.raises(ValueError, match="must not be blank"):
        initial.revise(second_plan, " ")


def test_revisions_cannot_change_tasks_or_follow_approval() -> None:
    initial = PlanRevisionState.from_plan(make_plan())
    changed_implementation = make_plan().model_copy(
        update={
            "implementation_plan": initial.active_plan.implementation_plan.model_copy(
                update={"summary": "Changed implementation"}
            )
        }
    )
    with pytest.raises(ValueError, match="preserve"):
        initial.revise(changed_implementation, "Change tasks")

    approved = initial.approve()
    assert approved.status is PlanReviewStatus.APPROVED
    with pytest.raises(ValueError, match="already approved"):
        approved.approve()
    with pytest.raises(ValueError, match="approved"):
        approved.revise(make_plan("Later"), "Later revision")
