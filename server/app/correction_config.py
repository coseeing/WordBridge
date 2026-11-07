"""Deployment settings for the /proofreader correction workflow.

Loads the bundled catalog and the corrector task config, validates the
deployment default model at startup, reads the API key of every provider a
served model uses, and resolves requested corrector config IDs against the
catalog for use by request handlers.

The keys are checked here, not in app/settings.py: alembic imports
app.settings, and running a migration must not need API keys.
"""

import json
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

from .lib.catalog import CorrectorCatalog
from .lib.catalog.fallback import load_catalog
from .lib.catalog.sources import BundledCatalogSource
from .lib.llm import SUPPORTED_PROVIDERS
from .settings import Settings, SettingsError, load_settings

logger = logging.getLogger(__name__)

SETTING_DIR = Path(__file__).parent / "setting"
CORRECTOR_TASK_CONFIG_PATH = SETTING_DIR / "task" / "corrector.json"
# Written by server/sync_addon_code.py from buildVars.py.
ADDON_VERSION_PATH = SETTING_DIR / "addon_version.txt"


@dataclass(frozen=True)
class CorrectionSettings:
	catalog: CorrectorCatalog
	template_name: dict
	optional_guidance_enable: dict
	default_id: str
	coseeing_ids: frozenset = frozenset()
	# Provider name -> API key, for every provider a served model uses. Kept
	# out of repr so the keys never reach a log through this object.
	api_keys: Mapping[str, str] = field(default_factory=dict, repr=False)


def api_key_variable(provider: str) -> str:
	"""The environment variable holding `provider`'s API key."""
	return f"{provider.upper()}_API_KEY"


def load_correction_settings(
	settings: Settings | None = None,
	environ: Mapping[str, str] | None = None,
) -> CorrectionSettings:
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

	Every provider a served model uses must have its key set in `environ`
	(os.environ by default): the default model, and each COSEEING_MODEL_IDS
	entry resolve_model() could serve. A missing or blank key raises one
	SettingsError naming every missing variable and no value. An entry that
	cannot be served is logged as a warning and needs no key: a catalog
	update that deactivates a model must not stop the server, and the
	entry keeps being rejected per request.
	"""
	if environ is None:
		environ = os.environ
	if settings is None:
		settings = load_settings(environ)
	catalog = load_catalog(BundledCatalogSource(SETTING_DIR), runnable_providers=SUPPORTED_PROVIDERS)
	task_config = _read_json(CORRECTOR_TASK_CONFIG_PATH)

	default_id = settings.default_corrector_config_id
	model = catalog.get_model(default_id)
	if model is None or not model.active or catalog.get_provider(model.provider) is None:
		raise ValueError(
			f"DEFAULT_CORRECTOR_CONFIG_ID {default_id!r} does not name an enabled, runnable local catalog model",
		)

	correction_settings = CorrectionSettings(
		catalog=catalog,
		template_name=task_config.get("template_name", {}),
		optional_guidance_enable=task_config.get("optional_guidance_enable", {}),
		default_id=default_id,
		coseeing_ids=settings.coseeing_model_ids,
	)
	providers = {model.provider}
	for coseeing_id in sorted(settings.coseeing_model_ids):
		try:
			providers.add(resolve_model(correction_settings, coseeing_id).provider)
		except LookupError:
			logger.warning(
				"COSEEING_MODEL_IDS entry %s is not an active catalog model with a supported provider; "
				"requests for it are rejected",
				coseeing_id,
			)
	api_keys = {}
	missing = []
	for provider in sorted(providers):
		key = environ.get(api_key_variable(provider), "")
		if key.strip():
			api_keys[provider] = key
		else:
			missing.append(api_key_variable(provider))
	if missing:
		raise SettingsError("Provider API keys are missing: " + ", ".join(missing))
	return replace(correction_settings, api_keys=api_keys)


def load_addon_version(path: Path = ADDON_VERSION_PATH) -> str:
	"""The add-on version this server's code and prompts correspond to.

	Recorded with every correction. Raises ValueError when the file is
	missing or blank, so a broken image stops at startup.
	"""
	try:
		version = path.read_text(encoding="utf-8").strip()
	except FileNotFoundError as error:
		raise ValueError(f"{path.name} is missing; run python3 server/sync_addon_code.py") from error
	if not version:
		raise ValueError(f"{path.name} is empty; run python3 server/sync_addon_code.py")
	return version


def template_stem(template_name: str) -> str:
	"""The template file name as recorded: without .json (Standard_v1)."""
	return template_name.removesuffix(".json")


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
