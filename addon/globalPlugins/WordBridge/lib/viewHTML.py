import os
import re

from jinja2 import Environment, FileSystemLoader

import addonHandler

addonHandler.initTranslation()

PATH = os.path.dirname(os.path.dirname(__file__))
TEMPLATES_PATH = os.path.join(PATH, "web", "templates")
env = Environment(
	loader=FileSystemLoader(TEMPLATES_PATH),
	variable_start_string="{|{",
	variable_end_string="}|}"
)


def text2template(src, dst):
	with open(src, "r", encoding="utf8") as f:
		value = f.read()

	try:
		title = ".".join(os.path.basename(dst).split(".")[:-1])
	except BaseException:
		title = "WordBridge"
	backslash_pattern = re.compile(r"\\")
	data = backslash_pattern.sub(lambda m: m.group(0).replace("\\", "\\\\"), value)
	data = data.replace(r"`", r"\`")
	raw = data
	template = env.get_template("index.template")
	content = template.render({
		"title": title,
		"data": data,
		"raw": raw,
	})
	with open(dst, "w", encoding="utf8", newline="") as f:
		f.write(content)
	return dst
