from collections import defaultdict
from typing import Dict, Tuple
from .utils import strings_diff, text_segmentation
from .typo_corrector import BaseTypoCorrector


class Proofreader():
	"""
	A class that provides a proofreading tool to refine texts.

	Parameters:
		segment_corrector (BaseTypoCorrector): An instance of a typo corrector for correcting typos of texts.
	"""

	def __init__(self, segment_corrector: BaseTypoCorrector):
		self.segment_corrector = segment_corrector
		self.response_history = []

	def get_total_usage(self) -> Dict:
		"""
		Get the total usage of OpenAI model (in tokens)

		Returns:
			The total usage of OpenAI model (in tokens)
		"""
		total_usage = defaultdict(int)
		for response in self.response_history:
			for usage_type in response["usage"].keys():
				total_usage[usage_type] += response["usage"][usage_type]
		return total_usage

	def typo_analyzer(self, text: str, batch_mode: bool = True, fake_corrected_text: str = None) -> Tuple:
		"""
		Analyze typos of text using self.segment_corrector. It also analyzes the difference between the original
		text and corrected text.

		Parameters:
			text (str): The text to be analyzed for typos.
			batch_mode (bool): If specified, enable multithread for typo correction
			fake_corrected_text (str, optional): If specified, return input text without correction steps.

		Returns:
			A tuple containing the corrected text and a list of differences between the original and corrected text.
		"""
		if fake_corrected_text is not None:
			return fake_corrected_text, strings_diff(text, fake_corrected_text)

		text_corrected = ""
		segments = text_segmentation(text)

		if batch_mode:
			corrector_result_list = self.segment_corrector.correct_segment_batch(segments)
		else:
			corrector_result_list = [self.segment_corrector.correct_segment(segment) for segment in segments]
		for corrector_result in corrector_result_list:
			text_corrected += corrector_result.corrected_text
			self.response_history.extend(corrector_result.response_history)
		diff = strings_diff(text, text_corrected)

		return text_corrected, diff
