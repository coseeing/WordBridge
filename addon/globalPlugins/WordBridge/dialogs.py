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

from .dictionary.dialog import DictionaryEntryDialog

addonHandler.initTranslation()

LABEL_DICT = {
	"OpenAI": _("OpenAI"),
	"Baidu": _("Baidu"),
	"Coseeing": _("Coseeing"),
	"gpt-3.5-turbo": _("gpt-3.5-turbo"),
	"gpt-4-turbo": _("gpt-4-turbo"),
	"gpt-4o": _("gpt-4o"),
	"gpt-4o-mini": _("gpt-4o-mini"),
	"ernie-4.0-turbo-8k": _("ernie-4.0-turbo-8k"),
	"Standard Mode": _("Standard Mode"),
	"Lite Mode": _("Lite Mode"),
	"zh_traditional": _("Traditional Chinese"),
	"zh_simplified": _("Simplified Chinese"),

	# legacy
	"ernie-4.0-8k-preview": _("ernie-4.0-8k-preview"),
	"personal_api_key": _("Personal API Key"),
	"coseeing_account": _("Coseeing Account"),
}

os_language_code = locale.windows_locale[ctypes.windll.kernel32.GetUserDefaultUILanguage()]
if os_language_code in ["zh_TW", "zh_MO", "zh_HK"]:
	LANGUAGE_DEFAULT = "zh_traditional"
else:
	LANGUAGE_DEFAULT = "zh_simplified"
CORRECTOR_CONFIG_FILENAME_DEFAULT = "coseeing-gpt-4o-mini (standard mode)"
CORRECTOR_CONFIG_FOLDER_PATH = os.path.join(os.path.dirname(__file__), "corrector_config")

LANGUAGE_VALUES = ["zh_traditional", "zh_simplified"]
LANGUAGE_LABELS = [LABEL_DICT[val] for val in LANGUAGE_VALUES]

CORRECTOR_CONFIG_PATHS = sorted(glob.glob(os.path.join(CORRECTOR_CONFIG_FOLDER_PATH, "*.json")))
CORRECTOR_CONFIG_VALUES = []
CORRECTOR_CONFIG_LABELS = []
CORRECTOR_CONFIG_FILENAMES = []
endpoint_set = set()
for path in CORRECTOR_CONFIG_PATHS:
	with open(path, "r", encoding="utf8") as f:
		corrector_config = json.loads(f.read())
	if corrector_config['model']['llm_access_method'] != "coseeing_relay":
		endpoint_text = LABEL_DICT[corrector_config['model']['provider']]
		endpoint_set.add(corrector_config['model']['provider'])
	else:
		endpoint_text = LABEL_DICT["Coseeing"]
		endpoint_set.add("Coseeing")
	model_name_text = LABEL_DICT[corrector_config['model']['model_name']]
	typo_correction_mode_text = LABEL_DICT[corrector_config["typo_corrector"]["typo_correction_mode"]]

	CORRECTOR_CONFIG_LABELS.append(f"{endpoint_text}: {model_name_text} | {typo_correction_mode_text}")
	CORRECTOR_CONFIG_VALUES.append(corrector_config)
	CORRECTOR_CONFIG_FILENAMES.append(os.path.basename(path))


