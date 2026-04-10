import json
import logging
import random
import time
from pathlib import Path

import requests
from requests.utils import urlparse

def _(s):
	return s

try:
	import addonHandler
	addonHandler.initTranslation()
except ImportError:
	pass


log = logging.getLogger(__name__)


class Provider:
	def __init__(self, credential: dict, retries: int = 2, backoff: int = 1):
		self.credential = credential
		self.retries = retries
		self.backoff = backoff

		setting_path = Path(__file__).resolve().parents[2] / "setting" / "provider" / f"{self.name}.json"
		with setting_path.open("r", encoding="utf8") as f:
			data = json.load(f)
			self.url = data["url"]
			self.setting = data["setting"]
			self.timeout0 = data["timeout0"]
			self.timeout_max = data["timeout_max"]

	@property
	def base_url(self):
		parse = urlparse(self.url)
		return f"{parse.scheme}://{parse.netloc}"

	def get_headers(self):
		return {
			"Content-Type": "application/json",
			"Authorization": f"Bearer {self.credential['api_key']}",
		}

	def get_api_url(self, model_name=None):
		return self.url

	def handle_errors(self, response):
		if response.status_code != 200:
			if response.status_code == 401:
				raise Exception(_("Authentication error. Please check if the service provider's key is correct."))
			if response.status_code == 403:
				raise Exception(_("Country, region, or territory not supported."))
			if response.status_code == 404:
				raise Exception(_("Service does not exist. Please check if the model does not exist or has expired."))
			if response.status_code == 429:
				raise Exception(
					_("Rate limit reached for requests or you exceeded your current quota. ")
					+ _("Please reduce the frequency of sending requests or check your account balance.")
				)
			if response.status_code == 503:
				raise Exception(_("The server is currently overloaded, please try again later."))
			message = json.loads(response.text)["error"]["message"]
			raise Exception(
				_("An error occurred, status code = ") + "{status_code}, {message}".format(
					status_code=response.status_code,
					message=message,
				)
			)

	def try_connection(self, timeout=10, try_count=1):
		url = self.base_url
		request_error = "Unknown"
		for r in range(try_count):
			try:
				requests.get(url, timeout=timeout)
				return
			except Exception as e:
				request_error = type(e).__name__
				log.error(
					"Try = {try_index}, {request_error}, an error occurred when sending request: {e}".format(
						try_index=(r + 1),
						request_error=request_error,
						e=e,
					)
				)

		raise Exception(
			_("HTTP request error ({request_error}). Please check the network setting.").format(
				request_error=request_error
			)
		)

	def send(self, payload, model_name=None):
		api_url = self.get_api_url(model_name=model_name)
		headers = self.get_headers()

		current_backoff = self.backoff
		response = None
		request_error = None

		for r in range(self.retries):
			timeout = min(self.timeout0 * (r + 1), self.timeout_max)
			try:
				response = requests.post(
					api_url,
					headers=headers,
					json=payload,
					timeout=timeout,
				)
				break
			except Exception as e:
				request_error = type(e).__name__
				log.error(
					"Try = {try_index}, {request_error}, an error occurred when sending {provider} request: {e}".format(
						try_index=(r + 1),
						request_error=request_error,
						provider=self.name,
						e=e,
					)
				)
				current_backoff = min(current_backoff * (1 + random.random()), 3)
				time.sleep(current_backoff)

		if response is None:
			raise Exception(
				_("HTTP request error ({request_error}). Please check the network setting.").format(
					request_error=request_error
				)
			)

		self.handle_errors(response)
		return response.json()

	def chat_completion(self, payload):
		return self.send(payload)


class OpenaiProvider(Provider):
	name = "OpenAI"


class AnthropicProvider(Provider):
	name = "Anthropic"

	def get_headers(self):
		return {
			"Content-Type": "application/json",
			"anthropic-version": "2023-06-01",
			"x-api-key": f"{self.credential['api_key']}",
		}


class GoogleProvider(Provider):
	name = "Google"

	def get_headers(self):
		return {
			"Content-Type": "application/json",
		}

	def get_api_url(self, model_name=None):
		if not model_name:
			raise ValueError("Google provider requires model_name when sending a request")
		return f"{self.url}/models/{model_name}:generateContent?key={self.credential['api_key']}"


class OpenrouterProvider(Provider):
	name = "OpenRouter"


class DeepseekProvider(Provider):
	name = "DeepSeek"


def get_provider(provider_name: str, credential: dict, retries: int = 2, backoff: int = 1) -> Provider:
	provider_mapping = {
		"OpenAI": OpenaiProvider,
		"Anthropic": AnthropicProvider,
		"DeepSeek": DeepseekProvider,
		"Google": GoogleProvider,
		"OpenRouter": OpenrouterProvider,
	}

	provider_class = provider_mapping.get(provider_name)
	if not provider_class:
		raise ValueError(f"Unsupported provider: {provider_name}")

	return provider_class(credential, retries=retries, backoff=backoff)
