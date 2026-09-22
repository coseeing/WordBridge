from .model import (
	CatalogIssue,
	CoseeingEntry,
	CorrectorCatalog,
	ModelEntry,
	ProviderEntry,
)


SCHEMA_VERSION = 1
PROVIDER_FIELDS = ("label", "url", "setting", "timeout0", "timeout_max")


def _text(value) -> bool:
	return isinstance(value, str) and value != ""


def build_catalog(document, *, runnable_providers) -> CorrectorCatalog:
	"""Always returns a catalog. Problems become issues, never exceptions."""
	issues = []
	if not isinstance(document, dict):
		issues.append(CatalogIssue("malformed_document", "document", f"expected a mapping, got {type(document).__name__}"))
		return CorrectorCatalog(issues=tuple(issues))
	if document.get("schema_version") != SCHEMA_VERSION:
		issues.append(CatalogIssue(
			"schema_version",
			"document",
			f"expected {SCHEMA_VERSION}, got {document.get('schema_version')!r}",
		))
		return CorrectorCatalog(issues=tuple(issues))

	providers = _build_providers(document.get("providers"), issues)
	models = _build_models(document.get("models"), providers, runnable_providers, issues)
	coseeings = _build_coseeings(document.get("coseeings"), issues)

	named = {entry.provider for entry in models}
	for name in sorted(set(providers) - named):
		issues.append(CatalogIssue("unreferenced_provider", f"providers.{name}", "no models entry names this provider"))

	return CorrectorCatalog(
		providers=providers,
		models=models,
		coseeings=coseeings,
		issues=tuple(issues),
	)


def _build_providers(raw, issues) -> dict:
	providers = {}
	if not isinstance(raw, dict):
		return providers
	for name in sorted(raw):
		location = f"providers.{name}"
		data = raw[name]
		if not _text(name) or "&" in name:
			issues.append(CatalogIssue("reserved_separator", location, "provider name is empty or contains '&'"))
			continue
		if not isinstance(data, dict):
			issues.append(CatalogIssue("incomplete_provider", location, "entry is not a mapping"))
			continue
		missing = [key for key in PROVIDER_FIELDS if key not in data or data[key] in ("", None)]
		if missing:
			issues.append(CatalogIssue("incomplete_provider", location, f"missing {', '.join(missing)}"))
			continue
		providers[name] = ProviderEntry(
			name=name,
			label=data["label"],
			url=data["url"],
			setting=data["setting"],
			timeout0=data["timeout0"],
			timeout_max=data["timeout_max"],
		)
	return providers


def _build_models(raw, providers, runnable_providers, issues) -> tuple:
	entries = []
	seen = set()
	for index, data in enumerate(raw or ()):
		location = f"models[{index}]"
		if not isinstance(data, dict):
			issues.append(CatalogIssue("incomplete_entry", location, "entry is not a mapping"))
			continue
		model, provider, label = data.get("model"), data.get("provider"), data.get("label")
		if not (_text(model) and _text(provider) and _text(label)):
			issues.append(CatalogIssue("incomplete_entry", location, "model, provider and label are all required"))
			continue
		if "&" in model or "&" in provider:
			issues.append(CatalogIssue("reserved_separator", location, "model and provider must not contain '&'"))
			continue
		active = data.get("active", True)
		if not isinstance(active, bool):
			issues.append(CatalogIssue("invalid_active", location, f"active must be a boolean, got {active!r}"))
			continue
		if provider not in providers:
			issues.append(CatalogIssue("unknown_provider", location, f"no providers entry for {provider!r}"))
			continue
		if provider not in runnable_providers:
			issues.append(CatalogIssue("unsupported_provider", location, f"this build has no implementation for {provider!r}"))
			continue
		entry = ModelEntry(
			provider=provider,
			model=model,
			label=label,
			active=active,
			pricing=data.get("pricing"),
			usage_key=data.get("usage_key"),
		)
		if entry.corrector_config_id in seen:
			issues.append(CatalogIssue("duplicate_entry", location, f"{entry.corrector_config_id!r} already defined"))
			continue
		seen.add(entry.corrector_config_id)
		entries.append(entry)
	return tuple(entries)


def _build_coseeings(raw, issues) -> tuple:
	entries = []
	seen = set()
	for index, data in enumerate(raw or ()):
		location = f"coseeings[{index}]"
		if not isinstance(data, dict):
			issues.append(CatalogIssue("incomplete_entry", location, "entry is not a mapping"))
			continue
		model, label, provider = data.get("model"), data.get("label"), data.get("provider")
		if not (_text(model) and _text(label)):
			issues.append(CatalogIssue("incomplete_entry", location, "model and label are both required"))
			continue
		if provider is not None and not _text(provider):
			issues.append(CatalogIssue("incomplete_entry", location, "provider, when present, must be a non-empty string"))
			continue
		if "&" in model or (provider is not None and "&" in provider):
			issues.append(CatalogIssue("reserved_separator", location, "model and provider must not contain '&'"))
			continue
		active = data.get("active", True)
		if not isinstance(active, bool):
			issues.append(CatalogIssue("invalid_active", location, f"active must be a boolean, got {active!r}"))
			continue
		entry = CoseeingEntry(model=model, label=label, provider=provider, active=active)
		if entry.corrector_config_id in seen:
			issues.append(CatalogIssue("duplicate_entry", location, f"{entry.corrector_config_id!r} already defined"))
			continue
		seen.add(entry.corrector_config_id)
		entries.append(entry)
	return tuple(entries)
