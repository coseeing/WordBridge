import json
import os
import sys
import time


path = os.path.dirname(__file__)
api_path = os.path.join(path, "..", "..", "addon", "globalPlugins", "WordBridge")
sys.path.insert(0, api_path)

from lib.typo_corrector import ChineseTypoCorrector, ChineseTypoCorrectorLite


"""
This is a quick example program that demonstrates how to use the ChineseTypoCorrector classes to
1. Correct typos in a sample text string
2. Analyze the differences between original and corrected texts
"""
if __name__ == "__main__":

	# Input text
	text = "天器真好，想出去完"

	# Settings
	model = "mistral-nemo"
	provider = "Ollama"
	typo_corrector_class = ChineseTypoCorrector
	language = "zh_traditional"
	template_name = "Standard_v3.json"
	optional_guidance_enable = {
		"no_explanation": True,
		"keep_non_chinese_char": False,
	}
	customized_words = []
	credential = None
	if provider.lower() != "ollama":
		with open(os.path.join(path, "config.json"), "r", encoding="utf8") as f:
			credential = json.loads(f.read())[provider]

	# Initialize the typo corrector object with the OpenAI API key and the GPT model
	start_time = time.time()
	corrector = typo_corrector_class(
		model=model,
		provider=provider,
		credential=credential,
		language=language,
		template_name=template_name,
		optional_guidance_enable=optional_guidance_enable,
		customized_words=customized_words,
	)


	text_corrected, diff = corrector.correct_text(text)
	print(f"text = {text}, text_corrected = {text_corrected}, diff = {diff}")
	print(f"time elapses = {time.time() - start_time} s")
	print("Token Usage:")
	usage = corrector.get_total_usage()
	for k in usage:
		print(f"{k} = {usage[k]}")

"""
Output:
text = 天器真好，想出去完,
text_corrected = 天氣真好，想出去玩,
diff = [
	{
		"operation": "equal",
		"before_text": "天",
		"after_text": "天",
		"index_start_before": 0,
		"index_end_before": 1,
		"index_start_after": 0,
		"index_end_after": 1,
		"before_descs": "",
		"after_descs": "",
		"tags": None
	},
	{
		"operation": "replace",
		"before_text": "器",
		"after_text": "氣",
		"index_start_before": 1,
		"index_end_before": 2,
		"index_start_after": 1,
		"index_end_after": 2,
		"before_descs": "",
		"after_descs": "",
		"tags": ["Share the same pronunciation"]
	},
	{
		"operation": "equal",
		"before_text": "真好，想出去",
		"after_text": "真好 ，想出去",
		"index_start_before": 2,
		"index_end_before": 8,
		"index_start_after": 2,
		"index_end_after": 8,
		"before_descs": "",
		"after_descs": "",
		"tags": None
	},
	{
		"operation": "replace",
		"before_text": "完",
		"after_text": "玩",
		"index_start_before": 8,
		"index_end_before": 9,
		"index_start_after": 8,
		"index_end_after": 9,
		"before_descs": "",
		"after_descs": "",
		"tags": ["Share the same pronunciation"]
	}
]
"""
