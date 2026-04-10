from copy import deepcopy
import json
import os

from pypinyin import lazy_pinyin, Style

from .utils import PUNCTUATION, get_char_pinyin, is_chinese_character


class InstructionComposer:
	def __init__(
		self,
		language: str,
		template_name: str,
		optional_guidance_enable: dict = None,
		customized_words: list = None,
	):
		self.language = language
		self.optional_guidance_enable = optional_guidance_enable or {}
		self.customized_words = customized_words or []

		file_dirpath = os.path.dirname(__file__)
		template_path = os.path.join(file_dirpath, "..", "setting", "templates", template_name)
		with open(template_path, "r", encoding="utf8") as f:
			self.template = json.loads(f.read())

	def compose(self, input_text: str, response_text_history: list, text_policy):
		input_info = self._get_input_info(input_text)
		return (
			self.build_messages(input_text, response_text_history, text_policy, input_info),
			self.build_system_template(input_info),
		)

	def build_messages(self, input_text: str, response_text_history: list, text_policy, input_info: dict):
		preprocessed_text = text_policy.preprocess_input(input_text)

		if input_info["focus_typo"]:
			message_template = deepcopy(self.template[self.language]["message_tag"])
		else:
			message_template = deepcopy(self.template[self.language]["message"])

		message_template = self._replace_newlines_in_messages(message_template)
		messages = self._render_input_messages(message_template, preprocessed_text, input_info, text_policy)

		comment_template = self.template[self.language]["comment"].replace("\\n", "\n")
		for response_previous in response_text_history:
			response_previous_wrapped = text_policy.wrap_history_response(response_previous)
			comment = comment_template.replace("{{response_previous}}", response_previous_wrapped)
			messages.append({"role": "assistant", "content": response_previous_wrapped})
			messages.append({"role": "user", "content": comment})

		return messages

	def build_system_template(self, input_info: dict):
		if input_info["focus_typo"]:
			system_template = deepcopy(self.template[self.language]["system_tag"])
		else:
			system_template = deepcopy(self.template[self.language]["system"])

		system_template = system_template.replace("\\n", "\n")
		return self._add_system_guidance(system_template, input_info)

	def _replace_newlines_in_messages(self, messages):
		for i in range(len(messages)):
			messages[i]["content"] = messages[i]["content"].replace("\\n", "\n")
		return messages

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
						break
				if flag:
					candidates.append(word)
					break

		return candidates

	def _add_system_guidance(self, system_template: str, input_info: dict) -> str:
		guidance_list = []
		optional_guidance = self.template[self.language]["optional_guidance"]

		if self.optional_guidance_enable.get("no_explanation"):
			guidance_list.append(optional_guidance["no_explanation"])

		if self.optional_guidance_enable.get("keep_non_chinese_char") and input_info["contain_non_chinese"]:
			guidance_list.append(optional_guidance["keep_non_chinese_char"])

		word_candidate = self._find_word_candidate(input_info["input_text"], self.customized_words)
		if word_candidate:
			system_template = system_template + "\n" + optional_guidance["customized_words"] + "、".join(word_candidate)

		if not guidance_list:
			return system_template

		return system_template + "\n須注意: " + "、".join(guidance_list)

	def _render_input_messages(self, template: list, preprocessed_text: str, input_info: dict, text_policy):
		raise NotImplementedError("Subclass must implement this method")


class LiteInstructionComposer(InstructionComposer):
	def _render_input_messages(self, template: list, preprocessed_text: str, input_info: dict, text_policy):
		for i in range(len(template)):
			template[i]["content"] = template[i]["content"].replace("{{text_input}}", preprocessed_text)
			template[i]["content"] = template[i]["content"].replace("{{QUESTION}}", text_policy.question_string)
			template[i]["content"] = template[i]["content"].replace("{{ANSWER}}", text_policy.answer_string)
		return template


class StandardInstructionComposer(InstructionComposer):
	def _render_input_messages(self, template: list, preprocessed_text: str, input_info: dict, text_policy):
		phone = " ".join(lazy_pinyin(preprocessed_text, style=Style.TONE3))
		if input_info["focus_typo"]:
			phone = phone.replace("[[ ", "[[").replace(" ]]", "]]").replace("]][[", "]] [[")

		for i in range(len(template)):
			template[i]["content"] = template[i]["content"].replace("{{text_input}}", preprocessed_text)
			template[i]["content"] = template[i]["content"].replace("{{phone_input}}", phone)
			template[i]["content"] = template[i]["content"].replace("{{QUESTION}}", text_policy.question_string)
			template[i]["content"] = template[i]["content"].replace("{{ANSWER}}", text_policy.answer_string)
		return template
