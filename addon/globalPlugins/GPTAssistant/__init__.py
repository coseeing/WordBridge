from .python.http import client as httpclient
from .python.http import cookies as httpcookies
from .python import importlib

import json
import os
import shutil
import sys

sys.modules['http.cookies'] = httpcookies
sys.modules['http.client'] = httpclient
sys.modules['importlib'] = importlib

PATH = os.path.dirname(__file__)

PYTHON_PATH = os.path.join(PATH, 'python')
sys.path.insert(0, PYTHON_PATH)

PACKAGE_PATH = os.path.join(PATH, 'package')
sys.path.insert(0, PACKAGE_PATH)

from .dialogs import GPTAssistantSettingsDialog

from logHandler import log
from scriptHandler import script
from speech.speech import getCharDescListFromText

import addonHandler
import api
import config
import globalPluginHandler
import gui
import textInfos
import ui
import wx

from .lib.proofreader import Proofreader
from .lib.typo_corrector import TypoCorrector
from .lib.viewHTML import text2template


addonHandler.initTranslation()
ADDON_SUMMARY = "GPTAssistant"

config.conf.spec["GPTAssistant"] = {
	"settings": {
		"model": "string(default=text-davinci-003)",
		"openai_key": "string(default=Please Enter Your Key)",
		"max_word_count": "integer(default=100,min=2,max=200)",
	}
}


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.create_menu()

	def terminate(self, *args, **kwargs):
		super().terminate(*args, **kwargs)
		self.remove_menu()

	def create_menu(self):
		self.toolsMenu = gui.mainFrame.sysTrayIcon.toolsMenu
		self.menu = wx.Menu()
		self.settings = self.menu.Append(
			wx.ID_ANY,
			_("&Settings...")
		)
		gui.mainFrame.sysTrayIcon.Bind(wx.EVT_MENU, self.onSettings, self.settings)
		self.gpt_assistant_item = self.toolsMenu.AppendSubMenu(self.menu, _("GPTAssistant"), _("GPTAssistant"))

	def remove_menu(self):
		self.toolsMenu.Remove(self.gpt_assistant_item)

	def onSettings(self, evt):
		wx.CallAfter(gui.mainFrame._popupSettingsDialog, GPTAssistantSettingsDialog)

	@script(
		gesture="kb:NVDA+alt+o",
		description=_("GPT"),
		category=ADDON_SUMMARY,
	)
	def script_action(self, gesture):
		corrector = TypoCorrector(
			model=config.conf["GPTAssistant"]["settings"]["model"],
			api_key=config.conf["GPTAssistant"]["settings"]["openai_key"]
		)
		proofreader = Proofreader(corrector)

		obj = api.getFocusObject()
		text = obj.makeTextInfo(textInfos.POSITION_SELECTION).text
		max_word_count = config.conf["GPTAssistant"]["settings"]["max_word_count"]

		if len(text) > max_word_count:
			ui.message(f"原文長度: {len(text)}, 超過上限: {max_word_count}")
			log.warning(f"原文長度: {len(text)}, 超過上限: {max_word_count}")
			return

		text_corrected, diff = proofreader.typo_analyzer(text)

		ui.message(f"原文是: {text}")
		ui.message(f"diff是: {diff}")
		print(f"原文是: {text}")
		print(f"修正後是: {text_corrected}")
		print(f"diff是: {diff}")

		template_folder = os.path.join(PATH, 'web', 'templates')
		raw_folder = os.path.join(PATH, 'web', 'workspace', 'default')
		review_folder = os.path.join(PATH, 'web', 'workspace', 'review')

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
			os.path.join(template_folder, 'modules'),
			os.path.join(review_folder, 'modules')
		)

		src = os.path.join(review_folder, os.path.basename(raw))
		shutil.copyfile(
			raw,
			src,
		)

		dst = os.path.join(review_folder, "result.html")
		text2template(src, dst)

		self.OnPreview(dst)

	def OnPreview(self, file):
		def openfile():
			os.startfile(file)
		wx.CallAfter(openfile)

