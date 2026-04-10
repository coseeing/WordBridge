from ..concurrency import parallel_map
from .utils import (
	find_correction_errors,
	get_segments_to_recorrect,
	review_correction_errors,
	strings_diff,
	text_segmentation,
)
from .result import TypoCorrectionResult


class TypoCorrectionWorkflow:
	def __init__(self, executor, prompt_strategy, text_policy, max_correction_attempts: int = 3):
		self.executor = executor
		self.prompt_strategy = prompt_strategy
		self.text_policy = text_policy
		self.max_correction_attempts = max_correction_attempts

	def run(self, input_text: str, batch_mode: bool = True) -> TypoCorrectionResult:
		self.executor.ensure_connection()

		text_corrected = ""
		segments = text_segmentation(input_text, max_length=100)

		if batch_mode:
			results = parallel_map(self._execute_segment, segments)
		else:
			results = [self._execute_segment(segment) for segment in segments]

		for res in results:
			text_corrected += res.output_text

		recorrection_history = None
		for i in range(self.max_correction_attempts):
			text_corrected_revised, typo_indices = find_correction_errors(input_text, text_corrected)
			if text_corrected_revised == text_corrected:
				break

			text_corrected = ""
			segments_revised = text_segmentation(text_corrected_revised, max_length=20)
			if recorrection_history is None:
				recorrection_history = [[] for _ in range(len(segments_revised))]

			segments_to_recorrect = get_segments_to_recorrect(segments_revised, typo_indices)
			history_for_correction = (
				recorrection_history if i >= self.max_correction_attempts / 3 else [[] for _ in range(len(segments_revised))]
			)

			if batch_mode:
				results = parallel_map(
					self._execute_segment,
					segments_to_recorrect,
					iterable_kwargs=[{"previous_results": h} for h in history_for_correction],
				)
			else:
				results = [
					self._execute_segment(seg, h)
					for seg, h in zip(segments_to_recorrect, history_for_correction)
				]

			for j in range(len(segments_revised)):
				if results[j].output_text:
					res_text = results[j].output_text
					text_corrected += res_text
					if res_text not in recorrection_history[j] and len(res_text) < len(input_text) * 2:
						recorrection_history[j].append(res_text)
				else:
					text_corrected += segments_revised[j]

		final_text = review_correction_errors(input_text, text_corrected)
		diff = strings_diff(input_text, final_text)
		return TypoCorrectionResult(
			corrected_text=final_text,
			diff=diff,
			usage_summary=self.executor.get_total_usage(),
			cost=self.executor.get_total_cost(),
		)

	def _execute_segment(self, input_text: str, previous_results: list | None = None):
		return self.executor.execute(
			input_text=input_text,
			prompt_strategy=self.prompt_strategy,
			text_policy=self.text_policy,
			previous_results=previous_results,
		)
