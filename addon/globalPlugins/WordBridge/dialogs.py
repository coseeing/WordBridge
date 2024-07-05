from configobj.validate import VdtValueTooBigError, VdtValueTooSmallError

import config
import glob
import json
import locale
import os
import wx
import addonHandler

from gui import guiHelper, nvdaControls
from gui.contextHelp import ContextHelpMixin
from gui.settingsDialogs import SettingsPanel


addonHandler.initTranslation()

LABEL_DICT = {
	"OpenAI": _("OpenAI"),
	"Baidu": _("Baidu"),
	"gpt-3.5-turbo": _("gpt-3.5-turbo"),
	"gpt-4-turbo": _("gpt-4-turbo"),
	"gpt-4o": _("gpt-4o"),
	"ernie-4.0-8k-preview": _("ernie-4.0-8k-preview"),
	"Standard Mode": _("Standard Mode"),
	"Lite Mode": _("Lite Mode"),
	"personal_api_key": _("Personal API Key"),
	"coseeing_account": _("Coseeing Account"),
	"zh_traditional": _("Traditional Chinese"),
	"zh_simplified": _("Simplified Chinese"),
}

if locale.getdefaultlocale()[0] in ["zh_TW", "zh_MO", "zh_HK"]:
	LANGUAGE_DEFAULT = "zh_traditional"
else:
	LANGUAGE_DEFAULT = "zh_simplified"
CORRECTOR_CONFIG_FILENAME_DEFAULT = "gpt-3.5-turbo (standard mode).json"
CORRECTOR_CONFIG_FOLDER_PATH = os.path.join(os.path.dirname(__file__), "corrector_config")

LLM_ACCESS_METHOD_VALUES = ["personal_api_key", "coseeing_account"]
LANGUAGE_VALUES = ["zh_traditional", "zh_simplified"]
LLM_ACCESS_METHOD_LABELS = [LABEL_DICT[val] for val in LLM_ACCESS_METHOD_VALUES]
LANGUAGE_LABELS = [LABEL_DICT[val] for val in LANGUAGE_VALUES]

