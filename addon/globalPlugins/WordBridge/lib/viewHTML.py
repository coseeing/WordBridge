import json
import os
import re

import addonHandler

addonHandler.initTranslation()

PATH = os.path.dirname(os.path.dirname(__file__))
TEMPLATES_PATH = os.path.join(PATH, "web", "templates")
CONTENT_CONFIG_PLACEHOLDER = "__CONTEXT__"

# json.dumps does not encode these, so a "</script>" sequence inside the
# selected text or the model output would terminate the inline script element.
# All five are valid JSON string escapes, so JSON.parse returns the original
# value unchanged.
JS_STRING_ESCAPES = {
	"<": "\\u003c",
	">": "\\u003e",
	"&": "\\u0026",
	" ": "\\u2028",
	" ": "\\u2029",
}


def _escape_for_inline_script(serialized: str) -> str:
	for character, escape in JS_STRING_ESCAPES.items():
		serialized = serialized.replace(character, escape)
	return serialized


def text2template(src, dst, title=None):
	with open(src, "r", encoding="utf8") as f:
		value = f.read()

	decimal_pattern = re.compile(r"&#([\d]+);")
	value = decimal_pattern.sub(lambda m: chr(int(m.group(1))), value)

	hexadecimal_pattern = re.compile(r"&#x([\dABCDEFabcdef]+);")
	value = hexadecimal_pattern.sub(lambda m: chr(int(m.group(1), 16)), value)

	if not title:
		try:
			name = os.path.basename(src).split(".")
			if len(name) > 1:
				name = name[:-1]
			title = ".".join(name)
		except BaseException:
			title = "WordBridge"

	content_config = {
		"title": title,
		"data": value,
		"raw": value,
	}
	with open(os.path.join(TEMPLATES_PATH, "index.template"), "r", encoding="utf8") as f:
		template = f.read()
	content = template.replace(
		CONTENT_CONFIG_PLACEHOLDER,
		_escape_for_inline_script(json.dumps(content_config, ensure_ascii=False)),
	)
	with open(dst, "w", encoding="utf8", newline="") as f:
		f.write(content)
	return dst
