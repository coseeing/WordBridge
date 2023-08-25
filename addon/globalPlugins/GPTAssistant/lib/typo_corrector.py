from typing import Any, List, Tuple

import logging
import requests
import time

from hanzidentifier import has_chinese
from pypinyin import lazy_pinyin, Style
from .template import TEMPLATE_DICT
from .utils import has_simplified_chinese_char, has_traditional_chinese_char
from .utils import SEPERATOR

import chinese_converter

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
		backoff: int = 5,
		prefix: str = "我說：“",
		suffix: str = "”",
		is_chat_completion: bool = False):

		self.model = model
		self.max_tokens = max_tokens
		self.temperature = temperature
		self.top_p = top_p
		self.retries = retries
		self.backoff = backoff
		self.prefix = prefix
		self.suffix = suffix
		self.is_chat_completion = is_chat_completion
		self.usage_history = []

		self.headers = {"Authorization": f"Bearer {api_key}"}

	def correct_string(self, original_text: str, fake_operation: bool = False) -> str:
		if fake_operation or not has_chinese(original_text):
			return original_text

		corrected_text = None
		for template_index, template in enumerate(TEMPLATE_DICT[self.__class__.__name__]):
			try:
				prompt = self._create_prompt(template, original_text)
				response = self._do_completion(prompt)

				if response is None:
					log.error(f"template {template_index} fails.\ntemplate = {template}")
					continue

				self.usage_history.append((prompt, response))

				response_text = self._parse_response(response)
				is_valid = self._is_validate_response(response_text, original_text)

				if is_valid:
					corrected_text = self._correct_typos(original_text, response_text)
					break

				log.warning(f"response result of template {template_index} is not valid")

			except Exception as e:
				log.error(f"An unexpected error occurred: {e}")

		return corrected_text

	def _do_completion(self, prompt: str) -> str:
		if self.is_chat_completion:
			return self._chat_completion(prompt)

		return self._completion(prompt)

	def _completion(self, prompt: str) -> str:
		data = {
			"model": self.model,
			"prompt": prompt,
			"max_tokens": self.max_tokens,
			"temperature": self.temperature,
			"top_p": self.top_p,
		}

		for r in range(self.retries):
			try:
				response = requests.post(
					"https://api.openai.com/v1/completions",
					headers=self.headers,
					json=data
				)
			except Exception as e:
				log.error(f"An unexpected error occurred when sending OpenAI request: {e}")
				time.sleep(self.backoff)
				continue

			if response.status_code == 200:
				return response.json()

			log.error(f"Try = {r}, {response}, error: {response.reason}")
			time.sleep(self.backoff)

		return None

	def _chat_completion(self, prompt: str) -> str:
		messages = [
			{"role": "user", "content": prompt},
		]

		data = {
			"model": self.model,
			"messages": messages,
			"max_tokens": self.max_tokens,
			"temperature": self.temperature,
			"top_p": self.top_p,
			"stop": ["#", " =>"]
		}

		for r in range(self.retries):
			try:
				response = requests.post(
					"https://api.openai.com/v1/chat/completions",
					headers=self.headers,
					json=data,
					timeout=10,
				)
			except Exception as e:
				log.error(f"An unexpected error occurred when sending OpenAI request: {e}")
				time.sleep(self.backoff)
				continue

			if response.status_code == 200:
				return response.json()

			log.error(f"Try = {r}, {response}, error: {response.reason}")
			time.sleep(self.backoff)

		return None

	def _parse_response(self, response: str):
		raise NotImplementedError("Subclass must implement this method")

	def _create_prompt(self, template: str, text: str):
		raise NotImplementedError("Subclass must implement this method")

	def _is_validate_response(self, response: Any, original_text: str):
		raise NotImplementedError("Subclass must implement this method")

	def _correct_typos(self, original_text: str, response: Any):
		raise NotImplementedError("Subclass must implement this method")


class TypoCorrector(BaseTypoCorrector):

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)

	def _parse_response(self, response: str) -> str:
		if self.is_chat_completion:
			return response["choices"][0]["message"]["content"]
		return response["choices"][0]["text"]

	def _create_prompt(self, template: str, text: str):
		return template.replace("{{text_input}}", text)

	def _is_validate_response(self, response: str, original_text: str) -> bool:
		return True

	def _correct_typos(self, original_text: str, response: str):
		return response


class TypoCorrectorWithPhone(BaseTypoCorrector):

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)

	def _parse_response(self, response: str) -> str:
		if self.is_chat_completion:
			return response["choices"][0]["message"]["content"]
		return response["choices"][0]["text"]

	def _create_prompt(self, template: str, text: str):
		text = self.prefix + text + self.suffix
		phone = ' '.join(lazy_pinyin(text, style=Style.TONE3))
		return template.replace("{{text_input}}", text).replace("{{phone_input}}", phone)

	def _is_validate_response(self, response: str, original_text: str) -> bool:
		return True

	def _correct_typos(self, original_text: str, response: str):
		correct_sentence = response[len(self.prefix):-len(self.suffix)] if self.suffix else response[len(self.prefix):]
		correct_sentence = correct_sentence.replace("。", "").replace("”", "").replace("“", "")
		if has_simplified_chinese_char(correct_sentence):
			correct_sentence = chinese_converter.to_traditional(correct_sentence)

		return correct_sentence


class TypoCorrectorByPhone(BaseTypoCorrector):

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)

	def _parse_response(self, response: str) -> str:
		if self.is_chat_completion:
			text = response["choices"][0]["message"]["content"]
		else:
			text = response["choices"][0]["text"]

		while text and text[-1] in SEPERATOR:
			text = text[:-1]
		return text

	def _create_prompt(self, template: str, text: str):
		pinyin = ' '.join(lazy_pinyin(text, style=Style.TONE))
		return template.replace("{{pinyin_input}}", pinyin).replace("{{text_type}}", "繁體中文")

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
