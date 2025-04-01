import json
from pathlib import Path

from requests.utils import urlparse


class Provider:
	timeout0 = 10
	timeout_max = 20

	def __init__(self, llm_settings: dict = {}):
		self.llm_settings = llm_settings

		# Load default setting
		setting_path = Path(__file__).parent.parent / "llm_setting" / f"{self.name}.json"
		with setting_path.open("r", encoding="utf8") as f:
			self.setting = json.load(f)

		for k in self.llm_settings:
			self.setting[k] = self.llm_settings[k]

	@property
	def base_url(self):
		parse = urlparse(self.url)
		return f"{parse.scheme}://{parse.netloc}"
	def _get_headers(self, credential):
		return {
			"Content-Type": "application/json",
			"Authorization": f"Bearer {credential['api_key']}"
		}

	def get_request_data(self, messages, system_template, model):
		raise NotImplementedError("Subclass must implement this method")

	def parse_response(self, response):
		return response["choices"][0]["message"]["content"]

	def handle_errors(self, response):
		raise NotImplementedError("Subclass must implement this method")


class OpenaiProvider(Provider):
	name = "openai"
	url = "https://api.openai.com/v1/chat/completions"

	def get_request_data(self, messages, system_template, model):
		messages = [{"role": "system", "content": system_template}] + messages
		if model.startswith("o"):
			messages.pop(0)
			messages[0]["content"] = system_template + "\n" + messages[0]["content"]
			self.setting.pop("stop")
			self.setting.pop("temperature")
			self.setting.pop("top_p")

		data = {
			"model": model,
			"messages": messages,
			**self.setting,
		}

		return data


class AnthropicProvider(Provider):
	name = "anthropic"
	url = "https://api.anthropic.com/v1/messages"

	def get_headers(self, credential):
		return {
			"Content-Type": "application/json",
			"anthropic-version": "2023-06-01",
			"x-api-key": f"{credential['api_key']}",
		}

	def get_request_data(self, messages, system_template, model):
		data = {
			"model": model,
			"system": system_template,
			"messages": messages,
			**self.setting,
		}
		return data

	def parse_response(self, response):
		return response["content"][0]["text"]


class BaiduProvider(Provider):
	name = "baidu"
	url = "https://qianfan.baidubce.com/v2/chat/completions"

	def get_request_data(self, messages, system_template, model):
		messages = [{"role": "system", "content": system_template}] + messages
		if "temperature" in setting:
			setting["temperature"] = max(setting["temperature"], 0.0001)
		if "max_completion_tokens" in setting:
			setting["max_completion_tokens"] = min(setting["max_completion_tokens"], len(messages[-1]["content"]))
		data = {
			"model": model,
			"messages": messages,
			**self.setting,
		}
		return data


class OpenrouterProvider(Provider):
	name = "openrouter"
	url = "https://openrouter.ai/api/v1/chat/completions"

	def get_request_data(self, messages, system_template, model):
		messages = [{"role": "system", "content": system_template}] + messages
		data = {
			"model": model,
			"messages": messages,
			"stream": False,
			"options":{
				**self.setting,
			}
		}
		return data


class DeepseekProvider(Provider):
	name = "deepseek"
	url = "https://api.deepseek.com/chat/completions"
	timeout0 = 30
	timeout_max = 60

	def get_request_data(self, messages, system_template, model):
		messages = [{"role": "system", "content": system_template}] + messages
		data = {
			"model": model,
			"messages": messages,
			"stream": False,
			"options":{
				**self.setting,
			}
		}
		return data

