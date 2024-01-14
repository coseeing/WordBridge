from .python.http import client as httpclient
from .python.http import cookies as httpcookies
from .python import importlib

import json
import os
import shutil
import sys
import threading
import time

sys.modules["http.cookies"] = httpcookies
sys.modules["http.client"] = httpclient
sys.modules["importlib"] = importlib

PATH = os.path.dirname(__file__)

PYTHON_PATH = os.path.join(PATH, "python")
sys.path.insert(0, PYTHON_PATH)

PACKAGE_PATH = os.path.join(PATH, "package")
sys.path.insert(0, PACKAGE_PATH)

from .dialogs import OpenAIGeneralSettingsPanel

from logHandler import log
from scriptHandler import script
from speech.speech import getCharDescListFromText
from tones import beep

import addonHandler
import api
import config
import globalPluginHandler
import gui
import textInfos
import ui
import wx

from .lib.proofreader import Proofreader
from .lib.typo_corrector import TypoCorrector, TypoCorrectorWithPhone
from .lib.viewHTML import text2template
from hanzidentifier import has_chinese


addonHandler.initTranslation()
ADDON_SUMMARY = "GPTAssistant"

config.conf.spec["GPTAssistant"] = {
	"settings": {
		"model": "string(default=gpt-3.5-turbo)",
		"gpt_access_method": "string(default=OpenAI API Key)",
		"openai_key": "string(default=Please Enter Your Key)",
		"account_name": "string(default=\0)",
		"password": "string(default=\0)",
		"max_word_count": "integer(default=100,min=2,max=200)",
	}
}


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		gui.settingsDialogs.NVDASettingsDialog.categoryClasses.append(OpenAIGeneralSettingsPanel)

	def terminate(self, *args, **kwargs):
		super().terminate(*args, **kwargs)
		gui.settingsDialogs.NVDASettingsDialog.categoryClasses.remove(OpenAIGeneralSettingsPanel)

	def onSettings(self, evt):
		wx.CallAfter(gui.mainFrame._popupSettingsDialog, gui.settingsDialogs.NVDASettingsDialog, OpenAIGeneralSettingsPanel)

	def OnPreview(self, file):
		def openfile():
			os.startfile(file)
		wx.CallAfter(openfile)

	def correct_typo(self):
		# text-davinci-003 may be deprecated inthe future version of GPTAssistant
		is_chat_completion = True
		if config.conf["GPTAssistant"]["settings"]["model"] == "text-davinci-003":
			is_chat_completion = False

		corrector = TypoCorrectorWithPhone(
			model=config.conf["GPTAssistant"]["settings"]["model"],
			api_key=config.conf["GPTAssistant"]["settings"]["openai_key"],
			is_chat_completion=is_chat_completion,
		)
		proofreader = Proofreader(corrector)

		obj = api.getFocusObject()
		text = obj.makeTextInfo(textInfos.POSITION_SELECTION).text
		max_word_count = config.conf["GPTAssistant"]["settings"]["max_word_count"]

		if len(text) > max_word_count:
			ui.message(f"原文長度: {len(text)}, 超過上限: {max_word_count}")
			log.warning(f"原文長度: {len(text)}, 超過上限: {max_word_count}")
			return
		elif len(text) == 0:
			ui.message(f"未選取任何文字，無法分析")
			log.warning(f"未選取任何文字，無法分析")
			return
		elif not has_chinese(text):
			ui.message(f"選取範圍不含漢字，無法分析")
			log.warning(f"選取範圍不含漢字，無法分析")
			return

		try:
			text_corrected, diff = proofreader.typo_analyzer(text)
		except Exception as e:
			ui.message(f"抱歉，程式運行中遇到了一些問題，錯誤詳情是:{e}")
			log.warning(f"抱歉，程式運行中遇到了一些問題，錯誤詳情是:{e}")
			return

		ui.message(f"原文是: {text}")
		ui.message(f"diff是: {diff}")
		print(f"原文是: {text}")
		print(f"修正後是: {text_corrected}")
		print(f"diff是: {diff}")

		template_folder = os.path.join(PATH, "web", "templates")
		raw_folder = os.path.join(PATH, "web", "workspace", "default")
		review_folder = os.path.join(PATH, "web", "workspace", "review")

		try:
			shutil.rmtree(raw_folder)
		except BaseException:
			pass
		if not os.path.exists(raw_folder):
			os.makedirs(raw_folder)

		data = diff

		raw = os.path.join(raw_folder, "result.txt")
		with open(raw, "w", encoding="utf8") as f:
			f.write(json.dumps(data))

		try:
			shutil.rmtree(review_folder)
		except BaseException:
			pass
		if not os.path.exists(review_folder):
			os.makedirs(review_folder)

		shutil.copytree(
			os.path.join(template_folder, "modules"),
			os.path.join(review_folder, "modules")
		)

		src = os.path.join(review_folder, os.path.basename(raw))
		shutil.copyfile(
			raw,
			src,
		)

		dst = os.path.join(review_folder, "result.html")
		text2template(src, dst)

		self.OnPreview(dst)

	def action(self):
		correct_typo_thread = threading.Thread(target=self.correct_typo)
		correct_typo_thread.start()

		while correct_typo_thread.is_alive():
			beep(261.6, 300)
			time.sleep(0.5)

	@script(
		gesture="kb:NVDA+alt+o",
		description=_("GPT"),
		category=ADDON_SUMMARY,
	)
	def script_action(self, gesture):
		action_thread = threading.Thread(target=self.action)
		action_thread.start()
