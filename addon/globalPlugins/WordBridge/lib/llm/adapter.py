import json
from abc import ABC, abstractmethod
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

from .cost_calculator import CostCalculator


class ProviderModelAdapter(ABC):
	def __init__(self, provider_name: str, model_name: str):
		self.provider_name = provider_name
		self.model_name = model_name
		self._model_entry = self._load_model_entry()
		self._cost_calculator = CostCalculator(self._model_entry)

	@abstractmethod
	def format_request(self, prompt_bundle, setting: dict):
		pass

	@abstractmethod
	def parse_response(self, response):
		pass

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

	def get_cost_for_usage(self, usage: dict) -> Decimal:
		return self._cost_calculator.get_total_cost([usage])

	def _load_model_entry(self) -> dict:
		config_path = Path(__file__).resolve().parents[2] / "setting" / "price.json"
		with config_path.open("r", encoding="utf8") as f:
			config = json.load(f)
		return config.get(f"{self.model_name}&{self.provider_name}", {})


class OpenAIAdapter(ProviderModelAdapter):
	def _build_input_item(self, message: dict) -> dict:
		content_type = "output_text" if message["role"] == "assistant" else "input_text"
		return {
			"role": message["role"],
			"content": [{"type": content_type, "text": message["content"]}],
		}

	def format_request(self, prompt_bundle, setting: dict):
		payload = deepcopy(setting)

		payload["model"] = self.model_name
		payload["instructions"] = prompt_bundle.system_template
		payload["input"] = [
			self._build_input_item(message)
			for message in deepcopy(prompt_bundle.messages)
		]
		return payload

	def parse_response(self, response):
		try:
			output_blocks = response["output"]
		except KeyError:
			if "output_text" in response:
				return response["output_text"]
			raise

		for block in output_blocks:
			if block.get("type") != "message":
				continue
			for content in block.get("content", []):
				if content.get("type") == "output_text":
					return content["text"]
		raise KeyError("No output_text found in Responses API payload")

class AnthropicAdapter(ProviderModelAdapter):
	def format_request(self, prompt_bundle, setting: dict):
		return {
			"model": self.model_name,
			"system": prompt_bundle.system_template,
			"messages": deepcopy(prompt_bundle.messages),
			**deepcopy(setting),
		}

	def parse_response(self, response):
		for block in response["content"]:
			if block.get("type") == "text":
				return block["text"]
		raise KeyError("No text block found in Anthropic API payload")


class GoogleAdapter(ProviderModelAdapter):
	def _build_generation_config(self, setting: dict) -> dict:
		generation_config = deepcopy(setting)

		if self.model_name.startswith("gemini-2.5-pro"):
			generation_config["thinkingConfig"] = {"thinkingBudget": 128}
		elif self.model_name.startswith("gemini-2.5-flash"):
			generation_config["thinkingConfig"] = {"thinkingBudget": 0}

		return generation_config

	def format_request(self, prompt_bundle, setting: dict):
		contents = []
		for message in prompt_bundle.messages:
			role = "model" if message["role"] == "assistant" else "user"
			contents.append({"role": role, "parts": [{"text": message["content"]}]})
		return {
			"system_instruction": {"parts": [{"text": prompt_bundle.system_template}]},
			"contents": contents,
			"generationConfig": self._build_generation_config(setting),
		}

	def parse_response(self, response):
		return response["candidates"][0]["content"]["parts"][0]["text"]


class OpenRouterAdapter(ProviderModelAdapter):
	def format_request(self, prompt_bundle, setting: dict):
		return {
			"model": self.model_name,
			"messages": [{"role": "system", "content": prompt_bundle.system_template}] + deepcopy(prompt_bundle.messages),
			"stream": False,
			"options": {**deepcopy(setting)},
		}

	def parse_response(self, response):
		return response["choices"][0]["message"]["content"]


class DeepSeekAdapter(ProviderModelAdapter):
	def format_request(self, prompt_bundle, setting: dict):
		payload = {
			"model": self.model_name,
			"messages": [{"role": "system", "content": prompt_bundle.system_template}] + deepcopy(prompt_bundle.messages),
			"stream": False,
			**deepcopy(setting),
		}
		return payload

	def parse_response(self, response):
		return response["choices"][0]["message"]["content"]


def get_provider_model_adapter(provider_name: str, model_name: str) -> ProviderModelAdapter:
	family_mapping = {
		"OpenAI": OpenAIAdapter,
		"Anthropic": AnthropicAdapter,
		"Google": GoogleAdapter,
		"OpenRouter": OpenRouterAdapter,
		"DeepSeek": DeepSeekAdapter,
	}
	adapter_class = family_mapping.get(provider_name)
	if not adapter_class:
		raise ValueError(f"Unsupported provider/model adapter: {provider_name}/{model_name}")
	return adapter_class(provider_name, model_name)
