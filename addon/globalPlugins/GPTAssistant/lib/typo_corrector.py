from typing import Any, List, Tuple

import logging
import requests
import time

from hanzidentifier import has_chinese
from pypinyin import lazy_pinyin, Style
from .template import TEMPLATE_DICT
from .utils import get_phone, has_simplified_chinese_char, has_traditional_chinese_char
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
		max_correction_count: int = 3,
		retries: int = 3,
		backoff: int = 5,
		is_chat_completion: bool = False):

		self.model = model
		self.max_tokens = max_tokens
		self.temperature = temperature
		self.top_p = top_p
		self.max_correction_count = max_correction_count
		self.retries = retries
		self.backoff = backoff
		self.is_chat_completion = is_chat_completion
		self.usage_history = []
		self.headers = {"Authorization": f"Bearer {api_key}"}

	def correct_string(self, input_text: str, fake_operation: bool = False) -> str:
		if fake_operation or not has_chinese(input_text):
			return input_text

		text = self._text_preprocess(input_text)
		response_text_history = []
		corrected_text = None
		template_index = 0
		for _ in range(self.max_correction_count):
			template = TEMPLATE_DICT[self.__class__.__name__][template_index]
			prompt = self._create_prompt(template, text)
			if self.is_chat_completion:
				response = self._chat_completion(prompt, response_text_history)
			else:
				response = self._completion(prompt)

			if response is None:
				log.error(f"template {template_index} fails.\ntemplate = {template}")
				continue

			self.usage_history.append((prompt, response))

			response_text = self._parse_response(response)
			corrected_text = self._correct_typos(response_text, text)

			if not self._error_detection(corrected_text, text):
				break

			response_text_history.append(corrected_text)

			if template_index + 1 < len(TEMPLATE_DICT[self.__class__.__name__]):
				template_index += 1

		if len(response_text_history) > 1:
			print(response_text_history)

		output_text = self._text_postprocess(corrected_text) if corrected_text is not None else None

		return output_text

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

	def _chat_completion(self, prompt: str, response_text_history: List) -> str:
		messages = [
			{"role": "user", "content": prompt},
		]
		for response_previous in response_text_history:
			messages.append({"role": "assistant", "content": response_previous})
			messages.append({"role": "user", "content": f"'{response_previous}'是錯誤答案，請修正重新輸出文字"})

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

	def _error_detection(self, response: Any, text: str):
		raise NotImplementedError("Subclass must implement this method")

	def _correct_typos(self, response: Any, text: str):
		raise NotImplementedError("Subclass must implement this method")

	def _text_preprocess(self, input_text: str):
		raise NotImplementedError("Subclass must implement this method")

	def _text_postprocess(self, text: str):
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

	def _error_detection(self, response: Any, text: str) -> bool:
		return False

	def _correct_typos(self, response: str, text: str):
		return response

	def _text_preprocess(self, input_text: str):
		return input_text

	def _text_postprocess(self, text: str):
		return text


class TypoCorrectorWithPhone(BaseTypoCorrector):

	def __init__(self, prefix="我說：“", suffix="。”", *args, **kwargs):
		self.prefix = prefix
		self.suffix = suffix
		super().__init__(*args, **kwargs)

	def _parse_response(self, response: str) -> str:
		if self.is_chat_completion:
			sentence = response["choices"][0]["message"]["content"]
		else:
			sentence = response["choices"][0]["text"]

		if has_simplified_chinese_char(sentence):
			sentence = chinese_converter.to_traditional(sentence)

		return sentence

	def _create_prompt(self, template: str, text: str):
		phone = ' '.join(lazy_pinyin(text, style=Style.TONE3))
		return template.replace("{{text_input}}", text).replace("{{phone_input}}", phone)

	def _error_detection(self, response: str, text: str) -> bool:
		if len(response) != len(text):
			return True

		for i in range(len(text)):
			if len(set(get_phone(text[i])) & set(get_phone(response[i]))) == 0:
				return True
		return False

	def _correct_typos(self, response: str, text: str):
		return response

	def _text_preprocess(self, input_text: str):
		return self.prefix + input_text + self.suffix

	def _text_postprocess(self, text: str):
		return text[len(self.prefix):(len(text) - len(self.suffix))]


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

	def _error_detection(self, response: str, text: str) -> bool:
		return False

	def _correct_typos(self, response: str, text: str):
		return response

	def _text_preprocess(self, input_text: str):
		return input_text

	def _text_postprocess(self, text: str):
		return text
