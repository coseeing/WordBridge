from concurrent.futures import Future
from configobj.validate import VdtValueTooBigError, VdtValueTooSmallError

import config
import ctypes
import glob
import json
import locale
import os
import wx

import addonHandler

import gui
from gui import guiHelper, nvdaControls
from gui.contextHelp import ContextHelpMixin
from gui.settingsDialogs import SettingsPanel

from . configManager import ConfigManager
from .dictionary.dialog import DictionaryEntryDialog

from .lib.auth.registry import (
	get as get_oidc,
	shutdown as shutdown_oidc,
)

addonHandler.initTranslation()

LABEL_DICT = {
	"zh_traditional": _("Traditional Chinese"),
	"zh_simplified": _("Simplified Chinese"),
	"standard": _("Standard"),
	"lite": _("Lite"),
	"personal_api_key": _("Personal API Key"),
	"coseeing_account": _("Coseeing Account"),
}

os_language_code = locale.windows_locale[ctypes.windll.kernel32.GetUserDefaultUILanguage()]
if os_language_code in ["zh_TW", "zh_MO", "zh_HK"]:
	LANGUAGE_DEFAULT = "zh_traditional"
else:
	LANGUAGE_DEFAULT = "zh_simplified"
CORRECTOR_CONFIG_FILENAME_DEFAULT = "Coseeing-1-deepseek-chat-v3-0324.json"
CORRECTOR_CONFIG_FOLDER_PATH = os.path.join(os.path.dirname(__file__), "corrector_config")
TYPO_CORRECTION_MODE_DEFAULT = "standard"

LANGUAGE_VALUES = ["zh_traditional", "zh_simplified"]
LANGUAGE_LABELS = [LABEL_DICT[val] for val in LANGUAGE_VALUES]

TYPO_CORRECTION_MODE_VALUES = ["standard", "lite"]
TYPO_CORRECTION_MODE_LABELS = [LABEL_DICT[val] for val in TYPO_CORRECTION_MODE_VALUES]

SOUND_EFFECTS_URL = "https://www.zapsplat.com/music/medium-underwater-movement-whoosh-pass-by-1/"

configManager = ConfigManager(CORRECTOR_CONFIG_FOLDER_PATH)