class LLMSettingsPanel(SettingsPanel):
	title = _("WordBridge")
	helpId = "WordBridge Settings"

	def makeSettings(self, settingsSizer):
		settingsSizerHelper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)

		# For selecting LLM
		modelLabelText = _("Large Language Model:")
		self.modelList = settingsSizerHelper.addLabeledControl(
			modelLabelText,
			wx.Choice,
			choices=CORRECTOR_CONFIG_LABELS
		)
		self.modelList.SetToolTip(wx.ToolTip(_("Choose the large language model for the Word Bridge")))
		config_filename = config.conf["WordBridge"]["settings"]["corrector_config_filename"]

		if config_filename not in CORRECTOR_CONFIG_FILENAMES:
			model_index = CORRECTOR_CONFIG_FILENAMES.index(CORRECTOR_CONFIG_FILENAME_DEFAULT)
		else:
			model_index = CORRECTOR_CONFIG_FILENAMES.index(config_filename)
		model_provider_selected = CORRECTOR_CONFIG_VALUES[model_index]["model"]["provider"]
		self.modelList.SetSelection(model_index)
		self.modelList.Bind(wx.EVT_CHOICE, self.onChangeChoice)

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

		# For setting account information
		accessPanel = wx.Panel(self)
		self.accessPanelSizer = wx.GridBagSizer(3, 2)
		accessPanel.SetSizer(self.accessPanelSizer)
		self.accessPanelSizer.Fit(self)
		settingsSizerHelper.addItem(accessPanel)

		self.accessLLMTextLabel = wx.StaticText(accessPanel, label="")
		self.accountInfoLabel1 = wx.StaticText(accessPanel, label="")
		self.accountInfoLabel2 = wx.StaticText(accessPanel, label="")
		self.accessPanelSizer.Add(self.accessLLMTextLabel, pos=(0, 0), flag=wx.LEFT, border=0)
		self.accessPanelSizer.Add(self.accountInfoLabel1, pos=(1, 0), flag=wx.LEFT, border=0)
		self.accessPanelSizer.Add(self.accountInfoLabel2, pos=(2, 0), flag=wx.LEFT, border=0)

		self.usernameTextCtrl = wx.TextCtrl(
			accessPanel,
			size=(self.scaleSize(375), -1),
			value=config.conf["WordBridge"]["settings"]["coseeing_username"],
		)
		self.passwordTextCtrl = wx.TextCtrl(
			accessPanel,
			size=(self.scaleSize(375), -1),
			value=config.conf["WordBridge"]["settings"]["coseeing_password"],
			style=wx.TE_PASSWORD,
		)
		self.accessPanelSizer.Add(self.usernameTextCtrl, pos=(1, 1), flag=wx.LEFT, border=0)
		self.accessPanelSizer.Add(self.passwordTextCtrl, pos=(2, 1), flag=wx.LEFT, border=0)
		self.usernameTextCtrl.Hide()
		self.passwordTextCtrl.Hide()

		self.apikeyTextCtrlMap = {}
		self.secretkeyTextCtrlMap = {}
		for endpoint in endpoint_set:
			if endpoint == "Coseeing":
				continue

			if endpoint not in config.conf["WordBridge"]["settings"]["api_key"]:
				config.conf["WordBridge"]["settings"]["api_key"][endpoint] = ""
			if endpoint not in config.conf["WordBridge"]["settings"]["secret_key"]:
				config.conf["WordBridge"]["settings"]["secret_key"][endpoint] = ""

			self.apikeyTextCtrlMap[endpoint] = wx.TextCtrl(
				accessPanel,
				size=(self.scaleSize(375), -1),
				value=config.conf["WordBridge"]["settings"]["api_key"][endpoint],
			)
			self.secretkeyTextCtrlMap[endpoint] = wx.TextCtrl(
				accessPanel,
				size=(self.scaleSize(375), -1),
				value=config.conf["WordBridge"]["settings"]["secret_key"][endpoint],
			)
			self.apikeyTextCtrlMap[endpoint].Hide()
			self.secretkeyTextCtrlMap[endpoint].Hide()

		self._refreshAccountInfo()

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
			wx.CheckBox(self, label=_("Apply customized dictionary"))
		)
		self.customizedWordEnable.SetValue(config.conf["WordBridge"]["settings"]["customized_words_enable"])

		self.wordDictionaryCtrl = settingsSizerHelper.addItem(
			wx.Button(
				self,
				label=_("Edit dictionary"),
			)
		)
		self.wordDictionaryCtrl.Bind(wx.EVT_BUTTON, self.onEditDictionary)

		self.settingsSizer = settingsSizer

	def _refreshAccountInfo(self):
		model_index = self.modelList.GetSelection()
		provider_tmp = CORRECTOR_CONFIG_VALUES[model_index]["model"]["provider"]
		llm_access_method = CORRECTOR_CONFIG_VALUES[model_index]['model']['llm_access_method']
		textctrl1 = self.accessPanelSizer.FindItemAtPosition((1, 1)).GetWindow()
		textctrl2 = self.accessPanelSizer.FindItemAtPosition((2, 1)).GetWindow()

		if llm_access_method == "coseeing_relay":
			self.accessLLMTextLabel.SetLabel(_("Coseeing Account"))
			self.accountInfoLabel1.SetLabel(_("Username:"))
			self.accountInfoLabel2.SetLabel(_("Password:"))
			if textctrl1 != self.usernameTextCtrl:
				self.accessPanelSizer.Detach(textctrl1)
				textctrl1.Hide()
				self.accessPanelSizer.Add(self.usernameTextCtrl, pos=(1, 1))
			if textctrl2 != self.passwordTextCtrl:
				self.accessPanelSizer.Detach(textctrl2)
				textctrl2.Hide()
				self.accessPanelSizer.Add(self.passwordTextCtrl, pos=(2, 1))
			self.accessLLMTextLabel.Show()
			self.accountInfoLabel1.Show()
			self.accountInfoLabel2.Show()
			self.usernameTextCtrl.Show()
			self.passwordTextCtrl.Show()
		elif llm_access_method == "personal_api_key":
			providerLabelText = LABEL_DICT[provider_tmp]
			self.accessLLMTextLabel.SetLabel(providerLabelText + _(" Account"))
			self.accountInfoLabel1.SetLabel(_("API Key:"))
			self.accountInfoLabel2.SetLabel(_("Secret Key:"))
			if textctrl1 != self.apikeyTextCtrlMap[provider_tmp]:
				self.accessPanelSizer.Detach(textctrl1)
				textctrl1.Hide()
				self.accessPanelSizer.Add(self.apikeyTextCtrlMap[provider_tmp], pos=(1, 1))
			if textctrl2 != self.secretkeyTextCtrlMap[provider_tmp]:
				self.accessPanelSizer.Detach(textctrl2)
				textctrl2.Hide()
				self.accessPanelSizer.Add(self.secretkeyTextCtrlMap[provider_tmp], pos=(2, 1))
			self.accessLLMTextLabel.Show()
			self.accountInfoLabel1.Show()
			self.apikeyTextCtrlMap[provider_tmp].Show()
			if CORRECTOR_CONFIG_VALUES[model_index]["model"]["require_secret_key"]:
				self.accountInfoLabel2.Show()
				self.secretkeyTextCtrlMap[provider_tmp].Show()
			else:
				self.accountInfoLabel2.Hide()
				self.secretkeyTextCtrlMap[provider_tmp].Hide()
		else:
			self.accessLLMTextLabel.Hide()
			self.accountInfoLabel1.Hide()
			self.accountInfoLabel2.Hide()
			textctrl1.Hide()
			textctrl2.Hide()

	def onEditDictionary(self, event):
		gui.mainFrame.popupSettingsDialog(DictionaryEntryDialog)

	def onSave(self):
		model_index = self.modelList.GetSelection()
		config.conf["WordBridge"]["settings"]["corrector_config_filename"] = CORRECTOR_CONFIG_FILENAMES[model_index]
		config.conf["WordBridge"]["settings"]["language"] = LANGUAGE_VALUES[self.languageList.GetSelection()]
		config.conf["WordBridge"]["settings"]["coseeing_username"] = self.usernameTextCtrl.GetValue()
		config.conf["WordBridge"]["settings"]["coseeing_password"] = self.passwordTextCtrl.GetValue()
		config.conf["WordBridge"]["settings"]["max_char_count"] = self.maxCharCountSpinCtrl.GetValue()
		config.conf["WordBridge"]["settings"]["auto_display_report"] = self.autoDisplayReportEnable.GetValue()
		config.conf["WordBridge"]["settings"]["customized_words_enable"] = self.customizedWordEnable.GetValue()
		for i in range(len(CORRECTOR_CONFIG_VALUES)):
			provider_tmp = CORRECTOR_CONFIG_VALUES[i]["model"]["provider"]
			api_key_tmp = self.apikeyTextCtrlMap[provider_tmp].GetValue()
			secret_key_tmp = self.secretkeyTextCtrlMap[provider_tmp].GetValue()
			config.conf["WordBridge"]["settings"]["api_key"][provider_tmp] = api_key_tmp
			config.conf["WordBridge"]["settings"]["secret_key"][provider_tmp] = secret_key_tmp

	def onChangeChoice(self, evt):
		self.Freeze()
		# trigger a refresh of the settings
		self._refreshAccountInfo()
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
