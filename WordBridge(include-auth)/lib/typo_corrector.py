from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from decimal import Decimal
from threading import Thread
from typing import Any, Dict, List, Tuple

import json
import logging
import os
import random
import time

import requests

from pypinyin import lazy_pinyin, Style
from .provider import OpenaiProvider, AnthropicProvider, BaiduProvider, OpenrouterProvider, DeepseekProvider, GoogleProvider
from .utils import get_char_pinyin, has_chinese, has_simplified_chinese_char, has_traditional_chinese_char
from .utils import PUNCTUATION, SEPERATOR, is_chinese_character, strings_diff, text_segmentation
from .utils import find_correction_errors, review_correction_errors, get_segments_to_recorrect

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
		response_json: Dict,
	):
		self.original_text = original_text
		self.corrected_text = corrected_text
		self.response_json = response_json


class BaseTypoCorrector():
	PROVIDER = {
		"openai": OpenaiProvider,
		"anthropic": AnthropicProvider,
		"baidu": BaiduProvider,
		"deepseek": DeepseekProvider,
		"google": GoogleProvider,
		"openrouter": OpenrouterProvider,
	}
	MODEL = {
		"claude-3-5-haiku-20241022": {
			"usage_key": "usage",
			"input_tokens": "0.8",
			"cache_creation_input_tokens": "1",
			"cache_read_input_tokens": "0.08",
			"output_tokens": "4",
			"base_unit": "1000000"
		},
		"claude-3-7-sonnet-20250219": {
			"usage_key": "usage",
			"input_tokens": "3",
			"cache_creation_input_tokens": "3.75",
			"cache_read_input_tokens": "0.3",
			"output_tokens": "15",
			"base_unit": "1000000"
		},
		"claude-sonnet-4-20250514": {
			"usage_key": "usage",
			"input_tokens": "3",
			"cache_creation_input_tokens": "3.75",
			"cache_read_input_tokens": "0.3",
			"output_tokens": "15",
			"base_unit": "1000000"
		},
		"deepseek-v3": {},
		"deepseek-chat": {
			"usage_key": "usage",
			"prompt_cache_hit_tokens": "0.07",
			"prompt_cache_miss_tokens": "0.27",
			"completion_tokens": "1.1",
			"base_unit": "1000000"
		},
		"deepseek-reasoner": {
			"usage_key": "usage",
			"prompt_cache_hit_tokens": "0.14",
			"prompt_cache_miss_tokens": "0.55",
			"completion_tokens": "2.19",
			"base_unit": "1000000"
		},
		"deepseek/deepseek-chat:free": {},
		"deepseek/deepseek-chat-v3-0324:free": {},
		"deepseek/deepseek-r1-0528:free": {},
		"deepseek/deepseek-r1-0528-qwen3-8b:free": {},
		"gemini-2.5-flash-preview-05-20": {
			"usage_key": "usageMetadata",
			"promptTokenCount": "0.15",
			"candidatesTokenCount": "0.6",
			"base_unit": "1000000"
		},
		"gemini-2.5-pro-preview-06-05": {
			"usage_key": "usageMetadata",
			"promptTokenCount": "1.25",
			"candidatesTokenCount": "10",
			"base_unit": "1000000"
		},
		"gpt-4o-2024-08-06": {
			"usage_key": "usage",
			"prompt_tokens": "2.5",
			"completion_tokens": "10",
			"base_unit": "1000000"
		},
		"gpt-4o-mini-2024-07-18": {
			"usage_key": "usage",
			"prompt_tokens": "0.15",
			"completion_tokens": "0.6",
			"base_unit": "1000000"
		},
		"gpt-4.1-2025-04-14": {
			"usage_key": "usage",
			"prompt_tokens": "2",
			"completion_tokens": "8",
			"base_unit": "1000000"
		},
		"gpt-4.1-mini-2025-04-14": {
			"usage_key": "usage",
			"prompt_tokens": "0.4",
			"completion_tokens": "1.6",
			"base_unit": "1000000"
		},
		"gpt-4.1-nano-2025-04-14": {
			"usage_key": "usage",
			"prompt_tokens": "0.1",
			"completion_tokens": "0.4",
			"base_unit": "1000000"
		},
		"o4-mini-2025-04-16": {
			"usage_key": "usage",
			"prompt_tokens": "1.1",
			"completion_tokens": "4.4",
			"base_unit": "1000000"
		},
		"gpt-5-chat-latest": {
			"usage_key": "usage",
			"prompt_tokens": "1.25",
			"completion_tokens": "10",
			"base_unit": "1000000",
		},
		"gpt-5": {
			"usage_key": "usage",
			"prompt_tokens": "1.25",
			"completion_tokens": "10",
			"base_unit": "1000000",
		},
		"gpt-5-mini": {
			"usage_key": "usage",
			"prompt_tokens": "0.25",
			"completion_tokens": "2",
			"base_unit": "1000000",
		},
		"gpt-5-nano": {
			"usage_key": "usage",
			"prompt_tokens": "0.05",
			"completion_tokens": "0.4",
			"base_unit": "1000000",
		},
		"ernie-4.0-turbo-8k": {},
	}

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
		self.provider_object = self.PROVIDER[provider.lower()](credential, model)

		self.max_correction_attempts = max_correction_attempts
		self.httppost_retries = httppost_retries
		self.backoff = backoff
		self.language = language
		self.optional_guidance_enable = optional_guidance_enable

		self.customized_words = customized_words
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

		base_url = self.provider_object.base_url
		self._try_internet_connection(base_url)

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
			# for j in range(len(segments_to_recorrect)):
				# if segments_to_recorrect[j]:
					# print(f"iter = {i}, segment = {segments_revised[j]} isn't correct => {segments_to_recorrect[j]}, text_corrected_previous = {text_corrected_previous}")
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

		text_corrected = review_correction_errors(text, text_corrected)
		diff = strings_diff(text, text_corrected)

		return text_corrected, diff

	def correct_segment(self, input_text: str, previous_results: list = [], fake_operation: bool = False) -> str:
		if fake_operation or not self._has_target_language(input_text):
			return CorrectorResult(input_text, input_text, {})

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
		usage_key = self.MODEL[self.model].get("usage_key")
		total_usage = defaultdict(int)
		if not usage_key:
			return total_usage

		for response in self.response_history:
			if isinstance(response, dict) and usage_key in response:
				for usage_type in set(self.MODEL[self.model].keys()):
					if usage_type == "base_unit" or usage_type == "usage_key":
						continue
					try:
						total_usage[usage_type] += response[usage_key][usage_type]
					except KeyError:
						pass

		return total_usage

	def get_total_cost(self) -> int:
		"""
		Get the total cost of provider model (in USD)

		Returns:
			The total cost of provider model (in USDs)
		"""
		price_info = self.MODEL[self.model]
		cost = Decimal("0")
		usages = self.get_total_usage()
		for key, value in usages.items():
			cost += Decimal(price_info[key]) * Decimal(str(value)) / Decimal(price_info["base_unit"])

		return cost

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

	def _chat_completion(self, input: List, response_text_history: List, input_info: dict) -> str:
		messages = deepcopy(input)
		comment_template = deepcopy(self.template[self.language]["comment"])
		comment_template = comment_template.replace("\\n", "\n")
		for response_previous in response_text_history:
			response_previous = self.prefix + response_previous + self.suffix
			comment = comment_template.replace("{{response_previous}}", response_previous)
			messages.append({"role": "assistant", "content": response_previous})
			messages.append({"role": "user", "content": comment})

		if input_info["focus_typo"]:
			system_template = deepcopy(self.template[self.language]["system_tag"])
			system_template = system_template.replace("\\n", "\n")
			system_template = self._system_add_guidance(system_template, input_info)
		else:
			system_template = deepcopy(self.template[self.language]["system"])
			system_template = system_template.replace("\\n", "\n")
			system_template = self._system_add_guidance(system_template, input_info)

		request_data = self.provider_object.get_request_data(messages, system_template)
		api_url = self.provider_object.url
		headers = self.provider_object.get_headers()

		return self._post_with_retries(request_data, api_url, headers)

	def _post_with_retries(self, request_data, api_url, headers):
		backoff = self.backoff
		response_json = None
		timeout0 = self.provider_object.timeout0
		timeout_max = self.provider_object.timeout_max
		for r in range(self.httppost_retries):
			timeout = min(timeout0 * (r + 1), timeout_max) if self.provider_object.name != "ollama" else 300
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
						provider=self.provider_object.name,
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

		self.provider_object.handle_errors(response)
		return response.json()

	def _parse_response(self, response: str) -> str:
		# ollama: sentence = response["message"]["content"]

		try:
			sentence = self.provider_object.parse_response(response)
		except KeyError as e:
			log.error(
				f"{response}"
			)
			raise Exception(_(f"Parsing error. Unexpected server response. Response: {response}"))

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

		if text and text[-1] not in SEPERATOR and input_text[-1] in SEPERATOR:
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
		for i in range(len(template)):
			template[i]["content"] = template[i]["content"].replace("{{text_input}}", text)
			template[i]["content"] = template[i]["content"].replace("{{QUESTION}}", self.question_string)
			template[i]["content"] = template[i]["content"].replace("{{ANSWER}}", self.answer_string)
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
