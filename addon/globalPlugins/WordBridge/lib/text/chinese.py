from hanzidentifier import identify
from hanzidentifier import MIXED, SIMPLIFIED, TRADITIONAL

try:
	from languageHandler import getLanguage
	from speech.speech import getCharDescListFromText
except ImportError:
	getLanguage = None
	getCharDescListFromText = None


SEPERATOR = "﹐，,.。﹒．｡!ǃⵑ︕！;;︔﹔；?︖﹖？⋯ "
PUNCTUATION = "﹐，,.。﹒．｡:׃∶˸︓﹕：!ǃⵑ︕！;;︔﹔；?︖﹖？⋯ \n\r\t\"\'#$%&()*+-/<=>@[\\]^_`{|}~"

ZH_UNICODE_INTERVALS = [
	["\u4e00", "\u9fff"],
	["\u3400", "\u4dbf"],
	["\u20000", "\u2a6df"],
	["\u2a700", "\u2b739"],
	["\u2b740", "\u2b81d"],
	["\u2b820", "\u2cea1"],
	["\u2ceb0", "\u2ebe0"],
	["\u30000", "\u3134a"],
	["\u31350", "\u323af"],
	["\u3100", "\u312f"],
	["\u31a0", "\u31bf"],
	["\uf900", "\ufaff"],
	["\u2f800", "\u2fa1f"],
]


def is_chinese_character(char: str) -> bool:
	assert len(char) <= 1, "Length of char should not be larger than 1."
	if not char:
		return False

	for interval in ZH_UNICODE_INTERVALS:
		if char >= interval[0] and char <= interval[1]:
			return True

	return False


def has_chinese(text: str):
	for char in text:
		if is_chinese_character(char):
			return True
	return False


def has_simplified_chinese_char(text: str):
	return identify(text) in [SIMPLIFIED, MIXED]


def has_traditional_chinese_char(text: str):
	return identify(text) in [TRADITIONAL, MIXED]


def get_descs(text: str) -> str:
	if not text or getLanguage is None or getCharDescListFromText is None:
		return ""

	if len(text) > 1:
		return [[text, [" ".join(list(text))]]]

	return getCharDescListFromText(text, getLanguage())
