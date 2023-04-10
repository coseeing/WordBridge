from typing import Any, List, Tuple

import requests

from hanzidentifier import has_chinese
from utils import rstrip_seperator
from template import TEMPLATE_DICT


class BaseTypoCorrector():

	def __init__(
		self,
		model: str,
		api_key: str,
		max_tokens: int = 2048,
		temperature: float = 0.0,
		top_p: float = 0.0):

		self.model = model
		self.max_tokens = max_tokens
		self.temperature = temperature
		self.top_p = top_p

		self.url = "https://api.openai.com/v1/completions"
		self.headers = {"Authorization": f"Bearer {api_key}"}

	def correct_string(self, original_text: str, fake_operation: bool = False) -> str:
		if fake_operation or not has_chinese(original_text):
			return original_text

		for template in TEMPLATE_DICT[self.__class__.__name__]:
			prompt = template.replace("{{text_input}}", original_text)
			response_string = self._do_completion(prompt)
			response = self._parse_response_string(response_string)
			is_valid = self._is_validate_response(response, original_text)

			if is_valid:
				corrected_text = self._correct_typos(original_text, response)
				break

		return corrected_text

	def _do_completion(self, prompt: str) -> str:
		data = {
			'model': self.model,
			'prompt': prompt,
			'max_tokens': self.max_tokens,
			'temperature': self.temperature,
			'top_p': self.top_p,
		}

		response = requests.post(self.url, headers=self.headers, json=data).json()
		return response['choices'][0]['text']

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
		corrected_text = original_text
		response = rstrip_seperator(response)

		return response + original_text[len(response):]


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
