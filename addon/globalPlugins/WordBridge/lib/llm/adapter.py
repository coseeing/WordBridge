import json
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

from .cost_calculator import CostCalculator


class ProviderModelAdapter:
	def __init__(self, provider_name: str, model_name: str):
		self.provider_name = provider_name
		self.model_name = model_name
		self._model_entry = self._load_model_entry()
		self._cost_calculator = CostCalculator(self._model_entry)

	def format_request(self, messages, system_template, setting: dict):
		raise NotImplementedError("Subclass must implement this method")

	def parse_response(self, response):
		return response["choices"][0]["message"]["content"]

	def extract_usage(self, response):
		usage_key = self._model_entry.get("usage_key")
		if not usage_key:
			return {}
		return response.get(usage_key, {})

	def get_model_entry(self) -> dict:
		return self._model_entry

	def get_total_usage(self, usage_history: list) -> dict:
		return self._cost_calculator.get_total_usage(usage_history)

	def get_total_cost(self, usage_history: list) -> Decimal:
		return self._cost_calculator.get_total_cost(usage_history)

	def _load_model_entry(self) -> dict:
		config_path = Path(__file__).resolve().parents[2] / "setting" / "llm_models.json"
		with config_path.open("r", encoding="utf8") as f:
			config = json.load(f)
		return config.get(f"{self.model_name}&{self.provider_name}", {})


class OpenAIChatAdapter(ProviderModelAdapter):
	def format_request(self, messages, system_template, setting: dict):
		payload = deepcopy(setting)
		payload["model"] = self.model_name
		payload["messages"] = [{"role": "system", "content": system_template}] + deepcopy(messages)
		return payload


class OpenAIReasoningAdapter(ProviderModelAdapter):
	def format_request(self, messages, system_template, setting: dict):
		payload = deepcopy(setting)
		payload.pop("stop", None)
		payload.pop("temperature", None)
		payload.pop("top_p", None)

		messages = deepcopy(messages)
		messages[0]["content"] = system_template + "\n" + messages[0]["content"]

		payload["model"] = self.model_name
		payload["messages"] = messages
		return payload


class AnthropicAdapter(ProviderModelAdapter):
	def format_request(self, messages, system_template, setting: dict):
		return {
			"model": self.model_name,
			"system": system_template,
			"messages": deepcopy(messages),
			**deepcopy(setting),
		}

	def parse_response(self, response):
		return response["content"][0]["text"]


class GoogleAdapter(ProviderModelAdapter):
	def format_request(self, messages, system_template, setting: dict):
		contents = []
		for message in messages:
			role = "model" if message["role"] == "assistant" else "user"
			contents.append({"role": role, "parts": [{"text": message["content"]}]})
		return {
			"system_instruction": {"parts": [{"text": system_template}]},
			"contents": contents,
		}

	def parse_response(self, response):
		return response["candidates"][0]["content"]["parts"][0]["text"]


class OpenRouterAdapter(ProviderModelAdapter):
	def format_request(self, messages, system_template, setting: dict):
		return {
			"model": self.model_name,
			"messages": [{"role": "system", "content": system_template}] + deepcopy(messages),
			"stream": False,
			"options": {**deepcopy(setting)},
		}


class DeepSeekAdapter(ProviderModelAdapter):
	def format_request(self, messages, system_template, setting: dict):
		return {
			"model": self.model_name,
			"messages": [{"role": "system", "content": system_template}] + deepcopy(messages),
			"stream": False,
			"options": {**deepcopy(setting)},
		}


def get_provider_model_adapter(provider_name: str, model_name: str) -> ProviderModelAdapter:
	if provider_name == "OpenAI":
		if model_name.startswith("o") or model_name in ["gpt-5", "gpt-5-mini", "gpt-5-nano"]:
			return OpenAIReasoningAdapter(provider_name, model_name)
		return OpenAIChatAdapter(provider_name, model_name)

	family_mapping = {
		"Anthropic": AnthropicAdapter,
		"Google": GoogleAdapter,
		"OpenRouter": OpenRouterAdapter,
		"DeepSeek": DeepSeekAdapter,
	}
	adapter_class = family_mapping.get(provider_name)
	if not adapter_class:
		raise ValueError(f"Unsupported provider/model adapter: {provider_name}/{model_name}")
	return adapter_class(provider_name, model_name)