CORRECTOR_CONFIG_PATHS = sorted(glob.glob(os.path.join(CORRECTOR_CONFIG_FOLDER_PATH, "*.json")))
CORRECTOR_CONFIG_VALUES = []
CORRECTOR_CONFIG_LABELS = []
CORRECTOR_CONFIG_FILENAMES = []
for path in CORRECTOR_CONFIG_PATHS:
	with open(path, "r") as f:
		corrector_config = json.loads(f.read())
	provider_text = LABEL_DICT[corrector_config['model']['provider']]
	model_name_text = LABEL_DICT[corrector_config['model']['model_name']]
	typo_correction_mode_text = LABEL_DICT[corrector_config["typo_corrector"]["typo_correction_mode"]]

	CORRECTOR_CONFIG_LABELS.append(f"{provider_text}: {model_name_text} | {typo_correction_mode_text}")
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

		# For selecting LLM access method
		accessMethodLabelText = _("Large Language Model Access Method:")
		self.methodList = settingsSizerHelper.addLabeledControl(
			accessMethodLabelText,
			wx.Choice,
			choices=LLM_ACCESS_METHOD_LABELS,
		)
		self.methodList.SetToolTip(wx.ToolTip(_("Choose the large language model access method")))
		if config.conf["WordBridge"]["settings"]["llm_access_method"] in LLM_ACCESS_METHOD_VALUES:
			self.methodList.SetSelection(
				LLM_ACCESS_METHOD_VALUES.index(config.conf["WordBridge"]["settings"]["llm_access_method"])
			)
		else:
			self.methodList.SetSelection(0)
			config.conf["WordBridge"]["settings"]["llm_access_method"] = LLM_ACCESS_METHOD_VALUES[0]
		self.methodList.Bind(wx.EVT_CHOICE, self.onChangeChoice)

		# For setting account information
		accessPanel = wx.Panel(self)
		sizer = wx.GridBagSizer(6, 2)

		providerLabelText = LABEL_DICT[model_provider_selected]
		self.accessLLMTextLabel = wx.StaticText(accessPanel, label=providerLabelText + _(" Account"))
		sizer.Add(self.accessLLMTextLabel, pos=(0, 0), flag=wx.LEFT, border=0)

		if model_provider_selected not in config.conf["WordBridge"]["settings"]["api_key"]:
			config.conf["WordBridge"]["settings"]["api_key"][model_provider_selected] = ""
		self.apikeyTextLabel = wx.StaticText(accessPanel, label=_("API Key:"))
		sizer.Add(self.apikeyTextLabel, pos=(1, 0), flag=wx.LEFT, border=10)
		self.apikeyTextCtrl = wx.TextCtrl(
			accessPanel,
			size=(self.scaleSize(375), -1),
			value=config.conf["WordBridge"]["settings"]["api_key"][model_provider_selected],
		)
		sizer.Add(self.apikeyTextCtrl, pos=(1, 1))

		if model_provider_selected not in config.conf["WordBridge"]["settings"]["secret_key"]:
			config.conf["WordBridge"]["settings"]["secret_key"][model_provider_selected] = ""
		self.secretkeyTextLabel = wx.StaticText(accessPanel, label=_("Secret Key:"))
		sizer.Add(self.secretkeyTextLabel, pos=(2, 0), flag=wx.LEFT, border=10)
		self.secretkeyTextCtrl = wx.TextCtrl(
			accessPanel,
			size=(self.scaleSize(375), -1),
			value=config.conf["WordBridge"]["settings"]["secret_key"][model_provider_selected],
		)
		sizer.Add(self.secretkeyTextCtrl, pos=(2, 1))

		self.accessCoseeingTextLabel = wx.StaticText(accessPanel, label=_("Coseeing Account"))
		sizer.Add(self.accessCoseeingTextLabel, pos=(3, 0), flag=wx.LEFT, border=0)

		self.usernameTextLabel = wx.StaticText(accessPanel, label=_("Username:"))
		sizer.Add(self.usernameTextLabel, pos=(4, 0), flag=wx.LEFT, border=10)
		self.usernameTextCtrl = wx.TextCtrl(
			accessPanel,
			size=(self.scaleSize(375), -1),
			value=config.conf["WordBridge"]["settings"]["coseeing_username"],
		)
		sizer.Add(self.usernameTextCtrl, pos=(4, 1))

		self.passwordTextLabel = wx.StaticText(accessPanel, label=_("Password:"))
		sizer.Add(self.passwordTextLabel, pos=(5, 0), flag=wx.LEFT, border=10)

		self.passwordTextCtrl = wx.TextCtrl(
			accessPanel,
			size=(self.scaleSize(375), -1),
			value=config.conf["WordBridge"]["settings"]["coseeing_password"],
			style=wx.TE_PASSWORD,
		)
		sizer.Add(self.passwordTextCtrl, pos=(5, 1))

		self._enableAccessElements(LLM_ACCESS_METHOD_VALUES[self.methodList.GetSelection()])

		accessPanel.SetSizer(sizer)
		sizer.Fit(self)
		settingsSizerHelper.addItem(accessPanel)

		# For setting upper bound of correction character count
		maxTokensLabelText = _("Max Character Count")
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
		self.maxCharCount = settingsSizerHelper.addLabeledControl(
			maxTokensLabelText,
			nvdaControls.SelectOnFocusSpinCtrl,
			min=maxCharCountlowerBound,
			max=maxCharCountUpperBound,
			initial=maxCharCount
		)

		# For setting auto display typo report
		self.autoDisplayReport = settingsSizerHelper.addItem(wx.CheckBox(self, label=_("Auto display typo report")))
		self.autoDisplayReport.SetValue(config.conf["WordBridge"]["settings"]["auto_display_report"])

		self.settingsSizer = settingsSizer

	def onSave(self):
		model_index = self.modelList.GetSelection()
		access_method_index = self.methodList.GetSelection()
		provider_tmp = CORRECTOR_CONFIG_VALUES[model_index]["model"]["provider"]
		config.conf["WordBridge"]["settings"]["corrector_config_filename"] = CORRECTOR_CONFIG_FILENAMES[model_index]
		config.conf["WordBridge"]["settings"]["language"] = LANGUAGE_VALUES[self.languageList.GetSelection()]
		config.conf["WordBridge"]["settings"]["llm_access_method"] = LLM_ACCESS_METHOD_VALUES[access_method_index]
		config.conf["WordBridge"]["settings"]["api_key"][provider_tmp] = self.apikeyTextCtrl.GetValue()
		config.conf["WordBridge"]["settings"]["secret_key"][provider_tmp] = self.secretkeyTextCtrl.GetValue()
		config.conf["WordBridge"]["settings"]["coseeing_username"] = self.usernameTextCtrl.GetValue()
		config.conf["WordBridge"]["settings"]["coseeing_password"] = self.passwordTextCtrl.GetValue()
		config.conf["WordBridge"]["settings"]["max_char_count"] = self.maxCharCount.GetValue()
		config.conf["WordBridge"]["settings"]["auto_display_report"] = self.autoDisplayReport.GetValue()

	def onChangeChoice(self, evt):
		self.Freeze()
		# trigger a refresh of the settings
		self.onPanelActivated()
		self._sendLayoutUpdatedEvent()
		self._enableAccessElements(LLM_ACCESS_METHOD_VALUES[self.methodList.GetSelection()])
		self.Thaw()

	def _enableAccessElements(self, llm_access_method):
		if llm_access_method == "personal_api_key":
			self.accessCoseeingTextLabel.Disable()
			self.usernameTextLabel.Disable()
			self.passwordTextLabel.Disable()
			self.usernameTextCtrl.Disable()
			self.passwordTextCtrl.Disable()
			self.accessLLMTextLabel.Enable()
			self.apikeyTextLabel.Enable()
			self.apikeyTextCtrl.Enable()
			self.secretkeyTextLabel.Enable()
			self.secretkeyTextCtrl.Enable()
		else:
			self.accessCoseeingTextLabel.Enable()
			self.usernameTextLabel.Enable()
			self.passwordTextLabel.Enable()
			self.usernameTextCtrl.Enable()
			self.passwordTextCtrl.Enable()
			self.accessLLMTextLabel.Disable()
			self.apikeyTextLabel.Disable()
			self.apikeyTextCtrl.Disable()
			self.secretkeyTextLabel.Disable()
			self.secretkeyTextCtrl.Disable()

		provider_tmp = CORRECTOR_CONFIG_VALUES[self.modelList.GetSelection()]["model"]["provider"]
		self.apikeyTextCtrl.SetValue(config.conf["WordBridge"]["settings"]["api_key"][provider_tmp])

		if CORRECTOR_CONFIG_VALUES[self.modelList.GetSelection()]["model"]["require_secret_key"]:
			self.secretkeyTextLabel.Show()
			self.secretkeyTextCtrl.Show()
			self.secretkeyTextCtrl.SetValue(config.conf["WordBridge"]["settings"]["secret_key"][provider_tmp])
		else:
			self.secretkeyTextLabel.Hide()
			self.secretkeyTextCtrl.Hide()

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
