from copy import deepcopy
from queue import Queue
from threading import Thread
from typing import Any, List

import logging
import random
import requests
import time

from pypinyin import lazy_pinyin, Style
from .template import COMMENT_DICT, TEMPLATE_DICT
from .utils import get_char_pinyin, has_chinese, has_simplified_chinese_char, has_traditional_chinese_char
from .utils import SEPERATOR, is_chinese_character

import chinese_converter


try:
	import addonHandler
	addonHandler.initTranslation()
except:
	pass


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
		provider: str,
		credential: dict,
		max_tokens: int = 2048,
		seed: int = 0,
		temperature: float = 0.0,
		top_p: float = 0.0,
		logprobs: bool = True,
		max_correction_attempts: int = 3,
		httppost_retries: int = 2,
		backoff: int = 1,
		language: str = "zh_traditional_tw",
	):

		self.model = model
		self.provider = provider
		self.max_tokens = max_tokens
		self.seed = seed
		self.temperature = temperature
		self.top_p = top_p
		self.logprobs = logprobs
		self.max_correction_attempts = max_correction_attempts
		self.httppost_retries = httppost_retries
		self.backoff = backoff
		self.credential = credential
		self.language = language

	def correct_segment(self, input_text: str, fake_operation: bool = False) -> str:
		if fake_operation or not self._has_target_language(input_text):
			return CorrectorResult(input_text, input_text, [])

		template = deepcopy(TEMPLATE_DICT[self.__class__.__name__][self.language])
		text = self._text_preprocess(input_text)
		input = self._create_input(template, text)

		response_history = []
		response_text_history = []
		for _ in range(self.max_correction_attempts):
			corrected_text = None
			response_json = self._chat_completion(input, response_text_history)

			response_history.append(response_json)

			response_text = self._parse_response(response_json)
			corrected_text = self._correct_typos(response_text, text)

			if not self._has_error(corrected_text, text):
				break

			response_text_history.append(corrected_text)

		if len(response_text_history) > 1:
			log.warning(f"Correction history: {response_text_history}")

		output_text = self._text_postprocess(corrected_text, input_text) if corrected_text is not None else None

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

	def _get_api_url(self):
		if self.provider == "OpenAI":
			api_url = "https://api.openai.com/v1/chat/completions"
		elif self.provider == "Baidu":
			api_key = self.credential["api_key"]
			secret_key = self.credential["secret_key"]
			url_get_access = "https://aip.baidubce.com/oauth/2.0/token" +\
						f"?grant_type=client_credentials&client_id={api_key}&client_secret={secret_key}"
			headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
			response = requests.request("POST", url_get_access, headers=headers, json={})
			access_token = response.json().get("access_token")
			api_url = "https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat/" +\
						f"{self.model}?access_token=" + access_token
		else:
			raise NotImplementedError("Subclass must implement this method")

		return api_url

	def _get_request_data(self, messages):
		if self.provider == "OpenAI":
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
		elif self.provider == "Baidu":
			data = {
				"messages": messages,
				"max_output_tokens": min(self.max_tokens, len(messages[-1]["content"])),
				"temperature": max(self.temperature, 0.0001),
				"top_p": self.top_p,
				"stop": ["\n"]
			}
		else:
			raise NotImplementedError("Subclass must implement this method")

		return data

	def _get_headers(self):
		if self.provider == "OpenAI":
			headers = {"Authorization": f"Bearer {self.credential['secret_key']}"}
		elif self.provider == "Baidu":
			headers = {'Content-Type': 'application/json'}
		else:
			raise NotImplementedError("Subclass must implement this method")

		return headers

	def _chat_completion(self, input: List, response_text_history: List) -> str:
		messages = deepcopy(input)
		if self.provider == "OpenAI":
			comment_template = COMMENT_DICT[self.__class__.__name__][self.language]
			for response_previous in response_text_history:
				comment = comment_template.replace("{{response_previous}}", response_previous)
				messages.append({"role": "assistant", "content": response_previous})
				messages.append({"role": "user", "content": comment})
		elif self.provider == "Baidu":
			msg_system = messages.pop(0)
			messages[0]["content"] = msg_system["content"] + "\n" + messages[0]["content"]

		request_data = self._get_request_data(messages)
		api_url = self._get_api_url()
		headers = self._get_headers()

		return self._post_with_retries(request_data, api_url, headers)

	def _post_with_retries(self, request_data, api_url, headers):
		backoff = self.backoff
		response_json = None
		for r in range(self.httppost_retries):
			request_error = None
			response = None
			try:
				response = requests.post(
					api_url,
					headers=headers,
					json=request_data,
					timeout=5,
				)
				break
			except Exception as e:
				request_error = type(e).__name__
				log.error(
					_("Try = {try_index}, {request_error}, an error occurred when sending OpenAI request: {e}").format(
						try_index=(r + 1),
						request_error=request_error,
						e=e
					)
				)
				backoff = min(backoff * (1 + random.random()), 3)
				time.sleep(backoff)

		if response is None:
			raise Exception(
				_("HTTP request error ({request_error}). Please check the network setting.").format(
					request_error=request_error
				)
			)

		response_json = response.json()
		if response.status_code == 401:
			raise Exception(_("Authentication error. Please check if the OpenAI API Key is correct."))
		elif response.status_code == 404:
			raise Exception(_("Service does not exist. Please check if the model does not exist or has expired."))
		elif response.status_code != 200:
			raise Exception(_("Unknown errors. Status code = {status_code}").format(status_code=response.status_code))

		return response_json

	def _parse_response(self, response: str) -> str:
		if self.provider == "OpenAI":
			sentence = response["choices"][0]["message"]["content"]
		elif self.provider == "Baidu":
			sentence = response["result"]
		else:
			raise NotImplementedError("Subclass must implement this method")

		if self.language == "zh_traditional_tw" and has_simplified_chinese_char(sentence):
			sentence = chinese_converter.to_traditional(sentence)
		if self.language == "zh_simplified" and has_traditional_chinese_char(sentence):
			sentence = chinese_converter.to_simplified(sentence)

		return sentence

	def _create_input(self, template: str, text: str):
		raise NotImplementedError("Subclass must implement this method")

	def _has_error(self, response: Any, text: str):
		raise NotImplementedError("Subclass must implement this method")

	def _correct_typos(self, response: Any, text: str):
		raise NotImplementedError("Subclass must implement this method")

	def _text_preprocess(self, input_text: str):
		raise NotImplementedError("Subclass must implement this method")

	def _text_postprocess(self, text: str, input_text: str):
		raise NotImplementedError("Subclass must implement this method")

	def _has_target_language(self, text: str):
		raise NotImplementedError("Subclass must implement this method")


