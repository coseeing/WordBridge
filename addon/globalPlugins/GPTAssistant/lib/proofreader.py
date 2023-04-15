from typing import Tuple
from .utils import strings_diff, text_segmentation
from .typo_corrector import TypoCorrector


class Proofreader():
	"""
	A class that provides a proofreading tool to refine texts.

	Parameters:
		segment_corrector (TypoCorrector): An instance of the TypoCorrector class that will be used to correct typos
										   in the input text.
	"""

	def __init__(self, segment_corrector: TypoCorrector):
		self.segment_corrector = segment_corrector

	def typo_analyzer(self, text: str, fake_operation: bool = False) -> Tuple:
		"""
		Analyzes the input text for typos and corrects them using the TypoCorrector instance passed to the Proofreader
		constructor. It also calculates the difference between the original and corrected text.

		Parameters:
			text (str): The text to be analyzed for typos.
			fake_operation (bool): If True, the function will not perform any corrections and will return the input text
								   unchanged.

		Returns:
			A tuple containing the corrected text and a list of differences between the original and corrected text.
		"""
		text_corrected = ""
		for segment in text_segmentation(text):
			segment_corrected = self.segment_corrector.correct_string(segment, fake_operation)
			if segment_corrected is None:
				text_corrected += ("■" * len(segment))
				continue
			text_corrected += segment_corrected

		diff = strings_diff(text, text_corrected)

		return text_corrected, diff
