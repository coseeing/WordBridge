import logging
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

	def ensure_connection(self):
		self.provider_object.try_connection()

	def execute(self, input_text: str, prompt_strategy, text_policy, previous_results: list | None = None) -> LLMExecutionResult:
		previous_results = previous_results or []
		if not text_policy.has_target_language(input_text):
			return LLMExecutionResult(input_text, input_text, {}, {})

		messages, system_template = prompt_strategy.compose(
			input_text=input_text,
			response_text_history=previous_results,
			text_policy=text_policy,
		)
		payload = self.adapter_object.format_request(
			messages=messages,
			system_template=system_template,
			setting=self.provider_object.setting,
		)
		response_json = self.provider_object.send(
			payload,
			model_name=self.adapter_object.model_name,
		)
		try:
			sentence = self.adapter_object.parse_response(response_json)
		except KeyError:
			log.error("%s", response_json)
			raise Exception(_(f"Parsing error. Unexpected server response. Response: {response_json}"))

		response_text = text_policy.normalize_response(sentence)
		output_text = text_policy.postprocess_output(response_text, input_text)
		usage = self.adapter_object.extract_usage(response_json)

		self.response_history.append(response_json)
		self.usage_history.append(usage)
		return LLMExecutionResult(
			original_text=input_text,
			output_text=output_text,
			raw_response=response_json,
			usage=usage,
		)

	def get_total_usage(self) -> dict:
		return self.adapter_object.get_total_usage(self.usage_history)

	def get_total_cost(self) -> Decimal:
		return self.adapter_object.get_total_cost(self.usage_history)
