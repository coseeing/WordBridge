from copy import deepcopy
from typing import Any, List

import logging
import random
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
		seed: int = 0,
		temperature: float = 0.0,
		top_p: float = 0.0,
		logprobs: bool = True,
		max_correction_attempts: int = 3,
		httppost_retries: int = 2,
		backoff: int = 1,
		is_chat_completion: bool = False,
	):

		self.model = model
		self.max_tokens = max_tokens
		self.seed = seed
		self.temperature = temperature
		self.top_p = top_p
		self.logprobs = logprobs
		self.max_correction_attempts = max_correction_attempts
		self.httppost_retries = httppost_retries
		self.backoff = backoff
		self.is_chat_completion = is_chat_completion
		self.usage_history = []
		self.headers = {"Authorization": f"Bearer {api_key}"}

	def correct_segment(self, input_text: str, fake_operation: bool = False) -> str:
		if fake_operation or not has_chinese(input_text):
			return input_text

		if self.is_chat_completion:
			template = deepcopy(TEMPLATE_DICT[self.__class__.__name__ + "Chat"])
		else:
			template = deepcopy(TEMPLATE_DICT[self.__class__.__name__])
		text = self._text_preprocess(input_text)
		input = self._create_input(template, text, self.is_chat_completion)

		response_text_history = []
		for _ in range(self.max_correction_attempts):
			corrected_text = None
			if self.is_chat_completion:
				response_json = self._chat_completion(input, response_text_history)
			else:
				response_json = self._completion(input)

			self.usage_history.append((input, response_json))

			response_text = self._parse_response(response_json)
			corrected_text = self._correct_typos(response_text, text)

			if not self._has_error(corrected_text, text):
				break

			response_text_history.append(corrected_text)

		if len(response_text_history) > 1:
			log.warning("Correction history: ", response_text_history)

		output_text = self._text_postprocess(corrected_text) if corrected_text is not None else None

		return output_text

	def _completion(self, prompt: str) -> str:
		data = {
			"model": self.model,
			"prompt": prompt,
			"max_tokens": self.max_tokens,
			"seed": self.seed,
			"temperature": self.temperature,
			"top_p": self.top_p,
			"logprobs": self.logprobs,
		}

		return self._openai_post_with_retries(data)

	def _chat_completion(self, messages: List, response_text_history: List) -> str:
		for response_previous in response_text_history:
			messages.append({"role": "assistant", "content": response_previous})
			messages.append({"role": "user", "content": f"'{response_previous}'是錯誤答案，請修正重新輸出文字"})

		data = {
			"model": self.model,
			"messages": messages,
			"max_tokens": self.max_tokens,
			"seed": self.seed,
			"temperature": self.temperature,
			"top_p": self.top_p,
			"logprobs": self.logprobs,
			"stop": [" =>"]
		}

		return self._openai_post_with_retries(data)

	def _openai_post_with_retries(self, data):
		backoff = self.backoff
		if self.is_chat_completion:
			url = "https://api.openai.com/v1/chat/completions"
		else:
			url = "https://api.openai.com/v1/completions"

		response_json = None
		for r in range(self.httppost_retries):
			response = None
			try:
				response = requests.post(
					url,
					headers=self.headers,
					json=data,
					timeout=5,
				)
				if response.status_code != 200:
					raise Exception

				response_json = response.json()
				break

			except Exception as e:
				if response is None:
					log.error(f"Try = {r}, An unexpected error occurred when sending OpenAI request: {e}")
				else:
					log.error(f"Try = {r}, {response}, error: {response.reason}")

				backoff = min(backoff * (1 + random.random()), 3)
				time.sleep(backoff)

		if response_json is None:
			raise MaxIterationsExceededError(f"Exceeded maximum iterations of httppost_retries = {self.httppost_retries}")
		return response_json


	def _parse_response(self, response: str):
		raise NotImplementedError("Subclass must implement this method")

	def _create_input(self, template: str, text: str, is_chat_completion: bool):
		raise NotImplementedError("Subclass must implement this method")

	def _has_error(self, response: Any, text: str):
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

	def _create_input(self, template: str, text: str, is_chat_completion: bool):
		if is_chat_completion:
			raise NotImplementedError("TypoCorrector do not support chat completion")
		return template.replace("{{text_input}}", text)

	def _has_error(self, response: Any, text: str) -> bool:
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

	def _create_input(self, template: str, text: str, is_chat_completion: bool):
		phone = ' '.join(lazy_pinyin(text, style=Style.TONE3))
		if is_chat_completion:
			template[-1]["content"] = template[-1]["content"].replace("{{text_input}}", text)
			template[-1]["content"] = template[-1]["content"].replace("{{phone_input}}", phone)
			return template
		return template.replace("{{text_input}}", text).replace("{{phone_input}}", phone)

	def _has_error(self, response: str, text: str) -> bool:
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

	def _create_input(self, template: str, text: str, is_chat_completion: bool):
		pinyin = ' '.join(lazy_pinyin(text, style=Style.TONE))
		if is_chat_completion:
			raise NotImplementedError("TypoCorrectorByPhone do not support chat completion")
		return template.replace("{{pinyin_input}}", pinyin).replace("{{text_type}}", "繁體中文")

	def _has_error(self, response: str, text: str) -> bool:
		return False

	def _correct_typos(self, response: str, text: str):
		return response

	def _text_preprocess(self, input_text: str):
		return input_text

	def _text_postprocess(self, text: str):
		return text
