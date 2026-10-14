"""Public execution content policy: no raw arguments or internal transcripts."""

import re
from pathlib import Path

from ai_agent_project.agent.workspace import is_workspace_ignored_path
from ai_agent_project.command_policy import parse_safe_command

MAX_LOG_CHARS = 8_000
PRIVATE_PARTS = {
    ".aws",
    ".ssh",
    ".codex",
    ".agents",
    "developers",
    "researchers",
    "project-runs",
    "research-runs",
    "projects",
    "handoffs",
    "improvements",
    "settings",
    "execution-events",
    "execution-locks",
}


def public_relative_path(value: str) -> Path:
    path = Path(value)
    if (
        not value
        or path.is_absolute()
        or "\\" in value
        or ":" in value
        or ".." in path.parts
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError("Private or unsafe path")
    for part in path.parts:
        name = part.rstrip(" .").casefold()
        if (
            name.startswith(".")
            or name in PRIVATE_PARTS
            or any(
                word in name
                for word in (
                    "secret",
                    "credential",
                    "token",
                    "password",
                    "private_key",
                    "id_rsa",
                    "id_ed25519",
                    "api_key",
                    "apikey",
                    "api-key",
                )
            )
        ):
            raise ValueError("Private or unsafe path")
    if is_workspace_ignored_path(path) or path.suffix.casefold() in {
        ".pem",
        ".key",
        ".p12",
        ".pfx",
        ".crt",
        ".cer",
        ".der",
        ".jks",
        ".keystore",
    }:
        raise ValueError("Private or unsafe path")
    return path


def sanitize_text(content: str, *, secrets: tuple[str, ...] = ()) -> str:
    for secret in sorted(set(secrets), key=len, reverse=True):
        if secret:
            content = content.replace(secret, "[REDACTED]")
    content = re.sub(
        r"-----BEGIN [^-]*PRIVATE KEY-----.*?(?:-----END [^-]*PRIVATE KEY-----|\Z)",
        "[REDACTED PRIVATE KEY]",
        content,
        flags=re.DOTALL,
    )
    # Withhold transcript-shaped output as a whole, including multi-line JSON.
    if re.search(
        r"(?i)\b(?:provider_context|tool_calls|tool_results|agent_run|agent_state|messages|system_prompt|user_message)\b|\"role\"\s*:\s*\"(?:system|user|assistant|tool)\"",
        content,
    ):
        return "[REDACTED internal data]"
    if re.search(
        r"(?im)(?:api[_-]?key|password|secret|credential|token)[\"']?\s*[:=]\s*(?:\n|[\"']{3})",
        content,
    ):
        return "[REDACTED multiline sensitive data]"
    content = re.sub(
        r"(?im)^.*(?:api[_-]?key|password|passwd|secret|credential|token|authorization|bearer|os\.environ|os\.getenv|process\.env|\$\{[A-Z_][A-Z_0-9]*\}).*$",
        "[REDACTED sensitive line]",
        content,
    )
    content = re.sub(r"(?m)^(\s*[A-Z][A-Z_0-9]*\s*=).*$", r"\1 [REDACTED]", content)
    content = re.sub(
        r"\b(?:sk-[A-Za-z0-9_-]+|AKIA[A-Z0-9]{16}|gh[pousr]_[A-Za-z0-9_]+)\b",
        "[REDACTED]",
        content,
    )
    content = re.sub(r"(?i)(https?://)[^\s/@]+:[^\s/@]+@", r"\1[REDACTED]@", content)
    return content


def public_log(content: str, *, secrets: tuple[str, ...], workspace: Path) -> str:
    # Sanitize BEFORE truncation so split credentials cannot survive truncation.
    content = sanitize_text(content, secrets=secrets)
    content = content.replace(str(workspace), "<workspace>")
    content = re.sub(
        r"(?<![\w<])(?:[A-Za-z]:[\\/]|/)[^\s\"'<>]+", "[REDACTED path]", content
    )
    content = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]|[\x00-\x08\x0b-\x1f\x7f]", "", content)
    if len(content) > MAX_LOG_CHARS:
        return content[:MAX_LOG_CHARS] + "\n[truncated]"
    return content


def public_command(value: str) -> str:
    argv = parse_safe_command(value)
    if argv[:3] == ["uv", "run", "pytest"] and len(argv) == 4:
        public_relative_path(argv[3].split("::", 1)[0])
    if argv[:4] == ["uv", "run", "ruff", "check"] and len(argv) == 5 and argv[4] != ".":
        public_relative_path(argv[4])
    return " ".join(argv)
