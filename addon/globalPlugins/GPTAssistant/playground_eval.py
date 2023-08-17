import os

from lib.proofreader import Proofreader
from lib.typo_corrector import TypoCorrector


if __name__ == "__main__":

	model = "gpt-3.5-turbo"
	api_key = "OPENAI_API_KEY"
	is_chat_completion = True
	data_name = "gpt4_250_sentence_aug_err_0.1_41PJSO2KRV6SK1WJ6936.txt"
	groundtruth_name = "gpt4_250_sentence_gt.txt"
	tag = "fix_word_count_v2"

	data_path = os.path.join(".", "data", data_name)
	groundtruth_path = os.path.join(".", "data", groundtruth_name)

	result_file_name = f"eval_{model}_{tag}_{os.path.basename(data_path)}"
	result_folder_name = os.path.join('.', 'eval')
	result_path_path = os.path.join(result_folder_name, result_file_name)

	if not os.path.isdir(result_folder_name):
		os.makedirs(result_folder_name)

	# Initialize the typo corrector object with the OpenAI API key and the GPT model
	corrector = TypoCorrector(model=model, api_key=api_key, is_chat_completion=is_chat_completion)

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
			text_corrected, _ = proofreader.typo_analyzer(data[i])
			if text_corrected == groundtruth[i]:
				f.write(f"{data[i]} => {text_corrected}\n")
				print(f"{data[i]} => {text_corrected}")
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