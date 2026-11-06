"""Deployment settings for the /proofreader correction workflow.

Loads the bundled catalog and the corrector task config, validates the
deployment default model at startup, and resolves requested corrector
config IDs against the catalog for use by request handlers.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from .lib.catalog import CorrectorCatalog
from .lib.catalog.fallback import load_catalog
from .lib.catalog.sources import BundledCatalogSource
from .lib.llm import SUPPORTED_PROVIDERS
from .settings import Settings, load_settings

SETTING_DIR = Path(__file__).parent / "setting"
CORRECTOR_TASK_CONFIG_PATH = SETTING_DIR / "task" / "corrector.json"


@dataclass(frozen=True)
class CorrectionSettings:
	catalog: CorrectorCatalog
	template_name: dict
	optional_guidance_enable: dict
	default_id: str
	coseeing_ids: frozenset = frozenset()


def load_correction_settings(settings: Settings = None) -> CorrectionSettings:
	"""Build the process-wide correction settings.

	Reads the bundled catalog and the corrector task config relative to this
	module's location, then validates that the configured deployment default
	model ID points to an enabled, runnable local model. The default and
	the Coseeing ids come from `settings` (read afresh from the environment
	when omitted), so DEFAULT_CORRECTOR_CONFIG_ID and COSEEING_MODEL_IDS
	have no built-in fallback. Raises ValueError (SettingsError when a
	variable is missing) when the default is unset or invalid, so a broken
	deployment fails loudly at startup rather than silently running a model
	nobody chose.
	"""
	if settings is None:
		settings = load_settings()
	catalog = load_catalog(BundledCatalogSource(SETTING_DIR), runnable_providers=SUPPORTED_PROVIDERS)
	task_config = _read_json(CORRECTOR_TASK_CONFIG_PATH)

	default_id = settings.default_corrector_config_id
	model = catalog.get_model(default_id)
	if model is None or not model.active or catalog.get_provider(model.provider) is None:
		raise ValueError(
			f"DEFAULT_CORRECTOR_CONFIG_ID {default_id!r} does not name an enabled, runnable local catalog model"
		)

	return CorrectionSettings(
		catalog=catalog,
		template_name=task_config.get("template_name", {}),
		optional_guidance_enable=task_config.get("optional_guidance_enable", {}),
		default_id=default_id,
		coseeing_ids=settings.coseeing_model_ids,
	)


def resolve_model(settings: CorrectionSettings, requested_id: str):
	"""Resolve a requested corrector config ID to a runnable local model entry.

	"default" resolves to the deployment-configured default local model. Any
	other ID must first be one the server serves on Coseeing
	(settings.coseeing_ids, from COSEEING_MODEL_IDS) and must then name an
	active local model entry with a supported provider. Raises LookupError
	when the requested model is unavailable.
	"""
	selected_id = settings.default_id if requested_id == "default" else requested_id
	if requested_id != "default" and selected_id not in settings.coseeing_ids:
		raise LookupError(selected_id)
	model = settings.catalog.get_model(selected_id)
	if model is None or not model.active or settings.catalog.get_provider(model.provider) is None:
		raise LookupError(selected_id)
	return model


def _read_json(path: Path) -> dict:
	with path.open("r", encoding="utf8") as handle:
		return json.load(handle)
