from copy import deepcopy
from queue import Queue
from threading import Thread
from typing import Any, List

import json
import logging
import os
import random
import requests
import time

from pypinyin import lazy_pinyin, Style
from .utils import get_char_pinyin, has_chinese, has_simplified_chinese_char, has_traditional_chinese_char
from .utils import PUNCTUATION, SEPERATOR, is_chinese_character

import chinese_converter


try:
	import addonHandler
	addonHandler.initTranslation()
except ImportError:
	def _(s):
		return s


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
		template_name: str,
		optional_guidance_enable: dict,
		customized_words: list,
		max_tokens: int = 2048,
		seed: int = 0,
		temperature: float = 0.0,
		top_p: float = 0.0,
		logprobs: bool = True,
		max_correction_attempts: int = 3,
		httppost_retries: int = 2,
		backoff: int = 1,
		language: str = "zh_traditional",
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
		self.optional_guidance_enable = optional_guidance_enable
		self.customized_words = customized_words

		file_dirpath = os.path.dirname(__file__)
		template_path = os.path.join(file_dirpath, "..", "template", template_name)
		with open(template_path, "r", encoding="utf8") as f:
			self.template = json.loads(f.read())

	def correct_segment(self, input_text: str, fake_operation: bool = False) -> str:
		if fake_operation or not self._has_target_language(input_text):
			return CorrectorResult(input_text, input_text, [])

		input_info = self._get_input_info(input_text)

		message_template = deepcopy(self.template[self.language]["message"])
		for i in range(len(message_template)):
			message_template[i]["content"] = message_template[i]["content"].replace("\\n", "\n")
		text = self._text_preprocess(input_text)
		input_prompt = self._create_input(message_template, text)

		response_history = []
		response_text_history = []
		output_text = None
		for _ in range(self.max_correction_attempts):
			response_json = self._chat_completion(input_prompt, response_text_history, input_info)

			response_history.append(response_json)

			response_text = self._parse_response(response_json)
			response_text_history.append(response_text)

			output_text = self._text_postprocess(response_text, input_text)
			if not self._has_error(output_text, input_text):
				break

		if len(response_text_history) > 1:
			log.warning(f"Correction history: {response_text_history}")

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
			response = None
			for r in range(2):
				timeout = min(5 * (r + 1), 15)
				try:
					response = requests.request("POST", url_get_access, headers=headers, json={}, timeout=timeout)
				except Exception as e:
					request_error = type(e).__name__
					log.error(
						"Try = {try_index}, {request_error}, an error occurred when sending {provider} request: {e}".format(
							try_index=(r + 1),
							request_error=request_error,
							provider=self.provider,
							e=e
						)
					)
					time.sleep(0.5 + random.random())
			if response is None:
				raise Exception(
					_("HTTP request error ({request_error}). Please check the network setting.").format(
						request_error=request_error
					)
				)
			elif "error" in response.json():
				raise Exception(_("Authentication error. Please check if the large language model's key is correct."))
			access_token = response.json().get("access_token")
			api_url = "https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat/" +\
						f"{self.model}?access_token=" + access_token
		else:
			raise NotImplementedError("Subclass must implement this method")

		return api_url

	def _get_input_info(self, input_text):
		input_info = {
			"input_text": input_text,
			"contain_non_chinese": False,
		}
		for char in input_text:
			if not is_chinese_character(char) and char not in PUNCTUATION:
				input_info["contain_non_chinese"] = True
				break

		return input_info

	def _find_word_candidate(self, input_text, customized_words):
		candidates = []
		for word in customized_words:
			if len(word) > len(input_text):
				continue
			for i in range(len(input_text) - len(word) + 1):
				flag = True
				for j in range(len(word)):
					if len(set(get_char_pinyin(word[j])) & set(get_char_pinyin(input_text[i + j]))) == 0:
						flag = False
				if flag:
					candidates.append(word)
					break

		return candidates

	def _system_add_guidance(self, system, input_info):
		guidance_list = []
		if self.optional_guidance_enable["no_explanation"]:
			guidance_list.append(self.template[self.language]["optional_guidance"]["no_explanation"])

		if self.optional_guidance_enable["keep_non_chinese_char"] and input_info["contain_non_chinese"]:
			guidance_list.append(self.template[self.language]["optional_guidance"]["keep_non_chinese_char"])

		word_candidate = self._find_word_candidate(input_info["input_text"], self.customized_words)
		if word_candidate:
			customized_word_guidance = self.template[self.language]["optional_guidance"]["customized_words"]
			system = system + "\n" + customized_word_guidance + "、".join(word_candidate)

		if not guidance_list:
			return system

		system = system + "\n須注意: " + "、".join(guidance_list)
		return system

	def _get_request_data(self, messages, input_info):
		system_template = deepcopy(self.template[self.language]["system"])
		system_template = system_template.replace("\\n", "\n")
		system_template = self._system_add_guidance(system_template, input_info)
		if self.provider == "OpenAI":
			messages = [{"role": "system", "content": system_template}] + messages
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
				"system": system_template,
				"max_output_tokens": min(self.max_tokens, len(messages[-1]["content"])),
				"temperature": max(self.temperature, 0.0001),
				"top_p": self.top_p,
				"stop": ["\n", "&"]
			}
		else:
			raise NotImplementedError("Subclass must implement this method")

		return data

	def _get_headers(self):
		if self.provider == "OpenAI":
			headers = {"Authorization": f"Bearer {self.credential['api_key']}"}
		elif self.provider == "Baidu":
			headers = {'Content-Type': 'application/json'}
		else:
			raise NotImplementedError("Subclass must implement this method")

		return headers

	def _chat_completion(self, input: List, response_text_history: List, input_info: dict) -> str:
		messages = deepcopy(input)
		if self.provider == "OpenAI":
			comment_template = deepcopy(self.template[self.language]["comment"])
			comment_template = comment_template.replace("\\n", "\n")
			for response_previous in response_text_history:
				comment = comment_template.replace("{{response_previous}}", response_previous)
				messages.append({"role": "assistant", "content": response_previous})
				messages.append({"role": "user", "content": comment})

		request_data = self._get_request_data(messages, input_info)
		api_url = self._get_api_url()
		headers = self._get_headers()

		return self._post_with_retries(request_data, api_url, headers)

	def _post_with_retries(self, request_data, api_url, headers):
		backoff = self.backoff
		response_json = None
		for r in range(self.httppost_retries):
			timeout = min(5 * (r + 1), 15)
			request_error = None
			response = None
			try:
				response = requests.post(
					api_url,
					headers=headers,
					json=request_data,
					timeout=timeout,
				)
				break
			except Exception as e:
				request_error = type(e).__name__
				log.error(
					"Try = {try_index}, {request_error}, an error occurred when sending {provider} request: {e}".format(
						try_index=(r + 1),
						request_error=request_error,
						provider=self.provider,
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

		if self.provider == "OpenAI" and response.status_code != 200:
			self._handle_openai_errors(response)

		if self.provider == "Baidu" and ("error_code" in response_json or not response_json["result"]):
			self._handle_baidu_errors(response_json)

		return response_json

	def _handle_openai_errors(self, response):
		if response.status_code == 401:
			raise Exception(_("Authentication error. Please check if the large language model's key is correct."))
		elif response.status_code == 403:
			raise Exception(_("Country, region, or territory not supported."))
		elif response.status_code == 404:
			raise Exception(_("Service does not exist. Please check if the model does not exist or has expired."))
		elif response.status_code == 429:
			raise Exception(
				_("Rate limit reached for requests or you exceeded your current quota. ") +\
				_("Please reduce the frequency of sending requests or check your account balance.")
			)
		elif response.status_code == 500:
			raise Exception(_("The server had an error while processing your request, please try again later."))
		elif response.status_code == 503:
			raise Exception(_("The server is currently overloaded, please try again later."))
		else:
			raise Exception(_("Unknown errors. Status code = {status_code}").format(status_code=response.status_code))

	def _handle_baidu_errors(self, response_json):
		if response_json["error_code"] == 3:
			raise Exception(_("Service does not exist. Please check if the model does not exist or has expired."))
		elif response_json["error_code"] in [336000, 336100]:
			raise Exception(_("Service internal error, please try again later."))
		elif response_json["error_code"] in [18, 336501, 336502]:
			raise Exception(_("Usage limit exceeded, please try again later."))
		elif response_json["error_code"] == 17:
			raise Exception(_("Please check if the API has been activated and the current account has enough money"))
		elif not response_json["result"]:
			raise Exception(_("Service does not exist. Please check if the model does not exist or has expired."))
		else:
			raise Exception(response_json["error_msg"])

	def _parse_response(self, response: str) -> str:
		if self.provider == "OpenAI":
			sentence = response["choices"][0]["message"]["content"]
		elif self.provider == "Baidu":
			sentence = response["result"]
		else:
			raise NotImplementedError("Subclass must implement this method")

		if self.language == "zh_traditional" and has_simplified_chinese_char(sentence):
			sentence = chinese_converter.to_traditional(sentence)
		if self.language == "zh_simplified" and has_traditional_chinese_char(sentence):
			sentence = chinese_converter.to_simplified(sentence)

		return sentence

	def _create_input(self, template: str, text: str):
		raise NotImplementedError("Subclass must implement this method")

	def _has_error(self, response: Any, text: str):
		raise NotImplementedError("Subclass must implement this method")

	def _text_preprocess(self, input_text: str):
		raise NotImplementedError("Subclass must implement this method")

	def _text_postprocess(self, text: str, input_text: str):
		raise NotImplementedError("Subclass must implement this method")

	def _has_target_language(self, text: str):
		raise NotImplementedError("Subclass must implement this method")


class ChineseTypoCorrectorLite(BaseTypoCorrector):

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)

	def _create_input(self, template: str, text: str):
		template[-1]["content"] = template[-1]["content"].replace("{{text_input}}", text)
		return template

	def _has_error(self, response: Any, text: str) -> bool:
		return False

	def _text_preprocess(self, input_text: str):
		return input_text

	def _text_postprocess(self, text: str, input_text: str):
		# Remove automatically added punctuations since there is no punctuation at the end of input
		while input_text[-1] not in SEPERATOR and text and text[-1] in SEPERATOR:
			text = text[:-1]

		# Remove automatically added punctuations since there is no punctuation at the begin of input
		while input_text[0] not in SEPERATOR and text and text[0] in SEPERATOR:
			text = text[1:]

	def _has_target_language(self, text: str):
		return has_chinese(text)


class ChineseTypoCorrector(BaseTypoCorrector):

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)

		if self.language == "zh_traditional":
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

		response_zh_list = []
		response_non_zh_list = []
		for char in response_text:
			if is_chinese_character(char):
				response_zh_list.append(char)
			else:
				response_non_zh_list.append(char)

		text_zh_list = []
		text_non_zh_list = []
		for char in text:
			if is_chinese_character(char):
				text_zh_list.append(char)
			else:
				text_non_zh_list.append(char)

		if len(response_zh_list) != len(text_zh_list):
			if len(response_non_zh_list) == len(text_non_zh_list):
				return True
			else:
				return False  # Some non-Chinese chars may become Chinese chars. Skip the case.

		for i in range(len(text_zh_list)):
			if len(set(get_char_pinyin(text_zh_list[i])) & set(get_char_pinyin(response_zh_list[i]))) == 0:
				return True
		return False

	def _text_preprocess(self, input_text: str):
		return self.prefix + input_text + self.suffix

	def _text_postprocess(self, text: str, input_text: str):
		text = text[(len(self.prefix) + len(self.answer_string)):(len(text) - len(self.suffix))]

		# Remove automatically added punctuations since there is no punctuation at the end of input
		while input_text[-1] not in SEPERATOR and text and text[-1] in SEPERATOR:
			text = text[:-1]

		# Remove automatically added punctuations since there is no punctuation at the begin of input
		while input_text[0] not in SEPERATOR and text and text[0] in SEPERATOR:
			text = text[1:]

		return text

	def _has_target_language(self, text: str):
		return has_chinese(text)
