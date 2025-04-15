from copy import deepcopy
import json
from pathlib import Path

from requests.utils import urlparse

try:
	import addonHandler
	addonHandler.initTranslation()
except ImportError:
	def _(s):
		return s


class Provider:
	def __init__(self, credential: dict, model: str, llm_settings: dict = {}):
		self.credential = credential
		self.model = model
		self.llm_settings = llm_settings

		# Load default setting
		setting_path = Path(__file__).parent.parent / "setting" / "provider" / f"{self.name}.json"
		with setting_path.open("r", encoding="utf8") as f:
			data = json.load(f)
			self.url = data["url"]
			self.setting = data["setting"]
			self.timeout0 = data["timeout0"]
			self.timeout_max = data["timeout_max"]

		for k in llm_settings:
			self.setting[k] = llm_settings[k]

	def set(self, credential: dict, model: str):
		self.credential = credential
		self.model = model

	@property
	def base_url(self):
		parse = urlparse(self.url)
		return f"{parse.scheme}://{parse.netloc}"

	def get_headers(self):
		return {
			"Content-Type": "application/json",
			"Authorization": f"Bearer {self.credential['api_key']}"
		}

	def get_request_data(self, messages, system_template):
		raise NotImplementedError("Subclass must implement this method")

	def parse_response(self, response):
		return response["choices"][0]["message"]["content"]

	def handle_errors(self, response):
		if response.status_code != 200:
			if response.status_code == 401:
				raise Exception(_("Authentication error. Please check if the service provider's key is correct."))
			elif response.status_code == 403:
				raise Exception(_("Country, region, or territory not supported."))
			elif response.status_code == 404:
				raise Exception(_("Service does not exist. Please check if the model does not exist or has expired."))
			elif response.status_code == 429:
				raise Exception(
					_("Rate limit reached for requests or you exceeded your current quota. ") +\
					_("Please reduce the frequency of sending requests or check your account balance.")
				)
			elif response.status_code == 503:
				raise Exception(_("The server is currently overloaded, please try again later."))
			else:
				message = json.loads(response.text)["error"]["message"]
				raise Exception(_("An error occurred, status code = ") + "{status_code}, {message}".format(
					status_code=response.status_code,
					message=message
				))


class OpenaiProvider(Provider):
	name = "openai"

	def get_request_data(self, messages, system_template):
		messages = [{"role": "system", "content": system_template}] + messages
		setting = deepcopy(self.setting)
		if self.model.startswith("o"):
			messages.pop(0)
			messages[0]["content"] = system_template + "\n" + messages[0]["content"]
			setting.pop("stop")
			setting.pop("temperature")
			setting.pop("top_p")

		data = {
			"model": self.model,
			"messages": messages,
			**setting,
		}

		return data


class AnthropicProvider(Provider):
	name = "anthropic"

	def get_headers(self):
		return {
			"Content-Type": "application/json",
			"anthropic-version": "2023-06-01",
			"x-api-key": f"{self.credential['api_key']}",
		}

	def get_request_data(self, messages, system_template):
		data = {
			"model": self.model,
			"system": system_template,
			"messages": messages,
			**self.setting,
		}
		return data

	def parse_response(self, response):
		return response["content"][0]["text"]


class GoogleProvider(Provider):
	name = "google"

	def __init__(self, credential: dict, model: str, llm_settings: dict = {}):
		super().__init__(credential=credential, model=model, llm_settings=llm_settings)
		self.url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.credential['api_key']}"

	def get_headers(self):
		return {
			"Content-Type": "application/json",
		}

	def get_request_data(self, messages, system_template):
		contents = []
		for message in messages:
			if message["role"] == "assistant":
				contents.append({
					"role": "model",
					"parts": [
						{
							"text": message["content"]
						}
					]
				})
			else:
				contents.append({
					"role": "user",
					"parts": [
						{
							"text": message["content"]
						}
					]
				})

		data = {
			"system_instruction": {
				"parts": [
					{
						"text": system_template
					}
				]
			},
			"contents": contents
		}
		return data

	def parse_response(self, response):
		return response["candidates"][0]["content"]["parts"][0]["text"]


class BaiduProvider(Provider):
	name = "baidu"

	def get_request_data(self, messages, system_template):
		messages = [{"role": "system", "content": system_template}] + messages
		setting = deepcopy(self.setting)
		if "temperature" in setting:
			setting["temperature"] = max(setting["temperature"], 0.0001)
		if "max_completion_tokens" in setting:
			setting["max_completion_tokens"] = min(setting["max_completion_tokens"], len(messages[-1]["content"]))
		data = {
			"model": self.model,
			"messages": messages,
			**self.setting,
		}
		return data

	def handle_errors(self, response):
		response_json = response.json()
		if "error_code" in response_json or not response_json["choices"][0]["message"]["content"]:
			if response_json["error_code"] == 3:
				raise Exception(_("Service does not exist. Please check if the model does not exist or has expired."))
			elif response_json["error_code"] in [336000, 336100]:
				raise Exception(_("Service internal error, please try again later."))
			elif response_json["error_code"] in [18, 336501, 336502]:
				raise Exception(_("Usage limit exceeded, please try again later."))
			elif response_json["error_code"] == 17:
				raise Exception(_("Please check if the API has been activated and the current account has enough money"))
			elif not response_json["choices"][0]["message"]["content"]:
				raise Exception(_("Service does not exist. Please check if the model does not exist or has expired."))
			else:
				raise Exception(_("An error occurred, error code = ") + response_json["error_msg"])


class OpenrouterProvider(Provider):
	name = "openrouter"

	def get_request_data(self, messages, system_template):
		messages = [{"role": "system", "content": system_template}] + messages
		data = {
			"model": self.model,
			"messages": messages,
			"stream": False,
			"options":{
				**self.setting,
			}
		}
		return data


class DeepseekProvider(Provider):
	name = "deepseek"

	def get_request_data(self, messages, system_template):
		messages = [{"role": "system", "content": system_template}] + messages
		data = {
			"model": self.model,
			"messages": messages,
			"stream": False,
			"options":{
				**self.setting,
			}
		}
		return data

