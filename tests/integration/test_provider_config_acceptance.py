"""Compact Phase 6A fresh-process acceptance with a fake SDK boundary."""

import os
import subprocess
import sys
from io import StringIO

from ai_agent_project.cli import run_cli
from ai_agent_project.llm.config import ProviderConfigService


def test_phase6a_provider_free_acceptance(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "user-config"))
    monkeypatch.setenv("OPENAI_API_KEY", "phase6a-test-secret")
    for name in ("OPENAI_BASE_URL", "OPENAI_MODEL", "OPENAI_TIMEOUT_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    output = StringIO()
    assert (
        run_cli(
            [
                "config",
                "llm",
                "set",
                "--base-url",
                "http://localhost:9876/custom/v1",
                "--model",
                "local-model",
                "--timeout-seconds",
                "11",
            ],
            stdout=output,
        )
        == 0
    )
    path = ProviderConfigService().path
    assert "phase6a-test-secret" not in path.read_text() + output.getvalue()
    before = path.read_bytes()
    code = r"""
from types import SimpleNamespace
import openai
from ai_agent_project.llm.config import ProviderConfigService, ProviderConfig
from ai_agent_project.llm.providers.openai_specification import OpenAISpecificationParser
from ai_agent_project.llm.providers.openai_research_question_planner import OpenAIResearchQuestionPlanner
calls = []
requests = []
def sdk(**kwargs):
    calls.append(kwargs)
    assert kwargs['api_key'] == 'phase6a-test-secret'
    def create(**request):
        requests.append(request)
        if kwargs['base_url'] == 'http://localhost:9876/bad':
            raise RuntimeError('phase6a-test-secret')
        assert kwargs['base_url'] == 'http://localhost:9876/custom/v1'
        assert kwargs['timeout'] == 11
        assert request['model'] == 'local-model'
        return SimpleNamespace(output_text='OK')
    return SimpleNamespace(responses=SimpleNamespace(create=create), close=lambda: None)
openai.OpenAI = sdk
service = ProviderConfigService()
assert service.resolve().model == 'local-model'
assert service.test_connection().success
for provider in (OpenAISpecificationParser(), OpenAIResearchQuestionPlanner()):
    provider._get_client().responses.create(model=provider._model, input='OK')
assert len(calls) == 3
bad = service.test_connection(ProviderConfig(base_url='http://localhost:9876/bad'))
assert not bad.success and 'phase6a-test-secret' not in str(bad)
assert len(calls) == 4
assert calls[-1]['base_url'] == 'http://localhost:9876/bad'
print('PHASE_6A_PROVIDER_FREE_ACCEPTANCE=PASSED')
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=dict(os.environ),
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "PHASE_6A_PROVIDER_FREE_ACCEPTANCE=PASSED"
    assert "phase6a-test-secret" not in result.stdout + result.stderr
    assert path.read_bytes() == before
    assert [item for item in tmp_path.rglob("*") if item.is_file()] == [path]
