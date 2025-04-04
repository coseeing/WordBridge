import csv
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
from configobj.validate import VdtValueTooBigError, VdtValueTooSmallError
import textInfos
from tones import beep
import ui
import wx

import requests

from .dialogs import CORRECTOR_CONFIG_FILENAME_DEFAULT, CORRECTOR_CONFIG_FOLDER_PATH, LANGUAGE_DEFAULT, TYPO_CORRECTION_MODE_DEFAULT
from .dialogs import LLMSettingsPanel, FeedbackDialog
from .decimalUtils import decimal_to_str_0
from .dictionary.dialog import DictionaryEntryDialog
from .lib.coseeing import obtain_openai_key
from .lib.typo_corrector import ChineseTypoCorrector, ChineseTypoCorrectorLite
from .lib.utils import strings_diff
from .lib.viewHTML import text2template
from hanzidentifier import has_chinese


DEBUG_MODE = False
addonHandler.initTranslation()
ADDON_SUMMARY = "WordBridge"

config.conf.spec["WordBridge"] = {
	"settings": {
		"corrector_config_filename": f"string(default={CORRECTOR_CONFIG_FILENAME_DEFAULT})",
		"language": f"string(default={LANGUAGE_DEFAULT})",
		"typo_correction_mode": f"string(default={TYPO_CORRECTION_MODE_DEFAULT})",
		"api_key": {},
		"secret_key": {},
		"coseeing_username": "string(default=\0)",
		"coseeing_password": "string(default=\0)",
		"max_char_count": "integer(default=512,min=256,max=1024)",
		"auto_display_report": "boolean(default=False)",
		"customized_words_enable": "boolean(default=True)",
	}
}
COSEEING_BASE_URL = "https://wordbridge.coseeing.org"
# COSEEING_BASE_URL = "http://localhost:8000"


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
			gui.mainFrame.popupSettingsDialog,
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
		try:
			max_char_count = config.conf["WordBridge"]["settings"]["max_char_count"]
		except VdtValueTooBigError:
			max_char_count = int(config.conf.getConfigValidation(
				("WordBridge", "settings", "max_char_count")
			).kwargs["max"])
		except VdtValueTooSmallError:
			max_char_count = int(config.conf.getConfigValidation(
				("WordBridge", "settings", "max_char_count")
			).kwargs["min"])
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

	def readDictionary(self):
		dictionary_path = os.path.join(PATH, "dictionary", "data.csv")
		if not os.path.exists(dictionary_path):
			open(dictionary_path, 'w', encoding='utf-8').close()
		with open(dictionary_path, encoding='utf8', newline='') as csvfile:
			reader = csv.DictReader(csvfile)
			word_list = list(reader)
		return word_list

	def isNVDASettingsDialogCreate(self):
		create_state = gui.settingsDialogs.NVDASettingsDialog.DialogState.CREATED
		for dlg, state in gui.settingsDialogs.NVDASettingsDialog._instances.items():
			if isinstance(dlg, gui.settingsDialogs.NVDASettingsDialog) and state == create_state:
				return True
		return False

	def correctTypo(self, request):
		corrector_config_filename = config.conf["WordBridge"]["settings"]["corrector_config_filename"]
		corrector_config_file_path = os.path.join(
			CORRECTOR_CONFIG_FOLDER_PATH,
			corrector_config_filename
		)
		if not os.path.exists(corrector_config_file_path):
			corrector_config_file_path = os.path.join(
				CORRECTOR_CONFIG_FOLDER_PATH,
				CORRECTOR_CONFIG_FILENAME_DEFAULT
			)

		language = config.conf["WordBridge"]["settings"]["language"]
		corrector_mode = config.conf["WordBridge"]["settings"]["typo_correction_mode"]
		with open(corrector_config_file_path, "r", encoding="utf8") as f:
			corrector_config = json.loads(f.read())
		provider = corrector_config["model"]["provider"]
		model_name = corrector_config["model"]["model_name"]
		template_name = corrector_config["model"]["template_name"][corrector_mode]
		optional_guidance_enable = corrector_config["model"]["optional_guidance_enable"]

		if config.conf["WordBridge"]["settings"]["customized_words_enable"]:
			customized_words = [row["text"] for row in self.readDictionary()]
		else:
			customized_words = []
		if corrector_config['model']['llm_access_method'] != "coseeing_relay":
			if provider not in config.conf["WordBridge"]["settings"]["api_key"]:
				config.conf["WordBridge"]["settings"]["api_key"][provider] = ""
			if provider not in config.conf["WordBridge"]["settings"]["secret_key"]:
				config.conf["WordBridge"]["settings"]["secret_key"][provider] = ""
			credential = {
				"api_key": config.conf["WordBridge"]["settings"]["api_key"][provider],
				"secret_key": config.conf["WordBridge"]["settings"]["secret_key"][provider],
			}
			corrector_class = ChineseTypoCorrectorLite if corrector_mode == "lite" else ChineseTypoCorrector
			corrector = corrector_class(
				model=model_name,
				provider=provider,
				credential=credential,
				language=language,
				template_name=template_name,
				optional_guidance_enable=optional_guidance_enable,
				customized_words=customized_words,
			)

			try:
				batch_mode = not DEBUG_MODE
				response, _diff_ = corrector.correct_text(request, batch_mode=batch_mode)
			except Exception as e:
				ui.message(_("Sorry, an error occurred during the program execution, the details are: {e}").format(e=e))
				log.warning(_("Sorry, an error occurred during the program execution, the details are: {e}").format(e=e))
				raise e
				return
			interaction_id = None
			cost = corrector.get_total_cost()
		else:
			try:
				access_token = obtain_openai_key(
					COSEEING_BASE_URL,
					config.conf["WordBridge"]["settings"]["coseeing_username"],
					config.conf["WordBridge"]["settings"]["coseeing_password"],
				)
			except Exception as e:
				access_token = ""
				# ui.message(_("Sorry, an error occurred while logging into Coseeing, the details are: {e}").format(e=e))
				# log.warning(_("Sorry, an error occurred while logging into Coseeing, the details are: {e}").format(e=e))
				# return

			data = {
				"request": request,
				"corrector_config_filename": corrector_config_filename,
				"language": language,
				"typo_correction_mode": corrector_mode,
				"customized_words": customized_words,
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
			cost = result["cost"]

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

		try:
			cost = decimal_to_str_0(cost)
		except:
			pass
		ui.message(_("This task costs {cost} USD.").format(cost=cost))
		log.warning(_("This task costs {cost} USD.").format(cost=cost))

		if config.conf["WordBridge"]["settings"]["auto_display_report"]:
			self.showReport(self.latest_action["diff"])

	def correctionAction(self, text):
		correct_typo_thread = threading.Thread(target=self.correctTypo, args=(text,))
		correct_typo_thread.start()

		while correct_typo_thread.is_alive():
			beep(261.6, 300)
			time.sleep(0.5)

	@script(
		gesture="kb:NVDA+alt+d",
		description=_("Open custom dictionary"),
		category=ADDON_SUMMARY,
	)
	def script_openCustomDictionary(self, gesture):
		gui.mainFrame.popupSettingsDialog(DictionaryEntryDialog)

	@script(
		gesture="kb:NVDA+alt+o",
		description=_("Execute typo correction"),
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
		gesture="kb:NVDA+alt+w",
		description=_("Open settings dialog of WordBridge"),
		category=ADDON_SUMMARY,
	)
	def script_openWordBridgeSettings(self, gesture):
		wx.CallAfter(
			gui.mainFrame.popupSettingsDialog,
			gui.settingsDialogs.NVDASettingsDialog,
			LLMSettingsPanel
		)

	@script(
		gesture="kb:NVDA+alt+r",
		description=_("Show report of correction"),
		category=ADDON_SUMMARY,
	)
	def script_showCorrectionReport(self, gesture):
		if self.latest_action["diff"] is None:
			ui.message(_("No report has been generated yet."))
			log.warning(_("No report has been generated yet."))
			return

		self.showReport(self.latest_action["diff"])

	@script(
		gesture="kb:NVDA+alt+f",
		description=_("Feedback of correction"),
		category=ADDON_SUMMARY,
	)
	def script_correctionFeedback(self, gesture):
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
