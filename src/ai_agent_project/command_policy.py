"""Shared safe command policy for planning and workspace command execution."""

import shlex
from pathlib import Path

SHELL_OPERATORS = ("&&", "||", ";", ">>", ">", "<", "|", "$(", "`")
DANGEROUS_COMMANDS = frozenset(
    {
        "sudo",
        "su",
        "rm",
        "mv",
        "cp",
        "chmod",
        "chown",
        "kill",
        "pkill",
        "curl",
        "wget",
        "ssh",
        "scp",
        "docker",
        "apt",
        "apt-get",
        "pip",
        "npm",
    }
)
DANGEROUS_GIT_SUBCOMMANDS = frozenset(
    {"reset", "clean", "checkout", "restore", "commit", "push", "pull"}
)
SAFE_COMMAND_FORMS = (
    "uv run pytest",
    "uv run pytest <relative path>",
    "uv run ruff check .",
    "uv run ruff check <relative path>",
    "uv run ruff format --check .",
    "git status",
    "git status --short",
    "git diff",
    "git diff --check",
    "git log",
    "git log --oneline",
    "python --version",
    "uv --version",
)


class CommandPolicyError(ValueError):
    """Raised when a command falls outside the shared safe command policy."""


def parse_safe_command(command: str) -> list[str]:
    """Parse and validate one allowlisted command without a shell."""
    if any(operator in command for operator in SHELL_OPERATORS):
        raise CommandPolicyError("Shell operators are not allowed")

    try:
        argv = shlex.split(command)
    except ValueError as error:
        raise CommandPolicyError(f"Invalid command syntax: {error}") from error

    if not argv:
        raise CommandPolicyError("Command must not be empty")
    _reject_dangerous_command(argv)
    _validate_allowlist(argv)
    return argv


def validation_command_instructions() -> str:
    """Render the exact command policy for an implementation-planning prompt."""
    allowed = "\n".join(f"- {command}" for command in SAFE_COMMAND_FORMS)
    return f"""Validation commands may use only these safe command forms:
{allowed}

When validation is needed and no narrower command is justified, use `uv run pytest`.
Do not emit `pytest`, `pytest -q`, package managers, arbitrary commands, shell
operators, redirects, command substitutions, or command chaining.
"""


def _reject_dangerous_command(argv: list[str]) -> None:
    """Reject explicitly dangerous executable and Git subcommand forms."""
    if argv[0] in DANGEROUS_COMMANDS:
        raise CommandPolicyError(f"Command is not allowed: {argv[0]}")
    if len(argv) >= 2 and argv[0] == "git" and argv[1] in DANGEROUS_GIT_SUBCOMMANDS:
        raise CommandPolicyError(f"Git command is not allowed: git {argv[1]}")


def _validate_allowlist(argv: list[str]) -> None:
    """Allow only fixed command forms and safe relative-path variants."""
    if argv in (
        ["git", "status"],
        ["git", "status", "--short"],
        ["git", "diff"],
        ["git", "diff", "--check"],
        ["git", "log"],
        ["git", "log", "--oneline"],
        ["python", "--version"],
        ["uv", "--version"],
        ["uv", "run", "pytest"],
        ["uv", "run", "ruff", "check", "."],
        ["uv", "run", "ruff", "format", "--check", "."],
    ):
        return

    if _is_relative_path_variant(argv, ["uv", "run", "pytest"]):
        return
    if _is_relative_path_variant(argv, ["uv", "run", "ruff", "check"]):
        return

    raise CommandPolicyError("Command is not in the allowlist")


def _is_relative_path_variant(argv: list[str], prefix: list[str]) -> bool:
    """Return whether argv is one allowed command prefix plus one safe path."""
    if argv[: len(prefix)] != prefix or len(argv) != len(prefix) + 1:
        return False

    path = Path(argv[-1])
    if path.is_absolute() or ".." in path.parts:
        raise CommandPolicyError("Command paths must be relative to the workspace")
    return True
