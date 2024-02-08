import os
import sys

path = os.path.dirname(__file__)
PYTHON_PATH = os.path.join(path, "..", "..", "addon", "globalPlugins", "GPTAssistant", "lib")
sys.path.insert(0, PYTHON_PATH)

from proofreader import Proofreader
from typo_corrector import ChineseTypoCorrector


if __name__ == "__main__":

	model = "gpt-3.5-turbo"
	api_key = "<API_KEY>"
	api_base_url="https://api.openai.com"
	data_name = "gpt4_250_sentence_aug_err_0.1_41PJSO2KRV6SK1WJ6936.txt"
	groundtruth_name = "gpt4_250_sentence_gt.txt"
	tag = "2024-02-02"

	data_path = os.path.join(".", "data", data_name)
	groundtruth_path = os.path.join(".", "data", groundtruth_name)

	result_file_name = f"eval_{model}_{tag}_{os.path.basename(data_path)}"
	result_folder_name = os.path.join('.', 'eval')
	result_path_path = os.path.join(result_folder_name, result_file_name)

	if not os.path.isdir(result_folder_name):
		os.makedirs(result_folder_name)

	# Initialize the typo corrector object with the OpenAI API key and the GPT model
	corrector = ChineseTypoCorrector(
		model=model,
		access_token=api_key,
		api_base_url=api_base_url,
	)

	# Initialize the proofreader object using the typo corrector
	proofreader = Proofreader(corrector)

	with open(data_path, 'r') as f:
		data = f.readlines()
		data = [sentence.replace('\n', '') for sentence in data]

	with open(groundtruth_path, 'r') as f:
		groundtruth = f.readlines()
		groundtruth = [sentence.replace('\n', '') for sentence in groundtruth]

	assert len(data) == len(groundtruth)

	correct = 0
	with open(result_path_path, 'w') as f:
		for i in range(len(data)):
			while 1:
				try:
					text_corrected, _ = proofreader.typo_analyzer(data[i])
					break
				except:
					continue
			if text_corrected == groundtruth[i]:
				correct += 1
				continue
			f.write(f"{data[i]} => {text_corrected}, ans: {groundtruth[i]}\n")
			print(f"{data[i]} => {text_corrected}, ans: {groundtruth[i]}")

		f.write(f"\n\nAccuracy = {correct/len(data) * 100}%\n")
		print(f"\n\nAccuracy = {correct/len(data) * 100}%")

		usage = proofreader.get_total_usage()

		f.write(f"\n\nToken Usage:\n")
		print("Token Usage:")
		for k in usage:
			f.write(f"{k} = {usage[k]}\n")
			print(f"{k} = {usage[k]}")
