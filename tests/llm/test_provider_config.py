"""Provider-free configuration, credential and SDK wiring contracts."""

import importlib
import json
import pkgutil
from io import StringIO
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from ai_agent_project.cli import run_cli
from ai_agent_project.llm.config import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    ProviderConfig,
    ProviderConfigError,
    ProviderConfigService,
    default_provider_config_path,
)
from ai_agent_project.llm.runtime import (
    ConfiguredOpenAIProvider,
    ProviderRequestError,
    build_openai_client,
)

SECRET = "phase6a-test-secret"


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    for name in (
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_MODEL",
        "OPENAI_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)


def custom_config(**updates):
    return ProviderConfig(
        base_url="http://localhost:9876/v1",
        model="personal-model",
        timeout_seconds=12.5,
        api_key=SECRET,
        **updates,
    )


def test_default_custom_and_safe_serialization():
    config = ProviderConfig()
    assert (
        config.provider_type,
        config.base_url,
        config.model,
        config.timeout_seconds,
    ) == ("openai-compatible", DEFAULT_BASE_URL, DEFAULT_MODEL, 90)
    custom = custom_config()
    assert custom.api_key.get_secret_value() == SECRET
    for public in (
        str(custom),
        repr(custom),
        custom.model_dump_json(),
        str(custom.model_dump()),
    ):
        assert SECRET not in public
    assert "api_key" not in custom.model_dump(include={"api_key"})
    assert "api_key" not in custom.model_dump_json()


@pytest.mark.parametrize(
    "values",
    [
        {"provider_type": "other"},
        {"model": " "},
        {"base_url": ""},
        {"base_url": "not-a-url"},
        {"base_url": "ftp://localhost"},
        {"base_url": "http://user:phase6a-test-secret@localhost/v1"},
        {"base_url": "http://localhost/v1?api_key=phase6a-test-secret"},
        {"base_url": "http://localhost:bad/v1"},
        {"timeout_seconds": 0},
        {"timeout_seconds": -1},
        {"timeout_seconds": float("nan")},
        {"timeout_seconds": float("inf")},
        {"api_key": " "},
        {"api_key": ""},
    ],
)
def test_validation_never_echoes_input(values):
    with pytest.raises(ValidationError) as caught:
        ProviderConfig(**values)
    assert SECRET not in str(caught.value)


def test_persistence_and_secret_boundary(tmp_path):
    service = ProviderConfigService()
    assert service.load() is None
    assert not service.path.parent.exists()
    assert service.path == tmp_path / "config" / "ai-agent" / "llm.json"
    service.save(custom_config())
    raw = service.path.read_text()
    assert SECRET not in raw and "api_key" not in raw
    loaded = ProviderConfigService().load()
    assert loaded.model_dump() == custom_config().model_dump()
    assert loaded.api_key is None


@pytest.mark.parametrize(
    "raw",
    [
        "broken",
        "[]",
        '{"timeout_seconds":0}',
        '{"model":" "}',
        '{"api_key":"phase6a-test-secret"}',
        '{"provider_type":"other"}',
    ],
)
def test_invalid_saved_configuration_no_fallback(tmp_path, raw):
    path = tmp_path / "llm.json"
    path.write_text(raw)
    with pytest.raises(ProviderConfigError, match="Invalid saved") as caught:
        ProviderConfigService(path).resolve(environ={"OPENAI_API_KEY": SECRET})
    assert SECRET not in str(caught.value)


def test_unreadable_config(tmp_path):
    with pytest.raises(ProviderConfigError, match="Cannot read"):
        ProviderConfigService(tmp_path).load()


def test_central_precedence_and_credentials():
    service = ProviderConfigService()
    env = {
        "OPENAI_BASE_URL": "http://localhost:9876/env",
        "OPENAI_MODEL": "env-model",
        "OPENAI_TIMEOUT_SECONDS": "22",
        "OPENAI_API_KEY": SECRET,
    }
    resolved = service.resolve(environ=env)
    assert (resolved.model, resolved.timeout_seconds, resolved.base_url) == (
        "env-model",
        22,
        env["OPENAI_BASE_URL"],
    )
    service.save(ProviderConfig(model="saved-model", timeout_seconds=33))
    saved = service.resolve(environ=env)
    assert (saved.model, saved.timeout_seconds, saved.base_url) == (
        "saved-model",
        33,
        DEFAULT_BASE_URL,
    )
    runtime = service.resolve(ProviderConfig(model="runtime-model"), environ=env)
    assert runtime.model == "runtime-model" and runtime.timeout_seconds == 33
    assert runtime.api_key.get_secret_value() == SECRET
    override = service.resolve(
        ProviderConfig(api_key="runtime-fake-key"),
        api_key="argument-fake-key",
        model="argument-model",
        timeout_seconds=44,
        environ=env,
    )
    assert override.api_key.get_secret_value() == "argument-fake-key"
    assert override.model == "argument-model" and override.timeout_seconds == 44
    with pytest.raises(ProviderConfigError):
        service.resolve(api_key="", environ=env)


def test_partial_saved_config_and_invalid_environment(tmp_path):
    path = tmp_path / "llm.json"
    path.write_text('{"model":"saved"}')
    service = ProviderConfigService(path)
    assert (
        service.resolve(environ={"OPENAI_TIMEOUT_SECONDS": "17"}).timeout_seconds == 17
    )
    with pytest.raises(ProviderConfigError):
        service.resolve(environ={"OPENAI_TIMEOUT_SECONDS": "bad"})


def test_xdg_requires_absolute_path(monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", "relative")
    assert default_provider_config_path().is_absolute()


def fake_sdk(monkeypatch, *, error=None, output="OK"):
    constructed, requests = [], []

    def create(**kwargs):
        requests.append(kwargs)
        if error is not None:
            raise error
        return SimpleNamespace(output_text=output)

    def constructor(**kwargs):
        constructed.append(kwargs)
        return SimpleNamespace(
            responses=SimpleNamespace(create=create), close=lambda: None
        )

    monkeypatch.setattr("openai.OpenAI", constructor)
    return constructed, requests


def test_connection_custom_endpoint_and_no_workflow_files(tmp_path, monkeypatch):
    constructed, requests = fake_sdk(monkeypatch)
    result = ProviderConfigService().test_connection(custom_config())
    assert result.success
    assert constructed[0]["base_url"] == "http://localhost:9876/v1"
    assert constructed[0]["timeout"] == 12.5
    assert constructed[0]["api_key"] == SECRET
    assert requests[0]["model"] == "personal-model"
    assert requests[0]["store"] is False and "tools" not in requests[0]
    assert SECRET not in result.model_dump_json()
    assert list(tmp_path.rglob("*")) == []


@pytest.mark.parametrize(
    "error", [RuntimeError(SECRET), ConnectionError(SECRET), PermissionError(SECRET)]
)
def test_provider_errors_are_sanitized(monkeypatch, error):
    fake_sdk(monkeypatch, error=error)
    result = ProviderConfigService().test_connection(custom_config())
    assert not result.success and SECRET not in result.model_dump_json()
    client = build_openai_client(custom_config())
    with pytest.raises(ProviderRequestError) as caught:
        client.responses.create(model="personal-model", input="OK")
    assert SECRET not in str(caught.value)
    assert caught.value.__suppress_context__


def test_missing_key_no_request_and_bad_response(monkeypatch):
    constructed, requests = fake_sdk(monkeypatch, output=None)
    assert not ProviderConfigService().test_connection().success
    assert constructed == requests == []
    assert not ProviderConfigService().test_connection(custom_config()).success


def provider_classes():
    import ai_agent_project.llm.providers as package

    found = []
    for info in pkgutil.iter_modules(package.__path__):
        if not info.name.startswith("openai"):
            continue
        module = importlib.import_module(package.__name__ + "." + info.name)
        for name, candidate in vars(module).items():
            if (
                isinstance(candidate, type)
                and candidate.__module__ == module.__name__
                and not name.startswith("_")
                and issubclass(candidate, ConfiguredOpenAIProvider)
            ):
                found.append(candidate)
    return found


@pytest.mark.parametrize("provider", provider_classes(), ids=lambda cls: cls.__name__)
def test_every_production_provider_uses_saved_settings(provider, monkeypatch):
    ProviderConfigService().save(custom_config())
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    constructed, _ = fake_sdk(monkeypatch)
    instance = provider()
    instance._get_client()
    assert instance._model == "personal-model"
    assert constructed[0]["base_url"] == "http://localhost:9876/v1"
    assert constructed[0]["timeout"] == 12.5
    assert constructed[0]["api_key"] == SECRET
    assert SECRET not in repr(instance)


def test_developer_researcher_and_hybrid_composition(monkeypatch, tmp_path):
    from ai_agent_project.agent.project_handoff import (
        ProjectHandoff,
        ResearchBootstrapProvenance,
    )
    from ai_agent_project.agent.project_runner import ProjectRun
    from ai_agent_project.agent.project_session import ProjectSession
    from ai_agent_project.agent.research import ResearchRun
    from ai_agent_project.api.app import create_app

    constructed, _ = fake_sdk(monkeypatch)
    app = create_app(workspace_root=tmp_path, provider_config=custom_config())
    visited, providers = set(), []

    def visit(obj):
        if id(obj) in visited:
            return
        visited.add(id(obj))
        if isinstance(obj, ConfiguredOpenAIProvider):
            providers.append(obj)
            obj._get_client()
        elif type(obj).__module__.startswith("ai_agent_project"):
            for child in vars(obj).values():
                visit(child)

    for obj in (
        app.state.project_application_service,
        app.state.research_application_service,
        app.state.project_session_service,
        app.state.agent_service,
        app.state.coding_agent_service,
    ):
        visit(obj)
    assert {type(provider) for provider in providers} == set(provider_classes())
    assert all(provider._model == "personal-model" for provider in providers)
    assert all(
        item["base_url"] == "http://localhost:9876/v1"
        and item["timeout"] == 12.5
        and item["api_key"] == SECRET
        for item in constructed
    )
    for model in (
        ProjectSession,
        ProjectRun,
        ResearchRun,
        ProjectHandoff,
        ResearchBootstrapProvenance,
    ):
        assert (
            not {"api_key", "base_url", "provider_config", "timeout_seconds"}
            & model.model_fields.keys()
        )


def test_cli_set_show_test_and_invalid(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    constructed, _ = fake_sdk(monkeypatch)
    for args in (
        [
            "set",
            "--base-url",
            "http://localhost:9876/v1",
            "--model",
            "personal-model",
            "--timeout-seconds",
            "12.5",
        ],
        ["show"],
        ["test"],
    ):
        out, err = StringIO(), StringIO()
        assert run_cli(["config", "llm", *args], stdout=out, stderr=err) == 0
        assert SECRET not in out.getvalue() + err.getvalue()
    assert constructed[0]["base_url"] == "http://localhost:9876/v1"
    before = ProviderConfigService().path.read_bytes()
    out, err = StringIO(), StringIO()
    assert (
        run_cli(
            [
                "config",
                "llm",
                "set",
                "--base-url",
                "http://user:" + SECRET + "@localhost",
            ],
            stdout=out,
            stderr=err,
        )
        == 1
    )
    assert SECRET not in out.getvalue() + err.getvalue()
    assert ProviderConfigService().path.read_bytes() == before


@pytest.mark.parametrize("status_code", [200, 401, 404, 500])
def test_real_sdk_uses_custom_responses_url_and_auth(monkeypatch, status_code):
    import openai

    http = importlib.import_module("openai._client").httpx2
    real_sdk = openai.OpenAI
    seen = []

    def handler(request):
        seen.append(str(request.url))
        assert str(request.url) == "http://localhost:9876/v1/responses"
        assert request.headers["authorization"] == "Bearer " + SECRET
        assert json.loads(request.content)["model"] == "personal-model"
        assert request.extensions["timeout"]["read"] == 12.5
        if status_code != 200:
            return http.Response(status_code, json={"error": {"message": SECRET}})
        return http.Response(
            200,
            json={
                "id": "resp_fake",
                "object": "response",
                "created_at": 0,
                "status": "completed",
                "model": "personal-model",
                "output": [
                    {
                        "type": "message",
                        "id": "msg_fake",
                        "status": "completed",
                        "role": "assistant",
                        "content": [
                            {"type": "output_text", "text": "OK", "annotations": []}
                        ],
                    }
                ],
            },
        )

    def constructor(**kwargs):
        return real_sdk(
            **kwargs, http_client=http.Client(transport=http.MockTransport(handler))
        )

    monkeypatch.setattr(openai, "OpenAI", constructor)
    result = ProviderConfigService().test_connection(custom_config())
    assert result.success is (status_code == 200)
    assert SECRET not in result.model_dump_json()
    assert len(seen) == 1


def test_injected_client_error_does_not_leak_credential():
    from ai_agent_project.llm.providers.openai_specification import (
        OpenAISpecificationParser,
    )

    def create(**kwargs):
        raise RuntimeError(SECRET)

    provider = OpenAISpecificationParser(
        config=custom_config(),
        client=SimpleNamespace(responses=SimpleNamespace(create=create)),
    )
    with pytest.raises(ProviderRequestError) as error:
        provider.parse("Build a utility")
    assert SECRET not in str(error.value)


def test_default_openai_sdk_settings_and_constructor_failure(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    constructed, _ = fake_sdk(monkeypatch)
    config = ProviderConfigService().resolve()
    build_openai_client(config)
    assert constructed[0]["base_url"] == DEFAULT_BASE_URL
    assert constructed[0]["api_key"] == SECRET
    assert config.model == DEFAULT_MODEL

    def failed_constructor(**kwargs):
        raise RuntimeError(SECRET)

    monkeypatch.setattr("openai.OpenAI", failed_constructor)
    with pytest.raises(ProviderConfigError) as caught:
        build_openai_client(config)
    assert SECRET not in str(caught.value) + repr(caught.value)
    assert not ProviderConfigService().test_connection(config).success
