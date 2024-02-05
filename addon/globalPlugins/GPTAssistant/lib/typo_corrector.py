from copy import deepcopy
from queue import Queue
from threading import Thread
from typing import Any, List

import logging
import random
import requests
import time

from hanzidentifier import has_chinese
from pypinyin import lazy_pinyin, Style
from .template import COMMENT_DICT, TEMPLATE_DICT
from .utils import get_phone, has_simplified_chinese_char, has_traditional_chinese_char

import chinese_converter

log = logging.getLogger(__name__)


class CorrectorResult():
	def __init__(
		self,
		original_text: str,
		corrected_text: str,
		response_history: List,
	):
		self.original_text = original_text
		self.corrected_text = corrected_text
		self.response_history = response_history


class BaseTypoCorrector():

	def __init__(
		self,
		model: str,
		access_token: str,
		api_base_url: str,
		max_tokens: int = 2048,
		seed: int = 0,
		temperature: float = 0.0,
		top_p: float = 0.0,
		logprobs: bool = True,
		max_correction_attempts: int = 3,
		httppost_retries: int = 2,
		backoff: int = 1,
		is_chat_completion: bool = True,
	):

		self.model = model
		self.api_base_url = api_base_url
		self.max_tokens = max_tokens
		self.seed = seed
		self.temperature = temperature
		self.top_p = top_p
		self.logprobs = logprobs
		self.max_correction_attempts = max_correction_attempts
		self.httppost_retries = httppost_retries
		self.backoff = backoff
		self.is_chat_completion = is_chat_completion
		self.headers = {"Authorization": f"Bearer {access_token}"}

	def correct_segment(self, input_text: str, fake_operation: bool = False) -> str:
		if fake_operation or not self._has_target_language(input_text):
			return input_text

		if self.is_chat_completion:
			template = deepcopy(TEMPLATE_DICT[self.__class__.__name__ + "Chat"])
		else:
			template = deepcopy(TEMPLATE_DICT[self.__class__.__name__])
		text = self._text_preprocess(input_text)
		input = self._create_input(template, text, self.is_chat_completion)

		response_history = []
		response_text_history = []
		for _ in range(self.max_correction_attempts):
			corrected_text = None
			if self.is_chat_completion:
				response_json = self._chat_completion(input, response_text_history)
			else:
				response_json = self._completion(input)

			response_history.append(response_json)

			response_text = self._parse_response(response_json)
			corrected_text = self._correct_typos(response_text, text)

			if not self._has_error(corrected_text, text):
				break

			response_text_history.append(corrected_text)

		if len(response_text_history) > 1:
			log.warning(f"Correction history: {response_text_history}")

		output_text = self._text_postprocess(corrected_text) if corrected_text is not None else None

		corrector_result = CorrectorResult(
			original_text=input_text,
			corrected_text=output_text,
			response_history=response_history,
		)

		return corrector_result

	def correct_segment_batch(self, input_text_list: list) -> list:
		assert isinstance(input_text_list, list)

		exception_queue = Queue()

		if not input_text_list:
			return input_text_list

		output_text_list = [None] * len(input_text_list)

		threads = []
		for index, input_text in enumerate(input_text_list):
			thread = Thread(
				target=self._correct_segment_task,
				args=(input_text, output_text_list, index, exception_queue)
			)
			thread.start()
			threads.append(thread)

		for thread in threads:
			thread.join()

		exception_set = set()
		while not exception_queue.empty():
			exception_set.add(str(exception_queue.get()))
		if exception_set:
			raise Exception(", ".join(list(exception_set)))

		return output_text_list

	def _correct_segment_task(
		self,
		input_text: str,
		output_text_list: list,
		index: int,
		exception_queue: Queue
	) -> str:
		try:
			text = self.correct_segment(input_text)
			output_text_list[index] = text
		except Exception as e:
			exception_queue.put(e)

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

	def _chat_completion(self, input: List, response_text_history: List) -> str:
		messages = deepcopy(input)
		comment_template = COMMENT_DICT[self.__class__.__name__ + "Chat"]
		for response_previous in response_text_history:
			comment = comment_template.replace("{{response_previous}}", response_previous)
			messages.append({"role": "assistant", "content": response_previous})
			messages.append({"role": "user", "content": comment})

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
			url = f"{self.api_base_url}/v1/chat/completions"
		else:
			url = f"{self.api_base_url}/v1/completions"

		response_json = None
		for r in range(self.httppost_retries):
			request_error = None
			response = None
			try:
				response = requests.post(
					url,
					headers=self.headers,
					json=data,
					timeout=5,
				)
				break
			except Exception as e:
				request_error = type(e).__name__
				log.error(
					_(f"Try = {r + 1}, {request_error}, an error occurred when sending OpenAI request: {e}")
				)
				backoff = min(backoff * (1 + random.random()), 3)
				time.sleep(backoff)

		if response is None:
			raise Exception(_(f"HTTP request error ({request_error}). Please check the network setting"))

		response_json = response.json()
		if response.status_code == 401:
			raise Exception(_("Authentication error. Please check if the OpenAI API Key is correct."))
		elif response.status_code == 404:
			raise Exception(_("Service does not exist. Please check if the model does not exist or has expired."))
		elif response.status_code != 200:
			raise Exception(_(f"Unknown errors. Status code = {response.status_code}"))

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

	def _has_target_language(self, text: str):
		raise NotImplementedError("Subclass must implement this method")


class ChineseTypoCorrectorLite(BaseTypoCorrector):

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

	def _has_target_language(self, text: str):
		return has_chinese(text)


class ChineseTypoCorrector(BaseTypoCorrector):

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

	def _has_target_language(self, text: str):
		return has_chinese(text)