class LLMSettingsPanel(SettingsPanel):
	title = _("WordBridge")
	helpId = "WordBridge Settings"

	def makeSettings(self, settingsSizer):
		settingsSizerHelper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)

		config_filename = config.conf["WordBridge"]["settings"]["corrector_config_filename"]
		(provider_index, model_index) = configManager.find_index_by_filename(config_filename)
		if (provider_index, model_index) == (-1, -1):
			(provider_index, model_index) = configManager.find_index_by_filename(CORRECTOR_CONFIG_FILENAME_DEFAULT)

		# For selecting provider
		providerLabelText = _("Service Provider:")
		self.providerList = settingsSizerHelper.addLabeledControl(
			providerLabelText,
			wx.Choice,
			choices=list(configManager.endpoint_labels)
		)
		self.providerList.SetToolTip(wx.ToolTip(_("Choose the service provider for the WordBridge")))

		self.providerList.Bind(wx.EVT_CHOICE, self.onChangeProviderChoice)
		self.providerList.SetSelection(provider_index)

		provider_index = self.providerList.GetSelection()
		configManager.provider = list(configManager.endpoints)[provider_index]

		# For selecting LLM
		modelLabelText = _("Large Language Model:")
		self.modelList = settingsSizerHelper.addLabeledControl(
			modelLabelText,
			wx.Choice,
			choices=configManager.model_labels
		)
		self.modelList.SetToolTip(wx.ToolTip(_("Choose the large language model for the Word Bridge")))

		self.modelList.SetSelection(model_index)

		# For setting account information
		self.accountGroupSizerMap = {}
		self.accountTextCtrlMap1 = {}
		self.accountTextCtrlMap2 = {}
		for endpoint, label in zip(configManager.endpoints.keys(), configManager.endpoint_labels):
			if endpoint not in config.conf["WordBridge"]["settings"]["api_key"]:
				config.conf["WordBridge"]["settings"]["api_key"][endpoint] = ""
			if endpoint not in config.conf["WordBridge"]["settings"]["secret_key"]:
				config.conf["WordBridge"]["settings"]["secret_key"][endpoint] = ""

			accountBoxSizer = wx.StaticBoxSizer(
				wx.VERTICAL,
				self,
				label=label+" "+_("Authentication")
			)
			self.accountGroupSizerMap[endpoint] = accountBoxSizer
			self.accountGroupSizerHelper = guiHelper.BoxSizerHelper(self, sizer=accountBoxSizer)
			settingsSizerHelper.addItem(self.accountGroupSizerHelper)

			firstInfoText = _("API Key:")
			firstInfo = config.conf["WordBridge"]["settings"]["api_key"][endpoint]

			self.accountTextCtrlMap1[endpoint] = self.accountGroupSizerHelper.addLabeledControl(
				firstInfoText,
				wx.TextCtrl,
				size=(self.scaleSize(375), -1),
				value=firstInfo,
				style=wx.TE_MULTILINE,
			)
			if endpoint == "Coseeing":
				self.accountTextCtrlMap1[endpoint].SetEditable(False)

			secondInfoText = _("Secret Key:")
			secondInfo =config.conf["WordBridge"]["settings"]["secret_key"][endpoint]
			if endpoint == "Coseeing" and False:
				self.accountTextCtrlMap2[endpoint] = self.accountGroupSizerHelper.addLabeledControl(
					secondInfoText,
					wx.TextCtrl,
					size=(self.scaleSize(375), -1),
					value=secondInfo,
					# style=wx.TE_PASSWORD if endpoint == "Coseeing" else wx.TE_PROCESS_ENTER,
				)

		self._refreshAccountInfo()

		# For selecting language
		languageLabelText = _("Language:")
		self.languageList = settingsSizerHelper.addLabeledControl(
			languageLabelText,
			wx.Choice,
			choices=LANGUAGE_LABELS
		)
		self.languageList.SetToolTip(wx.ToolTip(_("Choose the language for the Word Bridge")))
		if config.conf["WordBridge"]["settings"]["language"] in LANGUAGE_VALUES:
			self.languageList.SetSelection(LANGUAGE_VALUES.index(config.conf["WordBridge"]["settings"]["language"]))
		else:
			config.conf["WordBridge"]["settings"]["language"] = LANGUAGE_DEFAULT
			self.languageList.SetSelection(LANGUAGE_VALUES.index(config.conf["WordBridge"]["settings"]["language"]))

		# For selecting typo correction mode

		typoCorrectionModeLabelText = _("Correction Mode:")
		self.typoCorrectionModeList = settingsSizerHelper.addLabeledControl(
			typoCorrectionModeLabelText,
			wx.Choice,
			choices=TYPO_CORRECTION_MODE_LABELS
		)
		self.typoCorrectionModeList.SetToolTip(wx.ToolTip(_("Choose the typo correction mode for the Word Bridge")))
		if config.conf["WordBridge"]["settings"]["typo_correction_mode"] in TYPO_CORRECTION_MODE_VALUES:
			self.typoCorrectionModeList.SetSelection(TYPO_CORRECTION_MODE_VALUES.index(config.conf["WordBridge"]["settings"]["typo_correction_mode"]))
		else:
			config.conf["WordBridge"]["settings"]["typo_correction_mode"] = TYPO_CORRECTION_MODE_DEFAULT
			self.typoCorrectionModeList.SetSelection(TYPO_CORRECTION_MODE_VALUES.index(config.conf["WordBridge"]["settings"]["typo_correction_mode"]))

		# For setting upper bound of correction character count
		maxTokensLabelText = _("Max character count")
		try:
			maxCharCount = config.conf["WordBridge"]["settings"]["max_char_count"]
		except VdtValueTooBigError:
			maxCharCount = int(config.conf.getConfigValidation(
				("WordBridge", "settings", "max_char_count")
			).kwargs["max"])
		except VdtValueTooSmallError:
			maxCharCount = int(config.conf.getConfigValidation(
				("WordBridge", "settings", "max_char_count")
			).kwargs["min"])

		maxCharCountlowerBound = int(config.conf.getConfigValidation(
			("WordBridge", "settings", "max_char_count")
		).kwargs["min"])
		maxCharCountUpperBound = int(config.conf.getConfigValidation(
			("WordBridge", "settings", "max_char_count")
		).kwargs["max"])
		self.maxCharCountSpinCtrl = settingsSizerHelper.addLabeledControl(
			maxTokensLabelText,
			nvdaControls.SelectOnFocusSpinCtrl,
			min=maxCharCountlowerBound,
			max=maxCharCountUpperBound,
			initial=maxCharCount
		)

		# For setting auto display typo report
		self.autoDisplayReportEnable = settingsSizerHelper.addItem(
			wx.CheckBox(self, label=_("Auto display typo report"))
		)
		self.autoDisplayReportEnable.SetValue(config.conf["WordBridge"]["settings"]["auto_display_report"])

		# For setting custom dictionary
		self.customizedWordEnable = settingsSizerHelper.addItem(
			wx.CheckBox(self, label=_("Apply personal dictionary"))
		)
		self.customizedWordEnable.SetValue(config.conf["WordBridge"]["settings"]["customized_words_enable"])

		self.wordDictionaryCtrl = settingsSizerHelper.addItem(
			wx.Button(
				self,
				label=_("Edit dictionary"),
			)
		)
		self.wordDictionaryCtrl.Bind(wx.EVT_BUTTON, self.onEditDictionary)

		# For setting sound effects
		self.soundEffectsEnable = settingsSizerHelper.addItem(
			wx.CheckBox(self, label=_("Enable sound effect cues"))
		)
		self.soundEffectsEnable.SetValue(config.conf["WordBridge"]["settings"]["sound_effects_enable"])

		self.soundEffectsCtrl = settingsSizerHelper.addItem(
			wx.Button(
				self,
				label=_("Sound effect credits"),
			)
		)
		self.soundEffectsCtrl.Bind(wx.EVT_BUTTON, self.onSoundEffects)

		self.settingsSizer = settingsSizer

	def _refreshModelChoice(self):
		self.modelList.SetItems(configManager.model_labels)
		self.modelList.SetSelection(0)

	def _refreshAccountInfo(self):
		for ep in configManager.endpoints.keys():
			if ep == configManager.provider:
				self.settingsSizer.Show(self.accountGroupSizerMap[ep], recursive=True)
			else:
				self.settingsSizer.Hide(self.accountGroupSizerMap[ep], recursive=True)

	def onEditDictionary(self, event):
		gui.mainFrame.popupSettingsDialog(DictionaryEntryDialog)

	def onSoundEffects(self, event):
		def openfile():
			os.startfile(SOUND_EFFECTS_URL)
		wx.CallAfter(openfile)

	def onSave(self):
		provider_index = self.providerList.GetSelection()
		model_index = self.modelList.GetSelection()
		config.conf["WordBridge"]["settings"]["corrector_config_filename"] = configManager.get_config_by_index(provider_index, model_index).filename
		config.conf["WordBridge"]["settings"]["language"] = LANGUAGE_VALUES[self.languageList.GetSelection()]
		config.conf["WordBridge"]["settings"]["typo_correction_mode"] = TYPO_CORRECTION_MODE_VALUES[self.typoCorrectionModeList.GetSelection()]
		config.conf["WordBridge"]["settings"]["max_char_count"] = self.maxCharCountSpinCtrl.GetValue()
		config.conf["WordBridge"]["settings"]["auto_display_report"] = self.autoDisplayReportEnable.GetValue()
		config.conf["WordBridge"]["settings"]["customized_words_enable"] = self.customizedWordEnable.GetValue()
		config.conf["WordBridge"]["settings"]["sound_effects_enable"] = self.soundEffectsEnable.GetValue()

		# config.conf["WordBridge"]["settings"]["coseeing_username"] = self.accountTextCtrlMap1["Coseeing"].GetValue()
		# config.conf["WordBridge"]["settings"]["coseeing_password"] = self.accountTextCtrlMap2["Coseeing"].GetValue()
		for ep in configManager.endpoints.keys():
			if ep == "Coseeing":
				continue
			provider_tmp = ep
			if provider_tmp in self.accountTextCtrlMap1:
				api_key_tmp = self.accountTextCtrlMap1[provider_tmp].GetValue()
				config.conf["WordBridge"]["settings"]["api_key"][provider_tmp] = api_key_tmp
			if provider_tmp in self.accountTextCtrlMap2:
				secret_key_tmp = self.accountTextCtrlMap2[provider_tmp].GetValue()
				config.conf["WordBridge"]["settings"]["secret_key"][provider_tmp] = secret_key_tmp

		oidc = get_oidc()
		fut = oidc.get_valid_access_token_async(auto_login=False)

		def _promptLoginChoice():
			reply = gui.message.MessageDialog(
				parent=gui.mainFrame,
				message=_("No token was found. Would you like to log in now, or continue as a guest?"),
				title=_("Login Option"),
				buttons=gui.message.DefaultButtonSet.YES_NO,
			).setYesNoLabels(_("login now"), _("continue guest")).ShowModal()
			if reply == gui.message.ReturnCode.YES:
				try:
					oidc = get_oidc()
					oidc.abort_pending_flow()
					oidc.login_async()
				except Exception as e:
					print(e)

		def _get_valid_access_token_done(f: Future):
			try:
				at = f.result()
			except Exception:
				at = None
			if not at:
				wx.CallAfter(_promptLoginChoice)

		fut.add_done_callback(_get_valid_access_token_done)

	def bck(self):
		try:
			at = fut.result()
		except Exception:
			at = None

		if not at:
			reply = gui.message.MessageDialog(
				parent=gui.mainFrame,
				message=_("No token was found. Would you like to log in now, or continue as a guest?"),
				title=_("Login Option"),
				buttons=gui.message.DefaultButtonSet.YES_NO,
			).setYesNoLabels(_("login now"), _("continue guest")).ShowModal()
			if reply == gui.message.ReturnCode.YES:
				try:
					oidc = get_oidc()
					oidc.abort_pending_flow()
					oidc.login_async()
				except Exception:
					pass

	def onChangeProviderChoice(self, evt):
		provider_index = self.providerList.GetSelection()
		configManager.provider = list(configManager.endpoints)[provider_index]

		self.Freeze()
		# trigger a refresh of the settings
		self._refreshAccountInfo()
		self._refreshModelChoice()
		self.onPanelActivated()
		self._sendLayoutUpdatedEvent()
		self.Thaw()

	def updateCurrentKey(self, key):
		self.apikeyTextCtrl.SetValue(key)

	def updateAccountInformation(self, username, password):
		self.usernameTextCtrl.SetValue(username)
		self.passwordTextCtrl.SetValue(password)


