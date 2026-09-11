"""Small safe boundary for expected application failures.

Unrecognized exceptions propagate so programming defects remain visible. External
error strings are never copied: they may contain prompts, credentials or paths.
"""

from collections.abc import Callable
from enum import StrEnum
from functools import wraps

from openai import OpenAIError
from pydantic import ValidationError

from ai_agent_project.agent.hybrid_coordination_application import (
    HybridCoordinationError,
)
from ai_agent_project.agent.project_action_application import (
    ProjectActionError,
    ProjectActionNotAllowedError,
)
from ai_agent_project.agent.project_application import (
    ProjectRunError,
    ProjectRunNotFoundError,
)
from ai_agent_project.agent.project_artifact_application import (
    ProjectArtifactError,
    ProjectArtifactNotFoundError,
)
from ai_agent_project.agent.project_artifact_export import ProjectArtifactExportError
from ai_agent_project.agent.project_artifact_rendering import (
    ProjectArtifactRenderingError,
)
from ai_agent_project.agent.project_developer_bootstrap_application import (
    ProjectDeveloperBootstrapError,
)
from ai_agent_project.agent.project_handoff_application import ProjectHandoffError
from ai_agent_project.agent.project_handoff_consumption import (
    ProjectHandoffConsumptionError,
)
from ai_agent_project.agent.project_session_application import (
    ProjectSessionError,
    ProjectSessionNotFoundError,
)
from ai_agent_project.agent.research_application import (
    ResearchDirectionNotFoundError,
    ResearchRunError,
    ResearchRunNotFoundError,
)
from ai_agent_project.improvement.errors import ImprovementError
from ai_agent_project.llm.config import ProviderConfigError
from ai_agent_project.llm.providers.openai_planner import ImplementationPlanningError
from ai_agent_project.llm.providers.openai_project_mode_proposer import (
    ProjectModeProposalError,
)
from ai_agent_project.llm.providers.openai_project_planner import ProjectPlanningError
from ai_agent_project.llm.providers.openai_research_implementation import (
    ResearchImplementationGenerationError,
)
from ai_agent_project.llm.providers.openai_research_paper_materials import (
    ResearchPaperMaterialsError,
)
from ai_agent_project.llm.providers.openai_research_plan_generator import (
    ResearchPlanGenerationError,
)
from ai_agent_project.llm.providers.openai_research_result_analyzer import (
    ResearchResultAnalysisError,
)
from ai_agent_project.llm.providers.openai_research_result_synthesizer import (
    ResearchResultSynthesisError,
)


class DesktopErrorCode(StrEnum):
    NOT_FOUND = "NOT_FOUND"
    INVALID_STATE = "INVALID_STATE"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    ACTION_NOT_ALLOWED = "ACTION_NOT_ALLOWED"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class DesktopError(Exception):
    def __init__(self, code: DesktopErrorCode, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def desktop_boundary[**P, R](operation: Callable[P, R]) -> Callable[P, R]:
    @wraps(operation)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return operation(*args, **kwargs)
        except (
            ProjectSessionNotFoundError,
            ProjectRunNotFoundError,
            ResearchRunNotFoundError,
            ResearchDirectionNotFoundError,
            ProjectArtifactNotFoundError,
        ):
            raise DesktopError(
                DesktopErrorCode.NOT_FOUND,
                "Requested project, run, direction or artifact was not found.",
            ) from None
        except ProjectActionNotAllowedError:
            raise DesktopError(
                DesktopErrorCode.ACTION_NOT_ALLOWED,
                "This action is not currently allowed. Refresh the project and review its pending actions.",
            ) from None
        except ImprovementError as error:
            raise DesktopError(DesktopErrorCode.INVALID_STATE, str(error)) from None
        except ProviderConfigError:
            raise DesktopError(
                DesktopErrorCode.CONFIGURATION_ERROR,
                "Check provider settings, endpoint, model and credential configuration.",
            ) from None
        except (
            OpenAIError,
            ProjectModeProposalError,
            ProjectPlanningError,
            ImplementationPlanningError,
            ResearchPlanGenerationError,
            ResearchImplementationGenerationError,
            ResearchResultAnalysisError,
            ResearchResultSynthesisError,
            ResearchPaperMaterialsError,
        ):
            raise DesktopError(
                DesktopErrorCode.PROVIDER_ERROR,
                "Provider request failed. Check connection and provider settings.",
            ) from None
        except (
            ValidationError,
            ProjectArtifactRenderingError,
            ProjectArtifactExportError,
        ):
            raise DesktopError(
                DesktopErrorCode.VALIDATION_ERROR,
                "Invalid input. Check required fields, artifact format, or a new export filename in an existing folder.",
            ) from None
        except (
            ProjectSessionError,
            ProjectRunError,
            ResearchRunError,
            ProjectActionError,
            ProjectArtifactError,
            ProjectHandoffError,
            ProjectDeveloperBootstrapError,
            ProjectHandoffConsumptionError,
            HybridCoordinationError,
        ):
            raise DesktopError(
                DesktopErrorCode.INVALID_STATE,
                "Operation cannot be completed in the current project or lane state. Check bindings and approvals.",
            ) from None

    return wrapped
