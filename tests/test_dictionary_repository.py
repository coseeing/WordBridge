import importlib.util
from pathlib import Path


ADDON_PATH = Path(__file__).resolve().parents[1] / "addon" / "globalPlugins" / "WordBridge"


def _load_repository_module():
	# Loaded by file, not through the dictionary package: the package's
	# __init__ creates the user workspace directory on import.
	spec = importlib.util.spec_from_file_location(
		"wordbridge_dictionary_repository_probe",
		ADDON_PATH / "dictionary" / "repository.py",
	)
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


DictionaryRepository = _load_repository_module().DictionaryRepository


def test_loading_a_missing_dictionary_creates_it_empty(tmp_path):
	path = tmp_path / "data.csv"

	assert DictionaryRepository(path).load() == []
	assert path.exists()


def test_saved_rows_load_back_unchanged(tmp_path):
	repository = DictionaryRepository(tmp_path / "data.csv")
	rows = [
		{"text": "螢幕閱讀器", "pronunciation": "ying2 mu4 yue4 du2 qi4"},
		{"text": "WordBridge, 字橋", "pronunciation": ""},
	]

	repository.save(rows)

	assert repository.load() == rows


def test_save_writes_only_the_known_columns(tmp_path):
	repository = DictionaryRepository(tmp_path / "data.csv")

	repository.save(iter([{"text": "爸爸", "pronunciation": "ba4 ba", "extra": "x"}, {"text": "旅遊"}]))

	assert repository.load() == [
		{"text": "爸爸", "pronunciation": "ba4 ba"},
		{"text": "旅遊", "pronunciation": ""},
	]