class FeedbackDialog(
	ContextHelpMixin,
	wx.Dialog  # wxPython does not seem to call base class initializer, put last in MRO
):
	helpId = "FeedbackCoseeing"

	def __init__(self, parent, request, response):
		# This is the label for the feedback dialog for Coseeing.
		super().__init__(parent, title=_("Feedback Coseeing"))
		mainSizer = wx.BoxSizer(wx.VERTICAL)
		sHelper = guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)

		# Here are text Controls for request, response and feedback. Only feedback can be editable.
		self.requestTextCtrl = sHelper.addLabeledControl(
			_("Request:"),
			wx.TextCtrl,
			style=wx.TE_READONLY | wx.TE_MULTILINE,
			size=wx.Size(800, 70)
		)
		self.requestTextCtrl.SetValue(request)
		self.responseTextCtrl = sHelper.addLabeledControl(
			_("Response:"),
			wx.TextCtrl,
			style=wx.TE_READONLY | wx.TE_MULTILINE,
			size=wx.Size(800, 70)
		)
		self.responseTextCtrl.SetValue(response)
		self.feedbackTextCtrl = sHelper.addLabeledControl(
			_("Feedback:"),
			wx.TextCtrl,
			style=wx.TE_MULTILINE,
			size=wx.Size(800, 130)
		)

		sHelper.addDialogDismissButtons(self.CreateButtonSizer(wx.OK | wx.CANCEL))

		mainSizer.Add(sHelper.sizer, border=guiHelper.BORDER_FOR_DIALOGS, flag=wx.ALL)
		mainSizer.Fit(self)
		self.SetSize(1000, 450)
		self.SetSizer(mainSizer)

		self.feedbackTextCtrl.SetFocus()
		self.CentreOnScreen()
