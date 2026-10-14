"""Real persisted workflow fixtures, no production provider calls."""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_agent_project.agent.research import WorkMode
from ai_agent_project.improvement.file_store import FileImprovementStore
from ai_agent_project.improvement.models import CandidateProposal, EvaluationProposal
from ai_agent_project.improvement.service import ImprovementService

_spec = importlib.util.spec_from_file_location(
    "improvement_seed", Path(__file__).parents[1] / "desktop" / "conftest.py"
)
_seed = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _seed
_spec.loader.exec_module(_seed)
setup = _seed.setup


class Evaluator:
    def __init__(self):
        self.calls = []
        self.rule = "Inspect public interfaces before producing implementation patches."
        self.failure = False

    def evaluate(self, evidence):
        self.calls.append(evidence)
        if self.failure:
            raise RuntimeError("private provider body must not escape")
        return EvaluationProposal(
            strengths=("A persisted human checkpoint exists.",),
            weaknesses=("No completed outcome is recorded yet.",),
            confidence=0.5,
            improvement_warranted=True,
            candidates=(
                CandidateProposal(
                    category="planning",
                    title="Inspect interfaces",
                    proposed_rule=self.rule,
                    rationale="Conservative planning practice; limited evidence.",
                    confidence=0.5,
                ),
            ),
        )


@pytest.fixture
def env(setup, tmp_path):
    evaluator = Evaluator()
    service = ImprovementService(
        FileImprovementStore(tmp_path / "improvements"),
        developer_reader=setup.developers,
        researcher_reader=setup.researchers,
        projects=setup.sessions,
        evaluator_factory=lambda: evaluator,
    )
    setup.desktop._improvements = service
    developer = setup.sessions.get_project(
        setup.ids[WorkMode.DEVELOPER]
    ).project.developer_run_id
    researcher = setup.sessions.get_project(
        setup.ids[WorkMode.RESEARCHER]
    ).project.research_run_id
    return SimpleNamespace(
        service=service,
        evaluator=evaluator,
        seed=setup,
        developer=developer,
        researcher=researcher,
    )
