from collections import defaultdict
from typing import Dict, Tuple
from .utils import strings_diff, text_segmentation
from .typo_corrector import TypoCorrector


class Proofreader():
	"""
	A class that provides a proofreading tool to refine texts.

	Parameters:
		segment_corrector (TypoCorrector): An instance of the TypoCorrector for correcting typos in the input text.
	"""

	def __init__(self, segment_corrector: TypoCorrector):
		self.segment_corrector = segment_corrector

	def get_total_usage(self) -> Dict:
		total_usage = defaultdict(int)
		for history in self.segment_corrector.usage_history:
			for count in history[1]["usage"].keys():
				total_usage[count] += history[1]["usage"][count]
		return total_usage

	def typo_analyzer(self, text: str, fake_corrected_text: str = None) -> Tuple:
		"""
		Analyze the input text's typos and corrects them using the TypoCorrector instance passed to the Proofreader
		constructor. It also calculates the difference between the original and corrected text.

		Parameters:
			text (str): The text to be analyzed for typos.
			fake_corrected_text (str, optional): If specified, the function will return this text as the corrected
												text instead of correcting the input text.

		Returns:
			A tuple containing the corrected text and a list of differences between the original and corrected text.
		"""
		if fake_corrected_text is not None:
			return fake_corrected_text, strings_diff(text, fake_corrected_text)

		text_corrected = ""
		segments, separators = text_segmentation(text)
		for segment, separator in zip(segments, separators):
			segment_corrected = self.segment_corrector.correct_string(segment)
			if segment_corrected is None:
				text_corrected += ("■" * len(segment))
				continue
			text_corrected += (segment_corrected + separator)
		diff = strings_diff(text, text_corrected)

		return text_corrected, diff
