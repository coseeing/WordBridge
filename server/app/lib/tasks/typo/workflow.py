import time

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
		start_time = time.perf_counter()
		self.executor.ensure_connection()

		text_corrected = ""
		segments = text_segmentation(input_text, max_length=100)

		if batch_mode:
			results = parallel_map(self._execute_segment, segments)
		else:
			results = [self._execute_segment(segment) for segment in segments]

		for res in results:
			text_corrected += res.output_text

		# Keyed by segment text, not by index: the text is re-segmented every
		# round, so a list index means a different segment from one round to
		# the next. The history answers "you have already tried these for this
		# text", which is a property of the text.
		recorrection_history: dict[str, list[str]] = {}
		for i in range(self.max_correction_attempts):
			text_corrected_revised, typo_indices = find_correction_errors(input_text, text_corrected)
			if text_corrected_revised == text_corrected:
				break

			text_corrected = ""
			segments_revised = text_segmentation(text_corrected_revised, max_length=20)

			segments_to_recorrect = get_segments_to_recorrect(segments_revised, typo_indices)
			use_history = i >= self.max_correction_attempts / 3
			history_for_correction = [
				recorrection_history.get(segment, []) if use_history else []
				for segment in segments_revised
			]

			if batch_mode:
				results = parallel_map(
					self._execute_segment,
					segments_to_recorrect,
					iterable_kwargs=[{"previous_results": h} for h in history_for_correction],
				)
			else:
				results = [
					self._execute_segment(seg, h)
					for seg, h in zip(segments_to_recorrect, history_for_correction, strict=True)
				]

			for segment, result in zip(segments_revised, results, strict=True):
				if result.output_text:
					res_text = result.output_text
					text_corrected += res_text
					history = recorrection_history.setdefault(segment, [])
					if res_text not in history and len(res_text) < len(input_text) * 2:
						history.append(res_text)
				else:
					text_corrected += segment

		final_text = review_correction_errors(input_text, text_corrected)
		diff = strings_diff(input_text, final_text)
		usage_summary = self.executor.get_total_usage()
		total_cost = self.executor.get_total_cost()
		request_metrics = self.executor.get_execution_metrics()
		total_latency_ms = (time.perf_counter() - start_time) * 1000
		return TypoCorrectionResult(
			corrected_text=final_text,
			diff=diff,
			usage_summary=usage_summary,
			cost=total_cost,
			raw_data={
				"metrics": {
					"request_count": len(request_metrics),
					"total_latency_ms": total_latency_ms,
					"llm_latency_ms": sum(item.get("latency_ms", 0) for item in request_metrics),
				},
				"usage_summary": usage_summary,
				"cost": str(total_cost),
				"requests": request_metrics,
			},
		)

	def _execute_segment(self, input_text: str, previous_results: list | None = None):
		return self.executor.execute(
			input_text=input_text,
			prompt_strategy=self.prompt_strategy,
			text_policy=self.text_policy,
			previous_results=previous_results,
		)
