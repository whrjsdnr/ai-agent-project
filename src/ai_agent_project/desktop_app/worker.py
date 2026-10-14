"""One callable per worker; results cross to the GUI exclusively via signals."""

from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from ai_agent_project.desktop.errors import DesktopError


class WorkerSignals(QObject):
    succeeded = Signal(object)
    failed = Signal(str)


class OperationWorker(QRunnable):
    def __init__(self, operation: Callable[[], object]) -> None:
        super().__init__()
        self.operation = operation
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self.operation()
        except DesktopError as error:
            self.signals.failed.emit(error.message)
        except Exception:  # noqa: BLE001 -- UI boundary never exposes raw errors
            self.signals.failed.emit(
                "Operation failed. Check your input and settings, then refresh and try again."
            )
        else:
            self.signals.succeeded.emit(result)
        finally:
            self.operation = lambda: None
