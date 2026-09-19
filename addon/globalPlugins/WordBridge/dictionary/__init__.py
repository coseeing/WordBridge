import os


user_folder = os.path.dirname(
	os.path.dirname(
		os.path.dirname(
			os.path.dirname(
				os.path.dirname(
					os.path.dirname(__file__)
				)
			)
		)
	)
)
WBW_DICTIONARY_PATH = os.path.join(user_folder, "WordBridge-workspace", "dictionary")
os.makedirs(WBW_DICTIONARY_PATH, exist_ok=True)
