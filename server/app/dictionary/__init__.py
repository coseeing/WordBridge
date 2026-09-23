import os

from ..lib.paths import user_workspace_root


WBW_DICTIONARY_PATH = os.path.join(str(user_workspace_root()), "dictionary")
os.makedirs(WBW_DICTIONARY_PATH, exist_ok=True)
