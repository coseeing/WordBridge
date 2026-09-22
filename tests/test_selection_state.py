import pytest

from lib.catalog.document import SCHEMA_VERSION, build_catalog
from lib.catalog.model import COSEEING_GROUP
from lib.catalog.selection import SelectionState, normalize_selection


RUNNABLE = frozenset({"OpenAI", "DeepSeek"})

PROVIDER = {
	"label": "x",
	"url": "https://example.invalid",
	"setting": {},
	"timeout0": 10,
	"timeout_max": 20,
}


def catalog():
	return build_catalog(
		{
			"schema_version": SCHEMA_VERSION,
			"providers": {"OpenAI": dict(PROVIDER), "DeepSeek": dict(PROVIDER)},
			"models": [
				{"provider": "DeepSeek", "model": "ds-x", "label": "DS X"},
				{"provider": "OpenAI", "model": "gpt-x", "label": "GPT X"},
			],
			"coseeings": [
				{"model": "default", "label": "Coseeing default"},
				{"model": "ds-x", "provider": "DeepSeek", "label": "DS X"},
			],
		},
		runnable_providers=RUNNABLE,
	)


def test_a_valid_selection_is_returned_unchanged():
	assert normalize_selection(catalog(), "gpt-x&OpenAI", "local") == ("gpt-x&OpenAI", "local")


def test_an_unknown_id_falls_back_to_the_catalog_default():
	assert normalize_selection(catalog(), "nope", "local") == ("default", COSEEING_GROUP)


def test_an_empty_id_falls_back_to_the_catalog_default():
	assert normalize_selection(catalog(), "", "") == ("default", COSEEING_GROUP)


def test_a_channel_the_entry_does_not_offer_falls_back_to_the_other_one():
	assert normalize_selection(catalog(), "gpt-x&OpenAI", COSEEING_GROUP) == ("gpt-x&OpenAI", "local")


def test_a_coseeing_only_entry_asked_for_locally_stays_on_coseeing():
	assert normalize_selection(catalog(), "default", "local") == ("default", COSEEING_GROUP)


def test_an_unrecognised_channel_name_is_normalised():
	assert normalize_selection(catalog(), "gpt-x&OpenAI", "nonsense") == ("gpt-x&OpenAI", "local")


def test_a_dual_membership_id_stored_on_coseeing_stays_on_coseeing():
	# ds-x&DeepSeek is in both models and coseeings in the fixture above: a
	# shipped entry with "coseeing": true. A user who picked it through
	# Coseeing must not be silently moved onto their own API key.
	assert normalize_selection(catalog(), "ds-x&DeepSeek", COSEEING_GROUP) == ("ds-x&DeepSeek", COSEEING_GROUP)


def test_a_dual_membership_id_stored_locally_stays_local():
	assert normalize_selection(catalog(), "ds-x&DeepSeek", "local") == ("ds-x&DeepSeek", "local")


def test_a_retired_entry_is_not_honoured_as_a_stored_selection():
	retired = build_catalog(
		{
			"schema_version": SCHEMA_VERSION,
			"providers": {"OpenAI": dict(PROVIDER)},
			"models": [{"provider": "OpenAI", "model": "gone", "label": "Gone", "active": False}],
			"coseeings": [{"model": "default", "label": "Coseeing default"}],
		},
		runnable_providers=RUNNABLE,
	)

	assert normalize_selection(retired, "gone&OpenAI", "local") == ("default", COSEEING_GROUP)


def test_restore_finds_the_stored_selection():
	state = SelectionState.restore(catalog(), "gpt-x&OpenAI", "local")

	assert state.provider_group == "OpenAI"
	assert state.current_item().corrector_config_id == "gpt-x&OpenAI"


def test_restore_falls_back_to_the_default_for_an_unknown_selection():
	state = SelectionState.restore(catalog(), "nope", "local")

	assert state.provider_group == COSEEING_GROUP
	assert state.current_item().corrector_config_id == "default"


def test_choosing_a_group_resets_the_model_index():
	state = SelectionState.restore(catalog(), "default", COSEEING_GROUP)
	coseeing_index = catalog().provider_groups.index(COSEEING_GROUP)
	state.choose_provider_group(coseeing_index)
	state.model_index = 1
	assert state.current_item().corrector_config_id == "ds-x&DeepSeek"

	state.choose_provider_group(0)

	assert state.provider_group == "DeepSeek"
	assert state.model_index == 0


def test_restore_raises_only_when_the_catalog_is_empty():
	empty = build_catalog({"schema_version": SCHEMA_VERSION}, runnable_providers=RUNNABLE)

	with pytest.raises(ValueError):
		SelectionState.restore(empty, "anything", "local")
