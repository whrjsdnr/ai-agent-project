"""User-level provider settings, independent of all workflow persistence.

Per-field precedence: explicit runtime fields > saved fields > environment > defaults.
Credentials: explicit runtime key > OPENAI_API_KEY; never read keys from saved JSON.
.env loading remains the launcher's responsibility (e.g. uv run --env-file ...).
"""

import json
import math
import os
from collections.abc import Mapping
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
)

from ai_agent_project.paths import runtime_paths

DEFAULT_MODEL = "gpt-5-mini"
DEFAULT_BASE_URL = "https://api.openai.com/v1"


class ProviderConfigError(ValueError):
    """Safe configuration error: never include supplied values or file contents."""


class ProviderConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    provider_type: Literal["openai-compatible"] = "openai-compatible"
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout_seconds: float = 90.0
    api_key: SecretStr | None = Field(default=None, exclude=True, repr=False)

    @field_validator("model")
    @classmethod
    def nonblank_model(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Model must not be blank")
        return value.strip()

    @field_validator("base_url")
    @classmethod
    def valid_url(cls, value: str) -> str:
        try:
            parsed = urlsplit(value)
            valid = (
                value == value.strip()
                and not any(c.isspace() for c in value)
                and parsed.scheme in {"http", "https"}
                and bool(parsed.hostname)
                and parsed.username is None
                and parsed.password is None
                and not parsed.query
                and not parsed.fragment
            )
            _ = parsed.port
        except ValueError:
            valid = False
        if not valid:
            raise ValueError(
                "Base URL must be an HTTP(S) URL without credentials, query or fragment"
            )
        return value

    @field_validator("timeout_seconds")
    @classmethod
    def positive_timeout(cls, value: float) -> float:
        if not math.isfinite(value) or value <= 0:
            raise ValueError("Timeout must be finite and positive")
        return value

    @field_validator("api_key")
    @classmethod
    def nonblank_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and not value.get_secret_value().strip():
            raise ValueError("Explicit API key must not be blank")
        return value


def default_provider_config_path() -> Path:
    return runtime_paths().config / "llm.json"


class ConnectionTestResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    success: bool
    message: str


class ProviderConfigService:
    """Desktop-callable settings, resolution and isolated connection testing."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else default_provider_config_path()

    def load(self) -> ProviderConfig | None:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except (OSError, UnicodeError):
            raise ProviderConfigError("Cannot read saved LLM configuration") from None
        try:
            data = json.loads(raw)
            if not isinstance(data, dict) or "api_key" in data:
                raise ValueError
            return ProviderConfig.model_validate(data)
        except (ValueError, TypeError):
            raise ProviderConfigError("Invalid saved LLM configuration") from None

    def save(self, config: ProviderConfig) -> None:
        temporary: Path | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent, delete=False
            ) as stream:
                temporary = Path(stream.name)
                stream.write(config.model_dump_json(indent=2) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except OSError:
            raise ProviderConfigError("Cannot save LLM configuration") from None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def resolve(
        self,
        explicit: ProviderConfig | None = None,
        *,
        api_key: str | SecretStr | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> ProviderConfig:
        env = os.environ if environ is None else environ
        values: dict[str, object] = {}
        for field, variable in (
            ("base_url", "OPENAI_BASE_URL"),
            ("model", "OPENAI_MODEL"),
            ("timeout_seconds", "OPENAI_TIMEOUT_SECONDS"),
        ):
            if variable in env:
                values[field] = env[variable]
        saved = self.load()
        if saved is not None:
            values.update(saved.model_dump(exclude_unset=True))
        if explicit is not None:
            values.update(explicit.model_dump(exclude_unset=True))
        # Existing constructor keyword arguments are explicit runtime overrides.
        if model is not None:
            values["model"] = model
        if timeout_seconds is not None:
            values["timeout_seconds"] = timeout_seconds
        key = (
            api_key
            if api_key is not None
            else explicit.api_key
            if explicit is not None and explicit.api_key is not None
            else env.get("OPENAI_API_KEY")
        )
        values["api_key"] = key
        try:
            return ProviderConfig.model_validate(values)
        except ValidationError:
            raise ProviderConfigError(
                "Invalid LLM configuration; check provider, URL, model, positive timeout and credential"
            ) from None

    def test_connection(
        self, config: ProviderConfig | None = None
    ) -> ConnectionTestResult:
        from ai_agent_project.llm.runtime import build_openai_client

        client = None
        try:
            resolved = self.resolve(config)
            client = build_openai_client(resolved)
            response = client.responses.create(
                model=resolved.model,
                input="Reply OK.",
                max_output_tokens=128,
                store=False,
            )
            if (
                not isinstance(getattr(response, "output_text", None), str)
                or not response.output_text.strip()
            ):
                return ConnectionTestResult(
                    success=False, message="Provider returned no text response"
                )
            return ConnectionTestResult(success=True, message="Connection successful")
        except ProviderConfigError:
            return ConnectionTestResult(
                success=False, message="Invalid configuration or missing credential"
            )
        except Exception:  # noqa: BLE001 -- provider errors may contain secrets
            return ConnectionTestResult(
                success=False,
                message="Connection failed; check endpoint, credential, model and Responses API support",
            )
        finally:
            if client is not None:
                client.close()
