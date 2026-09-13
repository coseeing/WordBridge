import json
import re
import subprocess
from pathlib import Path


TEMPLATE_PATH = (
	Path(__file__).parents[1]
	/ "addon"
	/ "globalPlugins"
	/ "WordBridge"
	/ "web"
	/ "templates"
	/ "index.template"
)


def _open_replace_dialog_html():
	template = TEMPLATE_PATH.read_text(encoding="utf-8")
	scripts = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", template, re.DOTALL)
	application_script = scripts[-1]
	node_script = f"""
		const vm = require("node:vm");
		let component;
		let dialog;
		const context = {{
			Vue: {{
				createApp(value) {{ component = value; return {{ mount() {{}} }}; }},
				ref(value) {{ return {{ value }}; }},
			}},
			Swal: {{ fire(options) {{ dialog = options; }} }},
			document: {{ title: "" }},
			window: {{ contentConfig: {{ title: "測試", data: "[]", raw: "[]" }} }},
		}};
		vm.runInNewContext({json.dumps(application_script)}, context);
		component.setup().openInfos({{
			operation: "文字替換",
			descs_before: [["錯", ["錯字詞"]]],
			descs_after: [["對", ["正確詞"]]],
		}});
		process.stdout.write(dialog.html);
	"""
	result = subprocess.run(
		["node", "-e", node_script],
		check=True,
		capture_output=True,
		text=True,
	)
	return result.stdout


def test_replace_dialog_labels_original_text_before_corrected_text():
	html = _open_replace_dialog_html()

	original_label_index = html.index(
		'<h3 class="correction-dialog__label correction-dialog__label--original">原始文字</h3>'
	)
	original_description_index = html.index("錯字詞")
	corrected_label_index = html.index(
		'<h3 class="correction-dialog__label correction-dialog__label--corrected">修正文字</h3>'
	)
	corrected_description_index = html.index("正確詞")

	assert original_label_index < original_description_index < corrected_label_index < corrected_description_index


def test_dialog_uses_paragraphs_for_text_and_lists_only_for_descriptions():
	html = _open_replace_dialog_html()

	assert '<div class="correction-dialog__entry"><p class="correction-dialog__text">錯</p><ul><li>錯字詞</li></ul></div>' in html
	assert '<div class="correction-dialog__entry"><p class="correction-dialog__text">對</p><ul><li>正確詞</li></ul></div>' in html
	assert "<ul><li>錯:" not in html


def test_dialog_text_is_centered_in_its_entry():
	template = TEMPLATE_PATH.read_text(encoding="utf-8")

	text_rule = re.search(
		r"\.correction-dialog__text \{(?P<properties>.*?)\n\t\t\t\}",
		template,
		re.DOTALL,
	)
	assert text_rule is not None
	assert "align-self: center;" in text_rule.group("properties")


def test_dialog_labels_have_distinct_status_styles():
	template = TEMPLATE_PATH.read_text(encoding="utf-8")

	assert ".correction-dialog__label--original" in template
	assert "background: #eee6d8;" in template
	assert ".correction-dialog__label--corrected" in template
	assert "background: #dce9e6;" in template
