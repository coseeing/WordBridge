from .model import COSEEING_GROUP, LOCAL_CHANNEL


def normalize_selection(catalog, corrector_config_id: str, execution_channel: str) -> tuple:
	"""Resolve a stored selection against a catalog.

	Membership decides the channel: an id in coseeings can run on Coseeing, an
	id in models can run locally. Anything unresolvable becomes the catalog's
	default, which is why an empty stored value -- what a fresh install has,
	now that the config spec defaults are static -- lands on the default too.
	"""
	on_coseeing = catalog.get_coseeing(corrector_config_id) is not None
	on_local = catalog.get_model(corrector_config_id) is not None

	if execution_channel == COSEEING_GROUP and on_coseeing:
		return (corrector_config_id, COSEEING_GROUP)
	if execution_channel == LOCAL_CHANNEL and on_local:
		return (corrector_config_id, LOCAL_CHANNEL)
	if on_local:
		return (corrector_config_id, LOCAL_CHANNEL)
	if on_coseeing:
		return (corrector_config_id, COSEEING_GROUP)
	return catalog.default_selection()


class SelectionState:
	"""What the settings panel currently has selected.

	This is deliberately not on the catalog: the catalog answers the same
	question for everyone, and the panel's in-progress choice is nobody
	else's business. It was ConfigManager.provider that forced the two
	together.
	"""

	def __init__(self, catalog, provider_group_index: int, model_index: int):
		self.catalog = catalog
		self.provider_group_index = provider_group_index
		self.model_index = model_index

	@classmethod
	def restore(cls, catalog, corrector_config_id: str, execution_channel: str) -> "SelectionState":
		corrector_config_id, execution_channel = normalize_selection(
			catalog, corrector_config_id, execution_channel
		)
		indices = catalog.find_selection(corrector_config_id, execution_channel)
		if indices == (-1, -1):
			indices = catalog.find_selection(*catalog.default_selection())
		return cls(catalog, indices[0], indices[1])

	@property
	def provider_group(self) -> str:
		return self.catalog.provider_groups[self.provider_group_index]

	def choose_provider_group(self, index: int) -> None:
		self.provider_group_index = index
		self.model_index = 0

	def current_item(self):
		return self.catalog.get_item(self.provider_group_index, self.model_index)
