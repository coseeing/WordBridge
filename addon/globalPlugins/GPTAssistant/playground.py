from lib.proofreader import Proofreader
from lib.typo_corrector import TypoCorrector


if __name__ == "__main__":
	corrector = TypoCorrector(model="text-davinci-003", api_key="OPENAI_API_KEY")
	proofreader = Proofreader(corrector)

	text = "天器真好，想出去完"
	text_corrected, diff = proofreader.typo_analyzer(text)
	print(f"text = {text}, text_corrected = {text_corrected}, diff = {diff}")

"""
Output:
text = 天器真好，想出去完,
text_corrected = 天氣真好，想出去玩,
diff = [{'operation': 'replace', 'index_start1': 1, 'index_end1': 2, 'index_start2': 1, 'index_end2': 2},
		{'operation': 'replace', 'index_start1': 8, 'index_end1': 9, 'index_start2': 8, 'index_end2': 9}]
"""
