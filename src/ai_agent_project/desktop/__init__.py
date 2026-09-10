"""Direct local desktop application facade. No Qt or HTTP server required."""

from ai_agent_project.desktop.errors import DesktopError, DesktopErrorCode
from ai_agent_project.desktop.service import DesktopService

__all__ = ["DesktopError", "DesktopErrorCode", "DesktopService"]
