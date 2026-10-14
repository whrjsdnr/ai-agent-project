"""Shared OpenAI-compatible SDK boundary; no workflow state or provider registry."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Protocol

from ai_agent_project.llm.config import (
    ProviderConfig,
    ProviderConfigError,
    ProviderConfigService,
)


class ResponsesAPI(Protocol):
    def create(self, **kwargs: Any) -> Any: ...


class OpenAIAPIClient(Protocol):
    responses: ResponsesAPI


class ProviderRequestError(ValueError):
    """Sanitized provider failure safe for CLI/API and workflow error records."""


class _SafeResponses:
    def __init__(self, responses: ResponsesAPI) -> None:
        self._responses = responses

    def create(self, **kwargs: Any) -> Any:
        from ai_agent_project.improvement.context import (
            AUTHORITY,
            current_context,
            note_context_use,
        )

        context = current_context()
        if context is not None and context.rules:
            kwargs = dict(kwargs)
            kwargs["instructions"] = (
                (kwargs.get("instructions") or "") + "\n" + AUTHORITY
            )
            original = kwargs.get("input", "")
            guidance = context.prompt()
            kwargs["input"] = (
                [*original, {"role": "user", "content": guidance}]
                if isinstance(original, list)
                else str(original) + "\n" + guidance
            )
        try:
            result = self._responses.create(**kwargs)
            if context is not None and context.rules:
                note_context_use()
            return result
        except Exception:  # noqa: BLE001 -- provider errors may contain secrets
            # SDK errors can contain request headers, endpoint URLs or response bodies.
            raise ProviderRequestError(
                "LLM provider request failed; check connection, credential, model and supported API features"
            ) from None


class _SafeClient:
    def __init__(self, client: Any) -> None:
        self._client = client
        self.responses = _SafeResponses(client.responses)

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:  # noqa: BLE001, S110 -- never log credential-bearing cleanup errors
            pass


def build_openai_client(config: ProviderConfig) -> _SafeClient:
    if config.api_key is None:
        raise ProviderConfigError(
            "OPENAI_API_KEY must be configured (or supply a runtime credential)"
        )
    from openai import OpenAI

    try:
        return _SafeClient(
            OpenAI(
                api_key=config.api_key.get_secret_value(),
                base_url=config.base_url,
                timeout=config.timeout_seconds,
                max_retries=0,
            )
        )
    except Exception:  # noqa: BLE001 -- provider errors may contain secrets
        raise ProviderConfigError("Cannot construct configured LLM client") from None


class ConfiguredOpenAIProvider:
    """Share configuration resolution and lazy construction across existing providers."""

    def _configure(
        self,
        *,
        config: ProviderConfig | None,
        api_key: str | None,
        model: str | None,
        client: OpenAIAPIClient | None,
        timeout_seconds: float | None = None,
    ) -> None:
        self._config = ProviderConfigService().resolve(
            config,
            api_key=api_key,
            model=model,
            timeout_seconds=timeout_seconds,
        )
        self._model = self._config.model
        self._client = _SafeClient(client) if client is not None else None

    def _get_client(self) -> OpenAIAPIClient:
        if self._client is None:
            self._client = build_openai_client(self._config)
            clients = _operation_clients.get()
            if clients is not None:
                clients.append(self._client)
        return self._client


# Desktop operations own and release their lazy clients when a single call ends.
_operation_clients: ContextVar[list | None] = ContextVar(
    "operation_clients", default=None
)


@contextmanager
def provider_client_scope() -> Iterator[None]:
    clients = []
    token = _operation_clients.set(clients)
    try:
        yield
    finally:
        _operation_clients.reset(token)
        for client in clients:
            client.close()
