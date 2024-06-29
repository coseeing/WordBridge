from configobj.validate import VdtValueTooBigError, VdtValueTooSmallError

import config
import glob
import json
import os
import wx
import addonHandler

from gui import guiHelper, nvdaControls
from gui.contextHelp import ContextHelpMixin
from gui.settingsDialogs import SettingsPanel


addonHandler.initTranslation()

corrector_info_dict = {
	"OpenAI": _("OpenAI"),
	"Baidu": _("Baidu"),
	"gpt-3.5-turbo": _("gpt-3.5-turbo"),
	"gpt-4-turbo": _("gpt-4-turbo"),
	"gpt-4o": _("gpt-4o"),
	"ernie-4.0-8k-preview": _("ernie-4.0-8k-preview"),
	"Standard Mode": _("Standard Mode"),
	"Lite Mode": _("Lite Mode")
}

llm_access_method_labels = [
	_("Personal API Key"),
	_("Coseeing Account"),
]
llm_access_method_values = [
	"personal_api_key",
	"coseeing_account",
]
language_labels = [_("Traditional Chinese"), _("Simplified Chinese")]
language_values = ["zh_traditional_tw", "zh_simplified"]

corrector_config_path_default = os.path.join(
	os.path.dirname(__file__), "corrector_config", "gpt-3.5-turbo (standard mode).json"
)
corrector_config_paths = sorted(
	glob.glob(os.path.join(os.path.dirname(__file__), "corrector_config", "*.json"))
)
corrector_configs = []
for path in corrector_config_paths:
	with open(path, "r") as f:
		corrector_configs.append(json.loads(f.read()))

model_config_labels = []
model_config_values = []
for llm_config in corrector_configs:
	provider = llm_config['model']['provider']
	model_name = llm_config['model']['model_name']
	typo_correction_mode = llm_config["typo_corrector"]["typo_correction_mode"]
	provider_text = corrector_info_dict[provider]
	model_name_text = corrector_info_dict[model_name]
	typo_correction_mode_text = corrector_info_dict[typo_correction_mode]
	model_config_labels.append(f"{provider_text}: {model_name_text} | {typo_correction_mode_text}")
	model_config_values.append(llm_config)


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
			choices=model_config_labels
		)
		self.modelList.SetToolTip(wx.ToolTip(_("Choose the large language model for the Word Bridge")))
		model_config_val = config.conf["WordBridge"]["settings"]["corrector_config"].dict()

		if model_config_val not in model_config_values:
			model_index = corrector_config_paths.index(corrector_config_path_default)
			config.conf["WordBridge"]["settings"]["corrector_config"] = model_config_values[model_index]
		else:
			model_index = model_config_values.index(model_config_val)
		model_provider_selected = config.conf["WordBridge"]["settings"]["corrector_config"]["model"]["provider"]
		self.modelList.SetSelection(model_index)
		self.modelList.Bind(wx.EVT_CHOICE, self.onChangeChoice)

		# For selecting language
		languageLabelText = _("Language:")
		self.languageList = settingsSizerHelper.addLabeledControl(
			languageLabelText,
			wx.Choice,
			choices=language_labels
		)
		self.languageList.SetToolTip(wx.ToolTip(_("Choose the language for the Word Bridge")))
		if config.conf["WordBridge"]["settings"]["language"] in language_values:
			self.languageList.SetSelection(language_values.index(config.conf["WordBridge"]["settings"]["language"]))
		else:
			self.languageList.SetSelection(0)
			config.conf["WordBridge"]["settings"]["language"] = language_values[0]

		# For selecting LLM access method
		accessMethodLabelText = _("Large Language Model Access Method:")
		self.methodList = settingsSizerHelper.addLabeledControl(
			accessMethodLabelText,
			wx.Choice,
			choices=llm_access_method_labels,
		)
		self.methodList.SetToolTip(wx.ToolTip(_("Choose the large language model access method")))
		if config.conf["WordBridge"]["settings"]["llm_access_method"] in llm_access_method_values:
			self.methodList.SetSelection(
				llm_access_method_values.index(config.conf["WordBridge"]["settings"]["llm_access_method"])
			)
		else:
			self.methodList.SetSelection(0)
			config.conf["WordBridge"]["settings"]["llm_access_method"] = llm_access_method_values[0]
		self.methodList.Bind(wx.EVT_CHOICE, self.onChangeChoice)

		# For setting account information
		accessPanel = wx.Panel(self)
		sizer = wx.GridBagSizer(6, 2)

		providerLabelText = corrector_info_dict[model_provider_selected]
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

		self._enableAccessElements(llm_access_method_values[self.methodList.GetSelection()])

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
		provider_tmp = model_config_values[model_index]["model"]["provider"]
		config.conf["WordBridge"]["settings"]["corrector_config"] = model_config_values[model_index]
		config.conf["WordBridge"]["settings"]["language"] = language_values[self.languageList.GetSelection()]
		config.conf["WordBridge"]["settings"]["llm_access_method"] = llm_access_method_values[access_method_index]
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
		self._enableAccessElements(llm_access_method_values[self.methodList.GetSelection()])
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

		provider_tmp = model_config_values[self.modelList.GetSelection()]["model"]["provider"]
		self.apikeyTextCtrl.SetValue(config.conf["WordBridge"]["settings"]["api_key"][provider_tmp])

		if corrector_configs[self.modelList.GetSelection()]["model"]["require_secret_key"]:
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
