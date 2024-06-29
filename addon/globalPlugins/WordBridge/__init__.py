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

from .dialogs import LLMSettingsPanel, FeedbackDialog
from .lib.coseeing import obtain_openai_key
from .lib.proofreader import Proofreader
from .lib.typo_corrector import ChineseTypoCorrector, ChineseTypoCorrectorLite
from .lib.utils import strings_diff
from .lib.viewHTML import text2template
from hanzidentifier import has_chinese


DEBUG_MODE = False
addonHandler.initTranslation()
ADDON_SUMMARY = "WordBridge"

config.conf.spec["WordBridge"] = {
	"settings": {
		"corrector_config": {},
		"language": "string(default=zh_traditional_tw)",
		"llm_access_method": "string(default=coseeing_account)",
		"api_key": {},
		"secret_key": {},
		"coseeing_username": "string(default=\0)",
		"coseeing_password": "string(default=\0)",
		"max_char_count": "integer(default=50,min=2,max=64)",
		"auto_display_report": "boolean(default=False)",
	}
}
COSEEING_BASE_URL = "https://wordbridge.coseeing.org"


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		gui.settingsDialogs.NVDASettingsDialog.categoryClasses.append(LLMSettingsPanel)
		self.latest_action = {
			"request": None,
			"response": None,
			"diff": None,
			"interaction_id": None,
		}

	def terminate(self, *args, **kwargs):
		super().terminate(*args, **kwargs)
		gui.settingsDialogs.NVDASettingsDialog.categoryClasses.remove(LLMSettingsPanel)

	def onSettings(self, evt):
		wx.CallAfter(
			gui.mainFrame._popupSettingsDialog,
			gui.settingsDialogs.NVDASettingsDialog,
			LLMSettingsPanel
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
		corrector_config = config.conf["WordBridge"]["settings"]["corrector_config"]
		provider = corrector_config["model"]["provider"]
		model_name = corrector_config["model"]["model_name"]
		language = config.conf["WordBridge"]["settings"]["language"]
		if config.conf["WordBridge"]["settings"]["llm_access_method"] == "personal_api_key":
			corrector_mode = corrector_config["typo_corrector"]["typo_correction_mode"]
			if provider not in config.conf["WordBridge"]["settings"]["api_key"]:
				config.conf["WordBridge"]["settings"]["api_key"][provider] = ""
			if provider not in config.conf["WordBridge"]["settings"]["secret_key"]:
				config.conf["WordBridge"]["settings"]["secret_key"][provider] = ""
			credential = {
				"api_key": config.conf["WordBridge"]["settings"]["api_key"][provider],
				"secret_key": config.conf["WordBridge"]["settings"]["secret_key"][provider],
			}
			corrector_class = ChineseTypoCorrectorLite if corrector_mode == "Lite Mode" else ChineseTypoCorrector
			corrector = corrector_class(
				model=model_name,
				provider=provider,
				credential=credential,
				language=language,
			)
			proofreader = Proofreader(corrector)

			try:
				batch_mode = not DEBUG_MODE
				response, _diff_ = proofreader.typo_analyzer(request, batch_mode=batch_mode)
			except Exception as e:
				ui.message(_("Sorry, an error occurred during the program execution, the details are: {e}").format(e=e))
				log.warning(_("Sorry, an error occurred during the program execution, the details are: {e}").format(e=e))
				return
			res = proofreader.get_total_usage()
			interaction_id = None
		else:
			try:
				access_token = obtain_openai_key(
					COSEEING_BASE_URL,
					config.conf["WordBridge"]["settings"]["coseeing_username"],
					config.conf["WordBridge"]["settings"]["coseeing_password"],
				)
			except Exception as e:
				ui.message(_("Sorry, an error occurred while logging into Coseeing, the details are: {e}").format(e=e))
				log.warning(_("Sorry, an error occurred while logging into Coseeing, the details are: {e}").format(e=e))
				return

			data = {
				"request": request,
				"model": model_name,
				"language": language,
			}
			headers = {
				"Authorization": f"Bearer {access_token}",
			}
			try:
				data = requests.post(f"{COSEEING_BASE_URL}/proofreader", headers=headers, json=data)
				result = data.json()
			except requests.exceptions.JSONDecodeError as e:
				ui.message(_("Sorry, an error occurred while decode Coseeing response, the details are: {e}").format(e=e))
				return
			if data.status_code == 403:
				ui.message(_("Sorry, http 403 forbidden, the details are: {e}").format(e=data.json()["detail"]))
				return
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
		description=_("Show settings dialog of WordBridge"),
		category=ADDON_SUMMARY,
	)
	def script_showGPTSettings(self, gesture):
		wx.CallAfter(
			gui.mainFrame._popupSettingsDialog,
			gui.settingsDialogs.NVDASettingsDialog,
			LLMSettingsPanel
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
		# 	"request": "考式以經通過",
		# 	"response": "考試已經通過",
		# 	"diff": None,
		# 	"interaction_id": 1,
		# }
		if self.latest_action["interaction_id"] is None:
			ui.message(_("No report has been generated yet."))
			log.warning(_("No report has been generated yet."))
			return

		def show():
			with FeedbackDialog(
				gui.mainFrame,
				self.latest_action["request"],
				self.latest_action["response"]
			) as feedbackDialog:
				if feedbackDialog.ShowModal() != wx.ID_OK:
					return
				feedback_value = feedbackDialog.feedbackTextCtrl.GetValue()
				if not feedback_value:
					return

			try:
				access_token = obtain_openai_key(
					COSEEING_BASE_URL,
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
