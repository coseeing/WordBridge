from collections import defaultdict
from copy import deepcopy
from threading import Thread
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Tuple

import json
import logging
import os
import random
import requests
import time

from pypinyin import lazy_pinyin, Style
from .utils import get_char_pinyin, has_chinese, has_simplified_chinese_char, has_traditional_chinese_char
from .utils import PUNCTUATION, SEPERATOR, is_chinese_character, strings_diff, text_segmentation
from .utils import find_correction_errors, get_segments_to_recorrect

import chinese_converter


try:
	import addonHandler
	addonHandler.initTranslation()
except ImportError:
	def _(s):
		return s


log = logging.getLogger(__name__)

BASE_API_URLS = {
	"openai": "https://api.openai.com",
	"baidu": "https://aip.baidubce.com",
	"ollama": "http://localhost:11434",
}


class CorrectorResult():
	def __init__(
		self,
		original_text: str,
		corrected_text: str,
		response_json: Dict,
	):
		self.original_text = original_text
		self.corrected_text = corrected_text
		self.response_json = response_json


class BaseTypoCorrector():

	def __init__(
		self,
		model: str,
		provider: str,
		credential: dict,
		language: str,
		template_name: str = "Standard_v1.json",
		optional_guidance_enable: dict = None,
		customized_words: list = [],
		llm_settings: dict = {},
		max_correction_attempts: int = 3,
		httppost_retries: int = 2,
		backoff: int = 1,
	):

		self.model = model
		self.provider = provider.lower()
		self.max_correction_attempts = max_correction_attempts
		self.httppost_retries = httppost_retries
		self.backoff = backoff
		self.credential = credential
		self.language = language
		self.optional_guidance_enable = optional_guidance_enable
		if self.optional_guidance_enable is None:
			if self.provider == "openai":
				self.optional_guidance_enable = {
					"no_explanation": False,
					"keep_non_chinese_char": True,
				}
			elif self.provider == "baidu":
				self.optional_guidance_enable = {
					"no_explanation": True,
					"keep_non_chinese_char": False,
				}
			else:
				self.optional_guidance_enable = {
					"no_explanation": False,
					"keep_non_chinese_char": False,
				}

		self.customized_words = customized_words
		self.llm_settings = llm_settings
		self.response_history = []

		file_dirpath = os.path.dirname(__file__)
		template_path = os.path.join(file_dirpath, "..", "template", template_name)
		with open(template_path, "r", encoding="utf8") as f:
			self.template = json.loads(f.read())

		self.prefix = ""
		self.suffix = ""
		self.question_string = ""
		self.answer_string = ""

	def correct_text(self, text: str, batch_mode: bool = True, fake_corrected_text: str = None) -> Tuple:
		"""
		Analyze typos of text using self.segment_corrector. It also analyzes the difference between the original
		text and corrected text.

		Parameters:
			text (str): The text to be analyzed for typos.
			batch_mode (bool): If specified, enable multithread for typo correction
			fake_corrected_text (str, optional): If specified, return input text without correction steps.

		Returns:
			A tuple containing the corrected text and a list of differences between the original and corrected text.
		"""
		if fake_corrected_text is not None:
			return fake_corrected_text, strings_diff(text, fake_corrected_text)

		if self.provider in ["openai", "baidu"]:
			self._try_internet_connection(BASE_API_URLS[self.provider])

		text_corrected = ""
		segments = text_segmentation(text, max_length=100)

		# Typo correction
		if batch_mode:
			corrector_result_list = self.correct_segment_batch(segments)
		else:
			corrector_result_list = [self.correct_segment(segment) for segment in segments]
		for corrector_result in corrector_result_list:
			text_corrected += corrector_result.corrected_text
			self.response_history.append(corrector_result.response_json)

		# Find typo and keep correcting
		recorrection_history = None
		for i in range(self.max_correction_attempts):
			# Find typo
			text_corrected_previous = text_corrected
			text_corrected_revised, typo_indices = find_correction_errors(text, text_corrected)

			# No typo, stop correction
			if text_corrected_revised == text_corrected:
				break

			# Keep correction
			text_corrected = ""
			segments_revised = text_segmentation(text_corrected_revised, max_length=20)
			if recorrection_history is None:
				recorrection_history = [[] for _ in range(len(segments_revised))]
			segments_to_recorrect = get_segments_to_recorrect(segments_revised, typo_indices)
			for j in range(len(segments_to_recorrect)):
				if segments_to_recorrect[j]:
					print(f"iter = {i}, segment = {segments_revised[j]} isn't correct => {segments_to_recorrect[j]}, text_corrected_previous = {text_corrected_previous}")

			history_for_correction = recorrection_history if i >= self.max_correction_attempts / 3 else [[] for _ in range(len(segments_revised))]

			if batch_mode:
				corrector_result_list = self.correct_segment_batch(segments_to_recorrect, history_for_correction)
			else:
				corrector_result_list = [self.correct_segment(segment, segment_previous) for segment, segment_previous in zip(segments_to_recorrect, history_for_correction)]

			for j in range(len(segments_revised)):
				if corrector_result_list[j].corrected_text:
					text_corrected += corrector_result_list[j].corrected_text
					if corrector_result_list[j].corrected_text not in recorrection_history[j] and\
						len(corrector_result_list[j].corrected_text) < len(text) * 2:
						recorrection_history[j].append(corrector_result_list[j].corrected_text)
					self.response_history.append(corrector_result_list[j].response_json)
				else:
					text_corrected += segments_revised[j]

		diff = strings_diff(text, text_corrected)

		return text_corrected, diff


	def correct_segment(self, input_text: str, previous_results: list = [], fake_operation: bool = False) -> str:
		if fake_operation or not self._has_target_language(input_text):
			return CorrectorResult(input_text, input_text, [])

		input_info = self._get_input_info(input_text)

		if input_info["focus_typo"]:
			message_template = deepcopy(self.template[self.language]["message_tag"])
		else:
			message_template = deepcopy(self.template[self.language]["message"])
		for i in range(len(message_template)):
			message_template[i]["content"] = message_template[i]["content"].replace("\\n", "\n")
		text = self._text_preprocess(input_text)
		input_prompt = self._create_input(message_template, text, input_info)

		response_json = self._chat_completion(input_prompt, previous_results, input_info)
		response_text = self._parse_response(response_json)
		output_text = self._text_postprocess(response_text, input_text)

		corrector_result = CorrectorResult(
			original_text=input_text,
			corrected_text=output_text,
			response_json=response_json,
		)

		return corrector_result

	def correct_segment_batch(self, input_text_list: list, previous_results_list: list = []) -> list:
		assert isinstance(input_text_list, list)

		if not previous_results_list:
			previous_results_list = [[] for _ in range(len(input_text_list))]

		if not input_text_list:
			return input_text_list

		output_text_list = [None] * len(input_text_list)

		futures = []
		with ThreadPoolExecutor(max_workers=20) as executor:
			future_to_index = {
				executor.submit(
					self._correct_segment_task,
					input_text_list[index],
					previous_results_list[index],
					output_text_list,
					index,
				): index for index in range(len(input_text_list))
			}
			try:
				for future in as_completed(future_to_index):
					future.result()
			except Exception as e:
				executor.shutdown(wait=False)
				raise e

		return output_text_list

	def get_total_usage(self) -> Dict:
		"""
		Get the total usage of OpenAI model (in tokens)

		Returns:
			The total usage of OpenAI model (in tokens)
		"""
		if self.provider == "ollama":
			return {}
		total_usage = defaultdict(int)
		for response in self.response_history:
			for usage_type in response["usage"].keys():
				total_usage[usage_type] += response["usage"][usage_type]
		return total_usage

	def _correct_segment_task(
		self,
		input_text: str,
		previous_results: list,
		output_text_list: list,
		index: int,
	) -> str:
		text = self.correct_segment(input_text, previous_results)
		output_text_list[index] = text

	def _try_internet_connection(self, url, timeout=10, try_count=1):
		for r in range(try_count):
			try:
				response = requests.get(url, timeout=timeout)
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

	def _get_api_url(self):
		if self.provider == "openai":
			api_url = BASE_API_URLS[self.provider] + "/v1/chat/completions"
		elif self.provider == "ollama":
			api_url = BASE_API_URLS[self.provider] + "/api/chat"
		elif self.provider == "baidu":
			api_key = self.credential["api_key"]
			secret_key = self.credential["secret_key"]
			url_get_access = BASE_API_URLS[self.provider] + "/oauth/2.0/token" +\
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
			api_url = BASE_API_URLS[self.provider] + "/rpc/2.0/ai_custom/v1/wenxinworkshop/chat/" +\
						f"{self.model}?access_token=" + access_token
		else:
			raise NotImplementedError("Subclass must implement this method")

		return api_url

	def _get_input_info(self, input_text):
		input_info = {
			"input_text": input_text,
			"contain_non_chinese": False,
			"focus_typo": True if "[[" in input_text and "]]" in input_text else False
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
		# Load default setting
		setting_path = os.path.join(os.path.dirname(__file__), "..", "llm_setting", self.provider + ".json")
		with open(setting_path, "r", encoding="utf8") as f:
			setting = json.loads(f.read())

		for k in self.llm_settings:
			setting[k] = self.llm_settings[k]

		if input_info["focus_typo"]:
			system_template = deepcopy(self.template[self.language]["system_tag"])
			system_template = system_template.replace("\\n", "\n")
			system_template = self._system_add_guidance(system_template, input_info)
		else:
			system_template = deepcopy(self.template[self.language]["system"])
			system_template = system_template.replace("\\n", "\n")
			system_template = self._system_add_guidance(system_template, input_info)
		if self.provider == "openai":
			messages = [{"role": "system", "content": system_template}] + messages
			data = {
				"model": self.model,
				"messages": messages,
				**setting,
			}
		elif self.provider == "baidu":
			if "temperature" in setting:
				setting["temperature"] = max(setting["temperature"], 0.0001)
			if "max_output_tokens" in setting:
				setting["max_output_tokens"] = min(setting["max_output_tokens"], len(messages[-1]["content"]))
			data = {
				"messages": messages,
				"system": system_template,
				**setting,
			}
		elif self.provider == "ollama":
			messages = [{"role": "system", "content": system_template}] + messages
			data = {
				"model": self.model,
				"messages": messages,
				"stream": False,
				**setting,
			}
		else:
			raise NotImplementedError("Subclass must implement this method")

		return data

	def _get_headers(self):
		if self.provider == "openai":
			headers = {"Authorization": f"Bearer {self.credential['api_key']}"}
		elif self.provider == "baidu":
			headers = {'Content-Type': 'application/json'}
		elif self.provider == "ollama":
			headers = {'Content-Type': 'application/json'}
		else:
			raise NotImplementedError("Subclass must implement this method")

		return headers

	def _chat_completion(self, input: List, response_text_history: List, input_info: dict) -> str:
		messages = deepcopy(input)
		comment_template = deepcopy(self.template[self.language]["comment"])
		comment_template = comment_template.replace("\\n", "\n")
		for response_previous in response_text_history:
			response_previous = self.prefix + response_previous + self.suffix
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
			timeout = min(5 * (r + 1), 15) if self.provider != "ollama" else 300
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

		if self.provider == "openai" and response.status_code != 200:
			self._handle_openai_errors(response)

		if self.provider == "baidu" and ("error_code" in response_json or not response_json["result"]):
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
		if self.provider == "openai":
			sentence = response["choices"][0]["message"]["content"]
		elif self.provider == "baidu":
			sentence = response["result"]
		elif self.provider == "ollama":
			sentence = response["message"]["content"]
		else:
			raise NotImplementedError("Subclass must implement this method")

		if self.language == "zh_traditional" and has_simplified_chinese_char(sentence):
			sentence = chinese_converter.to_traditional(sentence)
		if self.language == "zh_simplified" and has_traditional_chinese_char(sentence):
			sentence = chinese_converter.to_simplified(sentence)

		return sentence

	def _create_input(self, template: str, text: str, input_info: dict):
		raise NotImplementedError("Subclass must implement this method")

	def _text_preprocess(self, input_text: str):
		return self.prefix + input_text + self.suffix

	def _text_postprocess(self, text: str, input_text: str):
		input_text_tmp = self.prefix + input_text + self.suffix

		# Remove automatically added punctuations since there is no punctuation at the end of input
		while input_text_tmp[-1] not in SEPERATOR and text and text[-1] in SEPERATOR:
			text = text[:-1]

		if text[-1] not in SEPERATOR and input_text[-1] in SEPERATOR:
			for i in range(len(input_text_tmp)):
				if input_text_tmp[-1 - i] not in SEPERATOR:
					text += input_text_tmp[-i:]
					break

		# Remove automatically added punctuations since there is no punctuation at the begin of input
		while input_text_tmp[0] not in SEPERATOR and text and text[0] in SEPERATOR:
			text = text[1:]

		text = text[(len(self.prefix) + len(self.answer_string)):(len(text) - len(self.suffix))]
		return text

	def _has_target_language(self, text: str):
		raise NotImplementedError("Subclass must implement this method")


class ChineseTypoCorrectorLite(BaseTypoCorrector):

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)

	def _create_input(self, template: str, text: str, input_info: dict):
		template[-1]["content"] = template[-1]["content"].replace("{{text_input}}", text)
		return template

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

	def _create_input(self, template: str, text: str, input_info: dict):
		phone = ' '.join(lazy_pinyin(text, style=Style.TONE3))
		if input_info["focus_typo"]:
			phone = phone.replace("[[ ", "[[").replace(" ]]", "]]").replace("]][[", "]] [[")

		for i in range(len(template)):
			template[i]["content"] = template[i]["content"].replace("{{text_input}}", text)
			template[i]["content"] = template[i]["content"].replace("{{phone_input}}", phone)
			template[i]["content"] = template[i]["content"].replace("{{QUESTION}}", self.question_string)
			template[i]["content"] = template[i]["content"].replace("{{ANSWER}}", self.answer_string)

		return template

	def _has_target_language(self, text: str):
		return has_chinese(text)
