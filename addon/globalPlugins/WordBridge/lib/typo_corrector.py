from decimal import Decimal
from typing import Dict, List, Tuple

import logging

from .utils import strings_diff, text_segmentation
from .utils import find_correction_errors, review_correction_errors, get_segments_to_recorrect, parallel_map


try:
	import addonHandler
	addonHandler.initTranslation()
except ImportError:
	def _(s):
		return s


log = logging.getLogger(__name__)


class CorrectorResult():
	def __init__(
		self,
		original_text: str,
		corrected_text: str,
		response_json: Dict,
		usage: Dict,
	):
		self.original_text = original_text
		self.corrected_text = corrected_text
		self.response_json = response_json
		self.usage = usage


class CorrectionOrchestrator:
	def __init__(self, corrector: 'ChineseTypoCorrector', max_correction_attempts: int = 3):
		self.corrector = corrector
		self.max_correction_attempts = max_correction_attempts

	def execute(self, text: str, batch_mode: bool = True) -> Tuple[str, List]:
		"""
		Orchestrate the full text correction process.
		
		Returns:
			A tuple containing the corrected text and a list of differences.
		"""
		self.corrector.provider_object.try_connection()

		# Initial correction pass
		text_corrected = ""
		segments = text_segmentation(text, max_length=100)

		if batch_mode:
			results = parallel_map(self.corrector.correct_segment, segments)
		else:
			results = [self.corrector.correct_segment(segment) for segment in segments]

		for res in results:
			text_corrected += res.corrected_text
			self.corrector.response_history.append(res.response_json)
			self.corrector.usage_history.append(res.usage)

		# Iterative refinement loop
		recorrection_history = None
		for i in range(self.max_correction_attempts):
			text_corrected_revised, typo_indices = find_correction_errors(text, text_corrected)

			# No more typos found, stable
			if text_corrected_revised == text_corrected:
				break

			text_corrected = ""
			segments_revised = text_segmentation(text_corrected_revised, max_length=20)
			if recorrection_history is None:
				recorrection_history = [[] for _ in range(len(segments_revised))]

			segments_to_recorrect = get_segments_to_recorrect(segments_revised, typo_indices)
			history_for_correction = recorrection_history if i >= self.max_correction_attempts / 3 else [[] for _ in range(len(segments_revised))]

			if batch_mode:
				results = parallel_map(
					self.corrector.correct_segment,
					segments_to_recorrect,
					iterable_kwargs=[{"previous_results": h} for h in history_for_correction]
				)
			else:
				results = [self.corrector.correct_segment(seg, h) for seg, h in zip(segments_to_recorrect, history_for_correction)]

			for j in range(len(segments_revised)):
				if results[j].corrected_text:
					res_text = results[j].corrected_text
					text_corrected += res_text
					if res_text not in recorrection_history[j] and len(res_text) < len(text) * 2:
						recorrection_history[j].append(res_text)
					self.corrector.response_history.append(results[j].response_json)
					self.corrector.usage_history.append(results[j].usage)
				else:
					text_corrected += segments_revised[j]

		final_text = review_correction_errors(text, text_corrected)
		diff = strings_diff(text, final_text)
		
		return final_text, diff


class ChineseTypoCorrector:

	def __init__(
		self,
		provider_object,
		adapter_object,
		instruction_composer,
		language_text_policy,
	):

		self.provider_object = provider_object
		self.adapter_object = adapter_object
		self.instruction_composer = instruction_composer
		self.language_text_policy = language_text_policy

		self.response_history = []
		self.usage_history = []

	def correct_segment(self, input_text: str, previous_results: list = []) -> CorrectorResult:
		if not self.language_text_policy.has_target_language(input_text):
			return CorrectorResult(input_text, input_text, {}, {})

		messages, system_template = self.instruction_composer.compose(
			input_text=input_text,
			response_text_history=previous_results,
			text_policy=self.language_text_policy,
		)

		response_json = self._chat_completion(messages, system_template)
		response_text = self._parse_response(response_json)
		output_text = self.language_text_policy.postprocess_output(response_text, input_text)

		return CorrectorResult(
			original_text=input_text,
			corrected_text=output_text,
			response_json=response_json,
			usage=self.adapter_object.extract_usage(response_json),
		)

	def get_total_usage(self) -> Dict:
		return self.adapter_object.get_total_usage(self.usage_history)

	def get_total_cost(self) -> Decimal:
		return self.adapter_object.get_total_cost(self.usage_history)

	def _chat_completion(self, messages: List, system_template: str) -> Dict:
		payload = self.adapter_object.format_request(
			messages=messages,
			system_template=system_template,
			setting=self.provider_object.setting,
		)

		return self.provider_object.send(
			payload,
			model_name=self.adapter_object.model_name,
		)

	def _parse_response(self, response: Dict) -> str:
		try:
			sentence = self.adapter_object.parse_response(response)
		except KeyError:
			log.error("%s", response)
			raise Exception(_(f"Parsing error. Unexpected server response. Response: {response}"))

		return self.language_text_policy.normalize_response(sentence)
