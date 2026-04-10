import chinese_converter

from ...text.chinese import SEPERATOR, has_chinese, has_simplified_chinese_char, has_traditional_chinese_char
from ..base import BaseTextPolicy


class TypoTextPolicy(BaseTextPolicy):
	def __init__(self, language: str, prefix: str = "", suffix: str = "", question_string: str = "", answer_string: str = ""):
		self.language = language
		self.prefix = prefix
		self.suffix = suffix
		self.question_string = question_string
		self.answer_string = answer_string

	def preprocess_input(self, input_text: str) -> str:
		return self.prefix + input_text + self.suffix

	def wrap_history_response(self, response_text: str) -> str:
		return self.prefix + response_text + self.suffix

	def postprocess_output(self, text: str, input_text: str) -> str:
		input_text_tmp = self.prefix + input_text + self.suffix

		prefix_to_strip = self.prefix + self.answer_string
		if prefix_to_strip and text.startswith(prefix_to_strip):
			text = text[len(prefix_to_strip):]
		if self.suffix and text.endswith(self.suffix):
			text = text[:-len(self.suffix)]

		while input_text_tmp[-1] not in SEPERATOR and text and text[-1] in SEPERATOR:
			text = text[:-1]

		if text and text[-1] not in SEPERATOR and input_text[-1] in SEPERATOR:
			for i in range(len(input_text_tmp)):
				if input_text_tmp[-1 - i] not in SEPERATOR:
					text += input_text_tmp[-i:]
					break

		while input_text_tmp[0] not in SEPERATOR and text and text[0] in SEPERATOR:
			text = text[1:]

		return text

	def has_target_language(self, text: str) -> bool:
		return has_chinese(text)

	def normalize_response(self, sentence: str) -> str:
		if self.language == "zh_traditional" and has_simplified_chinese_char(sentence):
			sentence = chinese_converter.to_traditional(sentence)
		if self.language == "zh_simplified" and has_traditional_chinese_char(sentence):
			sentence = chinese_converter.to_simplified(sentence)
		return sentence


class LiteTypoTextPolicy(TypoTextPolicy):
	pass


class StandardTypoTextPolicy(TypoTextPolicy):
	def __init__(self, language: str):
		if language == "zh_traditional":
			prefix = "我說"
		elif language == "zh_simplified":
			prefix = "我说"
		else:
			raise NotImplementedError

		super().__init__(language=language, prefix=prefix)
