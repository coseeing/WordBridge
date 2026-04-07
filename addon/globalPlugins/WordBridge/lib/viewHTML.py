import json
import os
import re

import addonHandler

addonHandler.initTranslation()

PATH = os.path.dirname(os.path.dirname(__file__))
TEMPLATES_PATH = os.path.join(PATH, "web", "templates")
CONTENT_CONFIG_PLACEHOLDER = "__CONTEXT__"


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
		json.dumps(content_config, ensure_ascii=False),
	)
	with open(dst, "w", encoding="utf8", newline="") as f:
		f.write(content)
	return dst
