from collections import defaultdict
from copy import deepcopy
from decimal import Decimal
from typing import Any, Dict, List, Tuple
from pathlib import Path

import json
import logging
import os

from pypinyin import lazy_pinyin, Style
from .provider import get_provider
from .utils import get_char_pinyin, has_chinese, has_simplified_chinese_char, has_traditional_chinese_char
from .utils import PUNCTUATION, SEPERATOR, is_chinese_character, strings_diff, text_segmentation
from .utils import find_correction_errors, review_correction_errors, get_segments_to_recorrect, parallel_map
from .cost_calculator import CostCalculator

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


class CorrectionOrchestrator:
	def __init__(self, corrector: 'BaseTypoCorrector'):
		self.corrector = corrector

	def execute(self, text: str, batch_mode: bool = True, fake_corrected_text: str = None) -> Tuple[str, List]:
		"""
		Orchestrate the full text correction process.
		
		Returns:
			A tuple containing the corrected text and a list of differences.
		"""
		if fake_corrected_text is not None:
			return fake_corrected_text, strings_diff(text, fake_corrected_text)

		self.corrector.provider_object.try_connection()

		# Initial correction pass
		text_corrected = ""
		segments = text_segmentation(text, max_length=100)

		if batch_mode:
			results = parallel_map(self.corrector.correct_segment, segments)
		else:
			results = [self.corrector.correct_segment(segment) for segment in segments]

		for res in results:
			text_corrected += res.corrected_text
			self.corrector.response_history.append(res.response_json)

		# Iterative refinement loop
		recorrection_history = None
		for i in range(self.corrector.max_correction_attempts):
			text_corrected_revised, typo_indices = find_correction_errors(text, text_corrected)

			# No more typos found, stable
			if text_corrected_revised == text_corrected:
				break

			text_corrected = ""
			segments_revised = text_segmentation(text_corrected_revised, max_length=20)
			if recorrection_history is None:
				recorrection_history = [[] for _ in range(len(segments_revised))]

			segments_to_recorrect = get_segments_to_recorrect(segments_revised, typo_indices)
			history_for_correction = recorrection_history if i >= self.corrector.max_correction_attempts / 3 else [[] for _ in range(len(segments_revised))]

			if batch_mode:
				results = parallel_map(
					self.corrector.correct_segment,
					segments_to_recorrect,
					iterable_kwargs=[{"previous_results": h} for h in history_for_correction]
				)
			else:
				results = [self.corrector.correct_segment(seg, h) for seg, h in zip(segments_to_recorrect, history_for_correction)]

			for j in range(len(segments_revised)):
				if results[j].corrected_text:
					res_text = results[j].corrected_text
					text_corrected += res_text
					if res_text not in recorrection_history[j] and len(res_text) < len(text) * 2:
						recorrection_history[j].append(res_text)
					self.corrector.response_history.append(results[j].response_json)
				else:
					text_corrected += segments_revised[j]

		final_text = review_correction_errors(text, text_corrected)
		diff = strings_diff(text, final_text)
		
		return final_text, diff


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
		self.provider_object = get_provider(provider, credential, model, llm_settings)

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

		config_key = f"{model}&{provider}"
		model_entry = self._load_model_config(config_key)
		self._cost_calculator = CostCalculator(model_entry)

	def _load_model_config(self, config_key: str) -> dict:
		config_path = Path(__file__).parent.parent / "setting" / "llm_models.json"
		with open(config_path, "r", encoding="utf8") as f:
			config = json.load(f)
		return config.get(config_key, {})

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

	def get_total_usage(self) -> Dict:
		return self._cost_calculator.get_total_usage(self.response_history)

	def get_total_cost(self) -> Decimal:
		return self._cost_calculator.get_total_cost(self.response_history)

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

		return self.provider_object.chat_completion(
			messages,
			system_template,
			retries=self.httppost_retries,
			backoff=self.backoff
		)

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
