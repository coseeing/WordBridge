import json
import logging
import random
import time

import requests
from requests.utils import urlparse

from .errors import LLMServiceError

try:
	import addonHandler

	addonHandler.initTranslation()
except ImportError:
	pass

# initTranslation() installs _ into builtins. A module-level def would shadow
# it, so only define a fallback when no _ is reachable at all -- which is the
# case outside NVDA, for example when workspace/evals imports this module.
try:
	_  # noqa: B018
except NameError:

	def _(s):
		return s


log = logging.getLogger(__name__)


def _error_detail(response) -> str:
	"""The provider's error.message, or else the HTTP reason, never the body.

	Error bodies are not always the documented JSON (a proxy's HTML page, an
	empty body, another shape); the body itself is never shown.
	"""
	try:
		document = json.loads(response.text)
	except (TypeError, ValueError):
		document = None
	error = document.get("error") if isinstance(document, dict) else None
	message = error.get("message") if isinstance(error, dict) else None
	if isinstance(message, str):
		return message
	return getattr(response, "reason", None) or ""


class Provider:
	def __init__(self, credential: dict, retries: int = 2, backoff: int = 1, *, provider_entry):
		self.credential = credential
		self.retries = retries
		self.backoff = backoff

		# Injected, never read from disk: the live catalog may come from a
		# remote source, and a second file-reading path here would silently
		# diverge from it.
		self.url = provider_entry.url
		self.setting = provider_entry.setting
		self.timeout0 = provider_entry.timeout0
		self.timeout_max = provider_entry.timeout_max

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
				raise LLMServiceError(
					# Translators: Reported when the AI service provider rejects the user's API key (HTTP 401).
					_("Authentication error. Please check if the service provider's key is correct."),
					kind="configuration",
				)
			if response.status_code == 403:
				raise LLMServiceError(
					# Translators: Reported when the AI service provider refuses requests from the user's location
					# (HTTP 403).
					_("Country, region, or territory not supported."),
					kind="configuration",
				)
			if response.status_code == 404:
				raise LLMServiceError(
					# Translators: Reported when the AI service provider does not know the selected model (HTTP 404).
					_("Service does not exist. Please check if the model does not exist or has expired."),
					kind="configuration",
				)
			if response.status_code == 429:
				raise LLMServiceError(
					# Translators: First sentence reported when the AI service provider limits the user's requests
					# (HTTP 429); the next sentence follows it directly, so keep the trailing space.
					_("Rate limit reached for requests or you exceeded your current quota. ")
					# Translators: Second sentence reported when the AI service provider limits the user's requests
					# (HTTP 429).
					+ _("Please reduce the frequency of sending requests or check your account balance."),
					kind="rate_limited",
				)
			if response.status_code == 503:
				raise LLMServiceError(
					# Translators: Reported when the AI service provider is too busy to answer (HTTP 503).
					_("The server is currently overloaded, please try again later."),
					kind="overloaded",
				)
			raise LLMServiceError(
				# Translators: Reported for any other error from the AI service provider; the HTTP status code
				# and the provider's own (untranslated) message follow it, as "401, message".
				_("An error occurred, status code = ") + f"{response.status_code}, {_error_detail(response)}",
				# Anthropic answers 529 when it is overloaded.
				kind="overloaded" if response.status_code == 529 else "other",
			)

	def try_connection(self, timeout=10, try_count=1):
		url = self.base_url
		request_error = "Unknown"
		for r in range(try_count):
			try:
				requests.get(url, timeout=timeout)
				return
			except Exception as e:  # noqa: BLE001
				request_error = type(e).__name__
				# Only the exception type: str() of a requests exception
				# carries the request URL, and a URL may carry a credential.
				log.error(
					"Try = %d, %s, an error occurred when sending %s request",
					r + 1,
					request_error,
					self.name,
				)

		raise LLMServiceError(
			# Translators: Reported when the AI service provider cannot be reached; {request_error} is the
			# name of the network error, for example ConnectTimeout.
			_("HTTP request error ({request_error}). Please check the network setting.").format(
				request_error=request_error,
			),
			kind="unreachable",
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
			except Exception as e:  # noqa: BLE001
				request_error = type(e).__name__
				# Same rule as try_connection(): never str(e).
				log.error(
					"Try = %d, %s, an error occurred when sending %s request",
					r + 1,
					request_error,
					self.name,
				)
				current_backoff = min(current_backoff * (1 + random.random()), 3)
				time.sleep(current_backoff)

		if response is None:
			raise LLMServiceError(
				# Translators: Reported when the AI service provider cannot be reached; {request_error} is the
				# name of the network error, for example ConnectTimeout.
				_("HTTP request error ({request_error}). Please check the network setting.").format(
					request_error=request_error,
				),
				kind="unreachable",
			)

		self.handle_errors(response)
		return response.json()

	def chat_completion(self, payload):
		return self.send(payload)


class OpenAIProvider(Provider):
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
		# The key goes in a header, never the URL query: requests puts the
		# full URL into the text of its exceptions, so a key in the query
		# ends up wherever that text is logged or shown.
		return {
			"Content-Type": "application/json",
			"x-goog-api-key": f"{self.credential['api_key']}",
		}

	def get_api_url(self, model_name=None):
		if not model_name:
			raise ValueError("Google provider requires model_name when sending a request")
		return f"{self.url}/models/{model_name}:generateContent"


class OpenrouterProvider(Provider):
	name = "OpenRouter"


class DeepseekProvider(Provider):
	name = "DeepSeek"


class OllamaProvider(Provider):
	name = "Ollama"


PROVIDER_CLASSES = {
	"OpenAI": OpenAIProvider,
	"Anthropic": AnthropicProvider,
	"DeepSeek": DeepseekProvider,
	"Ollama": OllamaProvider,
	"Google": GoogleProvider,
	"OpenRouter": OpenrouterProvider,
}


def get_provider(
	provider_name: str,
	credential: dict,
	retries: int = 2,
	backoff: int = 1,
	*,
	provider_entry,
) -> Provider:
	provider_class = PROVIDER_CLASSES.get(provider_name)
	if not provider_class:
		raise ValueError(f"Unsupported provider: {provider_name}")

	return provider_class(credential, retries=retries, backoff=backoff, provider_entry=provider_entry)
