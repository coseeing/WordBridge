import json
import os
import shutil
import sys
import threading
import time

PATH = os.path.dirname(__file__)
PACKAGE_PATH = os.path.join(PATH, "package")
sys.path.insert(0, PACKAGE_PATH)

import addonHandler
import api
import config
import globalPluginHandler
import gui
from logHandler import log
from scriptHandler import script
import textInfos
from tones import beep
import ui
import wx

import requests

from .dialogs import OpenAIGeneralSettingsPanel, FeedbackDialog
from .lib.coseeing import obtain_openai_key
from .lib.proofreader import Proofreader
from .lib.typo_corrector import ChineseTypoCorrector
from .lib.utils import strings_diff
from .lib.viewHTML import text2template
from hanzidentifier import has_chinese


addonHandler.initTranslation()
ADDON_SUMMARY = "WordBridge"

config.conf.spec["WordBridge"] = {
	"settings": {
		"model": "string(default=gpt-3.5-turbo)",
		"gpt_access_method": "string(default=openai_api_key)",
		"openai_key": "string(default=\0)",
		"coseeing_username": "string(default=\0)",
		"coseeing_password": "string(default=\0)",
		"max_char_count": "integer(default=50,min=2,max=64)",
		"auto_display_report": "boolean(default=False)",
	}
}
OPENAI_BASE_URL = "https://api.openai.com"
COSEEING_BASE_URL = "http://openairelay.coseeing.org"
# COSEEING_BASE_URL = "http://localhost:8000"


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		gui.settingsDialogs.NVDASettingsDialog.categoryClasses.append(OpenAIGeneralSettingsPanel)
		self.latest_action = {
			"request": None,
			"response": None,
			"diff": None,
			"interaction_id": None,
		}

	def terminate(self, *args, **kwargs):
		super().terminate(*args, **kwargs)
		gui.settingsDialogs.NVDASettingsDialog.categoryClasses.remove(OpenAIGeneralSettingsPanel)

	def onSettings(self, evt):
		wx.CallAfter(
			gui.mainFrame._popupSettingsDialog,
			gui.settingsDialogs.NVDASettingsDialog,
			OpenAIGeneralSettingsPanel
		)

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
		max_char_count = config.conf["WordBridge"]["settings"]["max_char_count"]
		if len(text) > max_char_count:
			ui.message(
				_("The number of characters is {len_text}, which exceeds the maximum, {max_char_count}.").format(
					len_text=len(text),
					max_char_count=max_char_count
				)
			)
			log.warning(
				_("The number of characters is {len_text}, which exceeds the maximum, {max_char_count}.").format(
					len_text=len(text),
					max_char_count=max_char_count
				)
			)
			return False
		elif len(text) == 0:
			ui.message(_("No text is selected, unable to analyze."))
			log.warning(_("No text is selected, unable to analyze."))
			return False
		elif not has_chinese(text):
			ui.message(_("The selected text does not contain Chinese characters, unable to analyze."))
			log.warning(_("The selected text does not contain Chinese characters, unable to analyze."))
			return False

		return True

	def isNVDASettingsDialogCreate(self):
		create_state = gui.settingsDialogs.NVDASettingsDialog.DialogState.CREATED
		for dlg, state in gui.settingsDialogs.NVDASettingsDialog._instances.items():
			if isinstance(dlg, gui.settingsDialogs.NVDASettingsDialog) and state == create_state:
				return True
		return False

	def correctTypo(self, request):
		if config.conf["WordBridge"]["settings"]["gpt_access_method"] == "openai_api_key":
			access_token = config.conf["WordBridge"]["settings"]["openai_key"]
			api_base_url = OPENAI_BASE_URL
			corrector = ChineseTypoCorrector(
				model=config.conf["WordBridge"]["settings"]["model"],
				access_token=access_token,
				api_base_url=api_base_url,
			)
			proofreader = Proofreader(corrector)

			try:
				response, _diff_ = proofreader.typo_analyzer(request)
			except Exception as e:
				ui.message(_("Sorry, an error occurred during the program execution, the details are: {e}").format(e=e))
				log.warning(_("Sorry, an error occurred during the program execution, the details are: {e}").format(e=e))
				return
			interaction_id = None
		else:
			try:
				access_token = obtain_openai_key(
					config.conf["WordBridge"]["settings"]["coseeing_username"],
					config.conf["WordBridge"]["settings"]["coseeing_password"],
				)
			except Exception as e:
				ui.message(_("Sorry, an error occurred while logging into Coseeing, the details are: {e}").format(e=e))
				log.warning(_("Sorry, an error occurred while logging into Coseeing, the details are: {e}").format(e=e))
				return

			data = {
				"request": request,
			}
			headers = {
				"Authorization": f"Bearer {access_token}",
			}
			result = requests.post(f"{COSEEING_BASE_URL}/proofreader", headers=headers, json=data).json()
			response = result["response"]
			interaction_id = result["interaction_id"]

		diff = strings_diff(request, response)

		self.latest_action = {
			"request": request,
			"response": response,
			"diff": diff,
			"interaction_id": interaction_id,
		}

		if request == response:
			ui.message(_("No errors in the selected text."))
			log.warning(_("No errors in the selected text."))
			return

		api.copyToClip(response)
		ui.message(_("The corrected text has been copied to the clipboard."))
		log.warning(_("The corrected text has been copied to the clipboard."))

		# print(_(f"Original text: {request}"))
		# print(_(f"Corrected text: {response}"))
		# print(_(f"Difference: {diff}"))

		if config.conf["WordBridge"]["settings"]["auto_display_report"]:
			self.showReport(self.latest_action["diff"])

	def correctionAction(self, text):
		correct_typo_thread = threading.Thread(target=self.correctTypo, args=(text,))
		correct_typo_thread.start()

		while correct_typo_thread.is_alive():
			beep(261.6, 300)
			time.sleep(0.5)

	@script(
		gesture="kb:NVDA+alt+o",
		description=_("Execute GPT typo correction for Chinese character"),
		category=ADDON_SUMMARY,
	)
	def script_correction(self, gesture):
		if self.isNVDASettingsDialogCreate():
			ui.message(
				_("The function cannot be executed. Please finish the configuration and close the setting window.")
			)
			log.warning(
				_("The function cannot be executed. Please finish the configuration and close the setting window.")
			)
			return

		text = self.getSelectedText()
		if not self.isTextValid(text):
			return
		action_thread = threading.Thread(target=self.correctionAction, args=(text,))
		action_thread.start()

	@script(
		gesture="kb:NVDA+alt+i",
		description=_("Show settings of GPT Assistant"),
		category=ADDON_SUMMARY,
	)
	def script_showGPTSettings(self, gesture):
		wx.CallAfter(
			gui.mainFrame._popupSettingsDialog,
			gui.settingsDialogs.NVDASettingsDialog,
			OpenAIGeneralSettingsPanel
		)

	@script(
		gesture="kb:NVDA+alt+u",
		description=_("Show report of typos"),
		category=ADDON_SUMMARY,
	)
	def script_showTypoReport(self, gesture):
		if self.latest_action["diff"] is None:
			ui.message(_("No report has been generated yet."))
			log.warning(_("No report has been generated yet."))
			return

		self.showReport(self.latest_action["diff"])

	@script(
		gesture="kb:NVDA+alt+f",
		description=_("Feedback of typos"),
		category=ADDON_SUMMARY,
	)
	def script_feedbackTypo(self, gesture):
		# self.latest_action = {
			# "request": "考式以經通過",
			# "response": "考試已經通過",
			# "diff": None,
			# "interaction_id": 1,
		# }
		if self.latest_action["interaction_id"] is None:
			ui.message(_("No report has been generated yet."))
			log.warning(_("No report has been generated yet."))
			return

		def show():
			with FeedbackDialog(gui.mainFrame, self.latest_action["request"], self.latest_action["response"]) as feedbackDialog:
				if feedbackDialog.ShowModal() != wx.ID_OK:
					return
				feedback_value = feedbackDialog.feedbackTextCtrl.GetValue()
				if not feedback_value:
					return

			try:
				access_token = obtain_openai_key(
					config.conf["WordBridge"]["settings"]["coseeing_username"],
					config.conf["WordBridge"]["settings"]["coseeing_password"],
				)
			except Exception as e:
				ui.message(_("Sorry, an error occurred while logging into Coseeing, the details are: {e}").format(e=e))
				log.warning(_("Sorry, an error occurred while logging into Coseeing, the details are: {e}").format(e=e))
				return

			data = {
				"interaction_id": self.latest_action["interaction_id"],
				"review_content": feedback_value,
			}
			headers = {
				"Authorization": f"Bearer {access_token}",
			}
			try:
				result = requests.post(f"{COSEEING_BASE_URL}/feedback", headers=headers, json=data).json()
			except Exception as e:
				ui.message(_("Sorry, an error occurred during the feedback request, the details are: {e}").format(e=e))
				log.warning(_("Sorry, an error occurred during the program execution, the details are: {e}").format(e=e))
				return

		wx.CallAfter(show)
