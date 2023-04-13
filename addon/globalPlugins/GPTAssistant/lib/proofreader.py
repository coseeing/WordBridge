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
