from typing import Any, List, Tuple

import logging
import requests
import time

from hanzidentifier import has_chinese
from .template import TEMPLATE_DICT

log = logging.getLogger(__name__)


class BaseTypoCorrector():

	def __init__(
		self,
		model: str,
		api_key: str,
		max_tokens: int = 2048,
		temperature: float = 0.0,
		top_p: float = 0.0,
		retries: int = 3,
		backoff: int = 1):

		self.model = model
		self.max_tokens = max_tokens
		self.temperature = temperature
		self.top_p = top_p
		self.retries = retries
		self.backoff = backoff

		self.url = "https://api.openai.com/v1/completions"
		self.headers = {"Authorization": f"Bearer {api_key}"}

	def correct_string(self, original_text: str, fake_operation: bool = False) -> str:
		if fake_operation or not has_chinese(original_text):
			return original_text

		corrected_text = None
		for template_index, template in enumerate(TEMPLATE_DICT[self.__class__.__name__]):
			try:
				prompt = template.replace("{{text_input}}", original_text)
				response_string = self._do_completion(prompt)

				if response_string is None:
					log.error(f"template {template_index} fails.\ntemplate = {template}")
					continue

				response = self._parse_response_string(response_string)
				is_valid = self._is_validate_response(response, original_text)

				if is_valid:
					corrected_text = self._correct_typos(original_text, response)
					break

				log.warning(f"response of template {template_index} is not valid")

			except Exception as e:
				log.error(f"An unexpected error occurred: {e}")

		return corrected_text

	def _do_completion(self, prompt: str) -> str:
		data = {
			'model': self.model,
			'prompt': prompt,
			'max_tokens': self.max_tokens,
			'temperature': self.temperature,
			'top_p': self.top_p,
		}

		for r in range(self.retries):
			response = requests.post(self.url, headers=self.headers, json=data)
			if response.status_code == 200:
				response = response.json()
				return response['choices'][0]['text']

			log.error(f"Retry = {r}, {response}, error: {response.reason}")
			time.sleep(self.backoff)

		return None

	def _parse_response_string(self, response_string: str):
		raise NotImplementedError("Subclass must implement this method")

	def _is_validate_response(self, response: Any, original_text: str):
		raise NotImplementedError("Subclass must implement this method")

	def _correct_typos(self, original_text: str, response: Any):
		raise NotImplementedError("Subclass must implement this method")


class TypoCorrector(BaseTypoCorrector):

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)

	def _parse_response_string(self, response_string: str) -> str:
		return response_string

	def _is_validate_response(self, response: str, original_text: str) -> bool:
		return True

	def _correct_typos(self, original_text: str, response: str):
		return response


# Todo: Implement the TypoIdentifier
class TypoIdentifier(BaseTypoCorrector):

	def __init__():
		pass

	def _parse_response_string(self, responsse_string: str) -> List[Tuple]:
		raise NotImplementedError("Subclass must implement this method")

	def _is_validate_response(self, response: Any, original_text: str):
		raise NotImplementedError("Subclass must implement this method")

	def _correct_typos(self, original_text: str, response: Any):
		raise NotImplementedError("Subclass must implement this method")