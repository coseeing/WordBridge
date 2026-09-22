from dataclasses import dataclass, field


COSEEING_GROUP = "Coseeing"
LOCAL_CHANNEL = "local"


def make_corrector_config_id(model: str, provider: str | None = None) -> str:
	"""The one identity rule.

	A local offer always joins with "&"; an entry the server provides on its
	own has no provider and gets the bare model name. The two forms cannot
	collide, because one always contains "&" and the other never does.
	"""
	if "&" in model or (provider is not None and "&" in provider):
		raise ValueError("model and provider must not contain '&'")
	return model if provider is None else f"{model}&{provider}"


@dataclass(frozen=True)
class CatalogIssue:
	code: str
	location: str
	detail: str


# Issue codes that flag a lint-level quirk in the source data -- legal,
# nothing dropped -- rather than an entry, provider or document that was
# actually rejected. "unreferenced_provider" (a provider no models entry
# names) is the only one document.py, sources.py or fallback.py emit that
# means this: every other code they emit means something was dropped. Kept
# here, next to CatalogIssue, so a caller like the settings panel can ask
# "was anything actually dropped" without hard-coding the validation
# vocabulary itself (lib/catalog owns it, and may not reach _()).
LINT_ISSUE_CODES = frozenset({"unreferenced_provider"})


def is_dropped_issue(issue: CatalogIssue) -> bool:
	"""True unless `issue` is a known lint-level quirk (see LINT_ISSUE_CODES).

	Used to report only entries/providers/documents that were actually
	dropped, as opposed to every issue logged (issues are always logged in
	full -- see __init__.py).
	"""
	return issue.code not in LINT_ISSUE_CODES


@dataclass(frozen=True)
class ProviderEntry:
	name: str
	label: str
	url: str
	setting: dict
	timeout0: int
	timeout_max: int


@dataclass(frozen=True)
class ModelEntry:
	provider: str
	model: str
	label: str
	active: bool = True
	pricing: dict | None = None
	usage_key: str | None = None

	@property
	def corrector_config_id(self) -> str:
		return make_corrector_config_id(self.model, self.provider)

	def price_entry(self) -> dict:
		"""The shape CostCalculator consumes.

		{} when there is no price, which is byte-for-byte what the old
		price.json lookup returned via .get(key, {}).
		"""
		if self.pricing is None:
			return {}
		return {
			"model": self.model,
			"provider": self.provider,
			"pricing": self.pricing,
			"usage_key": self.usage_key,
		}


@dataclass(frozen=True)
class CoseeingEntry:
	model: str
	label: str
	provider: str | None = None
	active: bool = True

	@property
	def corrector_config_id(self) -> str:
		return make_corrector_config_id(self.model, self.provider)


@dataclass(frozen=True)
class SelectableItem:
	provider_group: str
	corrector_config_id: str
	execution_channel: str
	label: str


@dataclass(frozen=True)
class CorrectorCatalog:
	providers: dict = field(default_factory=dict)
	models: tuple = ()
	coseeings: tuple = ()
	issues: tuple = ()
	degraded: bool = False

	def __post_init__(self):
		groups: dict[str, list] = {}
		for entry in self.models:
			if not entry.active:
				continue
			groups.setdefault(entry.provider, []).append(SelectableItem(
				provider_group=entry.provider,
				corrector_config_id=entry.corrector_config_id,
				execution_channel=LOCAL_CHANNEL,
				label=entry.label,
			))
		for entry in self.coseeings:
			if not entry.active:
				continue
			groups.setdefault(COSEEING_GROUP, []).append(SelectableItem(
				provider_group=COSEEING_GROUP,
				corrector_config_id=entry.corrector_config_id,
				execution_channel=COSEEING_GROUP,
				label=entry.label,
			))
		object.__setattr__(self, "_groups", {name: tuple(items) for name, items in groups.items()})

	@property
	def provider_groups(self) -> tuple:
		local = sorted(name for name in self._groups if name != COSEEING_GROUP)
		if COSEEING_GROUP in self._groups:
			return tuple(local + [COSEEING_GROUP])
		return tuple(local)

	def items_for(self, provider_group: str) -> tuple:
		return self._groups.get(provider_group, ())

	def labels_for(self, provider_group: str) -> tuple:
		return tuple(item.label for item in self.items_for(provider_group))

	@property
	def selectable_items(self) -> tuple:
		return tuple(
			item
			for group in self.provider_groups
			for item in self._groups[group]
		)

	def get_model(self, corrector_config_id: str):
		for entry in self.models:
			if entry.corrector_config_id == corrector_config_id:
				return entry
		return None

	def get_coseeing(self, corrector_config_id: str):
		for entry in self.coseeings:
			if entry.corrector_config_id == corrector_config_id:
				return entry
		return None

	def get_provider(self, name: str):
		return self.providers.get(name)

	def find_selection(self, corrector_config_id: str, execution_channel: str) -> tuple:
		for group_index, group in enumerate(self.provider_groups):
			for model_index, item in enumerate(self._groups[group]):
				if (
					item.corrector_config_id == corrector_config_id
					and item.execution_channel == execution_channel
				):
					return (group_index, model_index)
		return (-1, -1)

	def get_item(self, group_index: int, model_index: int) -> SelectableItem:
		group = self.provider_groups[group_index]
		return self._groups[group][model_index]

	def default_selection(self) -> tuple:
		for item in self.items_for(COSEEING_GROUP):
			return (item.corrector_config_id, item.execution_channel)
		for item in self.selectable_items:
			return (item.corrector_config_id, item.execution_channel)
		raise ValueError("No selectable corrector entries available")