class ChineseTypoCorrectorSimple(BaseTypoCorrector):

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)

	def _create_input(self, template: str, text: str):
		template[-1]["content"] = template[-1]["content"].replace("{{text_input}}", text)
		return template

	def _has_error(self, response: Any, text: str) -> bool:
		return False

	def _correct_typos(self, response: str, text: str):
		return response

	def _text_preprocess(self, input_text: str):
		return input_text

	def _text_postprocess(self, text: str, input_text: str):
		if input_text[-1] in SEPERATOR:
			return text

		# Remove automatically added punctuations since there is no punctuation at the end of input
		while text and text[-1] in SEPERATOR:
			text = text[:-1]
		return text

	def _has_target_language(self, text: str):
		return has_chinese(text)


class ChineseTypoCorrector(BaseTypoCorrector):

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)

		if self.language == "zh_traditional_tw":
			self.prefix = "我說"
			self.suffix = ""
			self.question_string: str = ""
			self.answer_string: str = ""
		elif self.language == "zh_simplified":
			self.prefix = "我说"
			self.suffix = ""
			self.question_string: str = ""
			self.answer_string: str = ""
		else:
			raise NotImplementedError

	def _create_input(self, template: str, text: str):
		phone = ' '.join(lazy_pinyin(text, style=Style.TONE3))

		for i in range(len(template)):
			template[i]["content"] = template[i]["content"].replace("{{text_input}}", text)
			template[i]["content"] = template[i]["content"].replace("{{phone_input}}", phone)
			template[i]["content"] = template[i]["content"].replace("{{QUESTION}}", self.question_string)
			template[i]["content"] = template[i]["content"].replace("{{ANSWER}}", self.answer_string)

		return template

	def _has_error(self, response: str, text: str) -> bool:
		if not self.provider == "OpenAI":
			return False

		response_text = response[len(self.answer_string):]

		response_list = []
		for char in response_text:
			if is_chinese_character(char):
				response_list.append(char)

		text_list = []
		for char in text:
			if is_chinese_character(char):
				text_list.append(char)

		if len(response_list) != len(text_list):
			return True

		for i in range(len(text_list)):
			if len(set(get_char_pinyin(text_list[i])) & set(get_char_pinyin(response_list[i]))) == 0:
				return True
		return False

	def _correct_typos(self, response: str, text: str):
		return response

	def _text_preprocess(self, input_text: str):
		return self.prefix + input_text + self.suffix

	def _text_postprocess(self, text: str, input_text: str):
		text = text[(len(self.prefix) + len(self.answer_string)):(len(text) - len(self.suffix))]
		if input_text[-1] in SEPERATOR:
			return text

		# Remove automatically added punctuations since there is no punctuation at the end of input
		while text and text[-1] in SEPERATOR:
			text = text[:-1]
		return text

	def _has_target_language(self, text: str):
		return has_chinese(text)
