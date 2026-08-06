import logging
import time
from decimal import Decimal

from .result import LLMExecutionResult

try:
	import addonHandler
	addonHandler.initTranslation()
except ImportError:
	def _(s):
		return s


log = logging.getLogger(__name__)


class LLMExecutor:
	def __init__(self, provider_object, adapter_object):
		self.provider_object = provider_object
		self.adapter_object = adapter_object
		self.response_history = []
		self.usage_history = []
		self.execution_history = []

	def ensure_connection(self):
		self.provider_object.try_connection()

	def execute(self, input_text: str, prompt_strategy, text_policy, previous_results: list | None = None) -> LLMExecutionResult:
		previous_results = previous_results or []
		if not text_policy.has_target_language(input_text):
			return LLMExecutionResult(input_text, input_text, {}, {})

		prompt_bundle = prompt_strategy.compose(
			input_text=input_text,
			response_text_history=previous_results,
			text_policy=text_policy,
		)
		payload = self.adapter_object.format_request(
			prompt_bundle=prompt_bundle,
			setting=self.provider_object.setting,
		)
		start_time = time.perf_counter()
		response_json = self.provider_object.send(
			payload,
			model_name=self.adapter_object.model_name,
		)
		latency_ms = (time.perf_counter() - start_time) * 1000
		try:
			sentence = self.adapter_object.parse_response(response_json)
		except KeyError:
			log.error("%s", response_json)
			raise Exception(_(f"Parsing error. Unexpected server response. Response: {response_json}"))

		response_text = text_policy.normalize_response(sentence)
		output_text = text_policy.postprocess_output(response_text, input_text)
		raw_usage = self.adapter_object.extract_usage(response_json)
		usage = raw_usage.copy() if isinstance(raw_usage, dict) else {}
		request_cost = self.adapter_object.get_cost_for_usage(usage) if usage else Decimal("0")

		self.response_history.append(response_json)
		self.usage_history.append(usage)
		result = LLMExecutionResult(
			original_text=input_text,
			output_text=output_text,
			request_payload=payload,
			raw_response=response_json,
			usage=usage,
			raw_usage=raw_usage,
			latency_ms=latency_ms,
			request_cost=request_cost,
		)
		self.execution_history.append(self._build_execution_record(result))
		return result

	def get_total_usage(self) -> dict:
		return self.adapter_object.get_total_usage(self.usage_history)

	def get_total_cost(self) -> Decimal:
		return self.adapter_object.get_total_cost(self.usage_history)

	def get_execution_metrics(self) -> list[dict]:
		return [record.copy() for record in self.execution_history]

	def _build_execution_record(self, result: LLMExecutionResult) -> dict:
		return {
			"original_text": result.original_text,
			"output_text": result.output_text,
			"request_payload": result.request_payload,
			"raw_response": result.raw_response,
			"usage": result.usage,
			"raw_usage": result.raw_usage,
			"latency_ms": result.latency_ms,
			"request_cost": str(result.request_cost),
		}
