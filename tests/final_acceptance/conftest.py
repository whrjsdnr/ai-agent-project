import importlib.util
import sys
from pathlib import Path

import pytest


def load_seed(name, relative):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).parents[1] / relative
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


developer_seed = load_seed("final_desktop_seed", "desktop/conftest.py")
research_seed = load_seed(
    "final_research_seed", "agent/test_research_implementation.py"
)
setup = developer_seed.setup


@pytest.fixture
def seeds():
    return developer_seed, research_seed


improvement_seed = load_seed("final_improvement_seed", "improvement/conftest.py")
env = improvement_seed.env
improvement_acceptance = load_seed(
    "final_improvement_requests", "improvement/test_acceptance.py"
)


@pytest.fixture
def actual_provider_operation():
    return improvement_acceptance.production
