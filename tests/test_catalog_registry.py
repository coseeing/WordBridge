import pytest

from lib.catalog import registry
from lib.catalog.model import CorrectorCatalog


@pytest.fixture(autouse=True)
def _reset_registry():
	registry.reset()
	yield
	registry.reset()


def test_replace_before_initialize_raises():
	with pytest.raises(RuntimeError):
		registry.replace(CorrectorCatalog())


def test_replace_swaps_current():
	first, second = CorrectorCatalog(), CorrectorCatalog(degraded=True)
	registry.initialize(first)

	registry.replace(second)

	assert registry.current() is second
