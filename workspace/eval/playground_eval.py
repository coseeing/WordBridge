import json
import os
import sys

from tqdm import tqdm

import jiwer


path = os.path.dirname(__file__)
api_path = os.path.join(path, "..", "..", "addon", "globalPlugins", "WordBridge")
sys.path.insert(0, api_path)

from lib.proofreader import Proofreader
from lib.typo_corrector import ChineseTypoCorrector, ChineseTypoCorrectorLite


def generate_results(text, groundtruth, proofreader):
	text_corrected = []
	for i in tqdm(range(len(text))):
		output, _ = proofreader.typo_analyzer(text[i], batch_mode=False)
		text_corrected.append(output)

		# For debugging
		if text_corrected[i] not in groundtruth[i]:
			print(f"{text[i]} => {text_corrected[i]}, ans: {' or '.join(groundtruth[i])}")

	return text_corrected

if __name__ == "__main__":

	model = "gpt-4o-mini"
	provider = "OpenAI"
	typo_corrector_class = ChineseTypoCorrector
	language = "zh_traditional"
	template_name = "Standard_v1.json"
	optional_guidance_enable = {
		"no_explanation": False,
		"keep_non_chinese_char": True,
	}
	customized_words = []
	with open(os.path.join(path, "config.json"), "r", encoding="utf8") as f:
		credential = json.loads(f.read())[provider]
	data_name = "gpt4_250_sentence_aug_err_0.1_41PJSO2KRV6SK1WJ6936.txt"
	groundtruth_name = "gpt4_250_sentence_gt.txt"
	tag = "2024-07-28-gpt-4o-mini"

	data_path = os.path.join(".", "data", data_name)
	groundtruth_path = os.path.join(".", "data", groundtruth_name)

	eval_file_name = f"eval_{model}_{tag}_{os.path.basename(data_path)}"
	result_file_name = f"result_{model}_{tag}_{os.path.basename(data_path)}"
	eval_file_path = os.path.join(".", "eval", eval_file_name)
	result_file_path = os.path.join(".", "result", result_file_name)

	# Initialize the typo corrector object with the OpenAI API key and the GPT model
	corrector = typo_corrector_class(
		model=model,
		provider=provider,
		credential=credential,
		language=language,
		template_name=template_name,
		optional_guidance_enable=optional_guidance_enable,
		customized_words=customized_words,
	)

	# Initialize the proofreader object using the typo corrector
	proofreader = Proofreader(corrector)

	# Read testing data
	with open(data_path, 'r') as f:
		text = f.readlines()
		text = [sentence.replace('\n', '') for sentence in text]

	# Read ground truth
	with open(groundtruth_path, 'r') as f:
		groundtruth = f.readlines()
		groundtruth = [sentence.replace('\n', '').split('#') for sentence in groundtruth]

	assert len(text) == len(groundtruth)

	# Text correction
	if os.path.exists(result_file_path):
		with open(result_file_path, 'r') as f:
			results = f.readlines()
			text_corrected = [sentence.replace('\n', '') for sentence in results[:len(groundtruth)]]
	else:
		text_corrected = generate_results(text, groundtruth, proofreader)
		result_file = open(result_file_path, 'w')
		for i in range(len(text_corrected)):
			result_file.write(f"{text_corrected[i]}\n")

		usage = proofreader.get_total_usage()
		result_file.write(f"\n\nToken Usage:\n")
		print("Token Usage:")
		for k in usage:
			result_file.write(f"{k} = {usage[k]}\n")
			print(f"{k} = {usage[k]}")

		result_file.close()

	eval_file = open(eval_file_path, 'w')

	# Calculate accuracy
	correct_count = 0
	for i in range(len(text)):
		if text_corrected[i] in groundtruth[i]:
			correct_count += 1
			continue

		eval_file.write(f"{text[i]} => {text_corrected[i]}, ans: {groundtruth[i]}\n")

	# Calculate character error rate
	cer_sum = 0
	for i in range(len(text)):
		cer = min([jiwer.cer(gt, text_corrected[i]) for gt in groundtruth[i]])
		cer_sum += cer

	eval_file.write(f"\n\nAccuracy = {correct_count / len(text) * 100}%\n")
	print(f"Accuracy = {correct_count / len(text) * 100}%")

	eval_file.write(f"Character Error Rate = {cer_sum / len(text) * 100}%\n")
	print(f"Character Error Rate = {cer_sum / len(text) * 100}%")

	eval_file.close()