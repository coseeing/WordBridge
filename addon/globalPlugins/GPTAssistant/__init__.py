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

from .lib.coseeing import obtain_openai_key
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
		"openai_key": "string(default=\0)",
		"coseeing_username": "string(default=\0)",
		"coseeing_password": "string(default=\0)",
		"max_word_count": "integer(default=50,min=2,max=64)",
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

	def showReport(self, diff_data):
		template_folder = os.path.join(PATH, "web", "templates")
		raw_folder = os.path.join(PATH, "web", "workspace", "default")
		review_folder = os.path.join(PATH, "web", "workspace", "review")

		try:
			shutil.rmtree(raw_folder)
		except BaseException:
			pass
		if not os.path.exists(raw_folder):
			os.makedirs(raw_folder)

		raw = os.path.join(raw_folder, "result.txt")
		with open(raw, "w", encoding="utf8") as f:
			f.write(json.dumps(diff_data))

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

	def getSelectedText(self):
		obj = api.getFocusObject()
		text = obj.makeTextInfo(textInfos.POSITION_SELECTION).text
		return text

	def isTextValid(self, text):
		max_word_count = config.conf["GPTAssistant"]["settings"]["max_word_count"]
		if len(text) > max_word_count:
			ui.message(f"原文字符數為{len(text)}, 超過上限{max_word_count}")
			log.warning(f"原文字符數: {len(text)}, 超過上限: {max_word_count}")
			return False
		elif len(text) == 0:
			ui.message(f"未選取任何文字，無法分析")
			log.warning(f"未選取任何文字，無法分析")
			return False
		elif not has_chinese(text):
			ui.message(f"選取範圍不含漢字，無法分析")
			log.warning(f"選取範圍不含漢字，無法分析")
			return False

		return True

	def correctTypo(self, text):
		# text-davinci-003 may be deprecated inthe future version of GPTAssistant
		is_chat_completion = True

		if config.conf["GPTAssistant"]["settings"]["gpt_access_method"] == "OpenAI API Key":
			openai_api_key = config.conf["GPTAssistant"]["settings"]["openai_key"]
		else:
			openai_api_key = obtain_openai_key(
				config.conf["GPTAssistant"]["settings"]["coseeing_username"],
				config.conf["GPTAssistant"]["settings"]["coseeing_password"],
			)

		if openai_api_key is None:
			if config.conf["GPTAssistant"]["settings"]["gpt_access_method"] == "OpenAI API Key":
				ui.message(f"OpenAI API Key不存在")
				log.warning(f"OpenAI API Key不存在")
			else:
				ui.message(f"Coseeing 帳號的使用者名稱或密碼有誤")
				log.warning(f"Coseeing 帳號的使用者名稱或密碼有誤")
			return

		corrector = TypoCorrectorWithPhone(
			model=config.conf["GPTAssistant"]["settings"]["model"],
			api_key=config.conf["GPTAssistant"]["settings"]["openai_key"],
			is_chat_completion=is_chat_completion,
		)
		proofreader = Proofreader(corrector)

		try:
			text_corrected, diff_data = proofreader.typo_analyzer(text)
		except Exception as e:
			ui.message(f"抱歉，程式運行中遇到了一些問題，錯誤詳情是:{e}")
			log.warning(f"抱歉，程式運行中遇到了一些問題，錯誤詳情是:{e}")
			return

		if text == text_corrected:
			ui.message(f"選取範圍未檢測出錯誤")
			log.warning(f"選取範圍未檢測出錯誤")
			return

		api.copyToClip(text_corrected)
		ui.message(f"結果已複製到剪貼簿")
		log.warning(f"結果已複製到剪貼簿")

		print(f"原文是: {text}")
		print(f"修正後是: {text_corrected}")
		print(f"diff是: {diff_data}")

		self.showReport(diff_data)

	def action(self, text):
		correct_typo_thread = threading.Thread(target=self.correctTypo, args=(text,))
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
		text = self.getSelectedText()
		if not self.isTextValid(text):
			return
		action_thread = threading.Thread(target=self.action, args=(text,))
		action_thread.start()
