from typing import Tuple
from .utils import strings_diff, text_segmentation
from .typo_corrector import TypoCorrector


class Proofreader():

	def __init__(self, segment_corrector: TypoCorrector):
		self.segment_corrector = segment_corrector

	def typo_analyzer(self, text: str, fake_operation: bool = False) -> Tuple:
		text_corrected = ""
		for segment in text_segmentation(text):
			segment_corrected = self.segment_corrector.correct_string(segment, fake_operation)
			if segment_corrected is None:
				text_corrected += ("☐" * len(segment))
				continue
			text_corrected += segment_corrected

		diff = strings_diff(text, text_corrected)

		return text_corrected, diff


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
