import os
import sys

import addonHandler
import api
import config
import globalPluginHandler
from scriptHandler import script
import textInfos
import ui

PATH = os.path.dirname(__file__)

PYTHON_PATH = os.path.join(PATH, 'python')
sys.path.insert(0, PYTHON_PATH)

PACKAGE_PATH = os.path.join(PATH, 'package')
sys.path.insert(0, PACKAGE_PATH)

from .python.http import cookies as httpcookies
sys.modules['http.cookies'] = httpcookies

from .python.http import client as httpclient
sys.modules['http.client'] = httpclient

from .python import importlib
sys.modules['importlib'] = importlib

import requests

addonHandler.initTranslation()
ADDON_SUMMARY = "GPTAssistant"

config.conf.spec["Access8Graph"] = {}


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)

	def terminate(self, *args, **kwargs):
		super().terminate(*args, **kwargs)

	@script(
		gesture="kb:NVDA+alt+o",
		description=_("GPT"),
		category=ADDON_SUMMARY,
	)
	def script_action(self, gesture):
		print("YA")
		obj = api.getFocusObject()
		text = obj.makeTextInfo(textInfos.POSITION_SELECTION).text
		ui.message(f"原文是: {text}")
		text_corrected = self._get_openai_completion_response(text)
		self._report_typos(text, text_corrected)

	def _report_typos(self, text_original, text_corrected):
		text_original_split = text_original.split('\r\n')
		text_corrected_split = text_corrected.split('\n')
		error_count = 0

		ui.message(f"分析結果如下:")

		for row in range(len(text_original_split)):
			for col in range(len(text_original_split[row])):
				if text_original_split[row][col] != text_corrected_split[row][col]:
					ui.message(f"row {row + 1}, column {col + 1}: {text_original_split[row][col]} 應改成 {text_corrected_split[row][col]}")
					error_count += 1

		ui.message(f"共有錯字{error_count}個")

	def _get_openai_completion_response(self, prompt_text):
		prompt_augmented = f'改錯字\n\n題目:{prompt_text}\n\n答案:'

		API_KEY = ''

		# GPT 3.5

		url = "https://api.openai.com/v1/chat/completions"
		headers = {
			"Content-Type": "application/json",
			"Authorization": f"Bearer {API_KEY}",
		}
		data = {
			'model': 'gpt-3.5-turbo',
			'messages': [
				{
					"role": "user",
					"content": prompt_augmented
				}
			]
		}

		response = requests.post(url, headers=headers, json=data).json()
		return response['choices'][0]['message']['content']

		# GPT 3

		url =  "https://api.openai.com/v1/completions"
		headers = {"Authorization": f"Bearer {API_KEY}"}
		data = {
			'model': 'text-davinci-003',
			'prompt': prompt_augmented,
			'max_tokens': 60,
			'temperature': 0,
		}

		response = requests.post(url, headers=headers, json=data).json()

		return response['choices'][0]['text']


'''
Example input cases:
今天天器真好，
好想初去完，
結數回家吃泛。
Expected output:
今天天氣真好，
好想出去玩，
結束回家吃飯。
'''
''
