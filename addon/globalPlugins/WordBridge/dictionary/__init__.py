import os

from ..lib.paths import user_workspace_root
from .repository import DictionaryRepository


WBW_DICTIONARY_PATH = os.path.join(str(user_workspace_root()), "dictionary")
os.makedirs(WBW_DICTIONARY_PATH, exist_ok=True)


def default_dictionary_repository() -> DictionaryRepository:
	return DictionaryRepository(os.path.join(WBW_DICTIONARY_PATH, "data.csv"))
