from configobj.validate import VdtValueTooBigError, VdtValueTooSmallError

import config
import wx
import addonHandler

from gui import guiHelper, nvdaControls
from gui.contextHelp import ContextHelpMixin
from gui.settingsDialogs import SettingsPanel


addonHandler.initTranslation()

model_labels = [_("gpt-3.5-turbo"), _("gpt-4-turbo"), _("gpt-4o"), _("gpt-4o | Simple Mode")]
model_values = ["gpt-3.5-turbo", "gpt-4-turbo", "gpt-4o", "gpt-4o | Simple Mode"]
gpt_access_method_labels = [_("OpenAI API Key"), _("Coseeing Account")]
gpt_access_method_values = ["openai_api_key", "coseeing_account"]
language_labels = [_("Traditional Chinese"), _("Simplified Chinese")]
language_values = ["zh_traditional_tw", "zh_simplified"]

class OpenAIGeneralSettingsPanel(SettingsPanel):
	title = _("WordBridge")
	helpId = "WordBridge Settings"

	def makeSettings(self, settingsSizer):
		settingsSizerHelper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)

		# For selecting OpenAI model
		modelLabelText = _("Model:")
		self.modelList = settingsSizerHelper.addLabeledControl(modelLabelText, wx.Choice, choices=model_labels)
		self.modelList.SetToolTip(wx.ToolTip(_("Choose the OpenAI model for the Word Bridge")))
		if config.conf["WordBridge"]["settings"]["model"] in model_values:
			self.modelList.SetSelection(model_values.index(config.conf["WordBridge"]["settings"]["model"]))
		else:
			self.modelList.SetSelection(0)
			config.conf["WordBridge"]["settings"]["model"] = model_values[0]

		# For selecting language
		languageLabelText = _("Language:")
		self.languageList = settingsSizerHelper.addLabeledControl(languageLabelText, wx.Choice, choices=language_labels)
		self.languageList.SetToolTip(wx.ToolTip(_("Choose the language for the Word Bridge")))
		if config.conf["WordBridge"]["settings"]["language"] in language_values:
			self.languageList.SetSelection(language_values.index(config.conf["WordBridge"]["settings"]["language"]))
		else:
			self.languageList.SetSelection(0)
			config.conf["WordBridge"]["settings"]["language"] = language_values[0]

		# For selecting GPT access method
		accessMethodLabelText = _("GPT Access Method:")
		self.methodList = settingsSizerHelper.addLabeledControl(
			accessMethodLabelText,
			wx.Choice,
			choices=gpt_access_method_labels,
		)
		self.methodList.SetToolTip(wx.ToolTip(_("Choose the GPT access method")))
		if config.conf["WordBridge"]["settings"]["gpt_access_method"] in gpt_access_method_values:
			self.methodList.SetSelection(
				gpt_access_method_values.index(config.conf["WordBridge"]["settings"]["gpt_access_method"])
			)
		else:
			self.methodList.SetSelection(0)
			config.conf["WordBridge"]["settings"]["gpt_access_method"] = gpt_access_method_values[0]
		self.methodList.Bind(wx.EVT_CHOICE, self.onChangeChoice)

		# For setting account information
		accessPanel = wx.Panel(self)
		sizer = wx.GridBagSizer(5, 2)

		self.accessOpenAITextLabel = wx.StaticText(accessPanel, label=_("OpenAI Account"))
		sizer.Add(self.accessOpenAITextLabel, pos=(0, 0), flag=wx.LEFT, border=0)

		self.apikeyTextLabel = wx.StaticText(accessPanel, label=_("API Key:"))
		sizer.Add(self.apikeyTextLabel, pos=(1, 0), flag=wx.LEFT, border=10)
		self.apikeyTextCtrl = wx.TextCtrl(
			accessPanel,
			size=(self.scaleSize(375), -1),
			value=config.conf["WordBridge"]["settings"]["openai_key"],
		)
		sizer.Add(self.apikeyTextCtrl, pos=(1, 1))

		self.accessCoseeingTextLabel = wx.StaticText(accessPanel, label=_("Coseeing Account"))
		sizer.Add(self.accessCoseeingTextLabel, pos=(2, 0), flag=wx.LEFT, border=0)

		self.usernameTextLabel = wx.StaticText(accessPanel, label=_("Username:"))
		sizer.Add(self.usernameTextLabel, pos=(3, 0), flag=wx.LEFT, border=10)
		self.usernameTextCtrl = wx.TextCtrl(
			accessPanel,
			size=(self.scaleSize(375), -1),
			value=config.conf["WordBridge"]["settings"]["coseeing_username"],
		)
		sizer.Add(self.usernameTextCtrl, pos=(3, 1))

		self.passwordTextLabel = wx.StaticText(accessPanel, label=_("Password:"))
		sizer.Add(self.passwordTextLabel, pos=(4, 0), flag=wx.LEFT, border=10)

		self.passwordTextCtrl = wx.TextCtrl(
			accessPanel,
			size=(self.scaleSize(375), -1),
			value=config.conf["WordBridge"]["settings"]["coseeing_password"],
			style=wx.TE_PASSWORD,
		)
		sizer.Add(self.passwordTextCtrl, pos=(4, 1))

		self._enableAccessElements(gpt_access_method_values[self.methodList.GetSelection()])

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
		config.conf["WordBridge"]["settings"]["model"] = model_values[self.modelList.GetSelection()]
		config.conf["WordBridge"]["settings"]["language"] = language_values[self.languageList.GetSelection()]
		config.conf["WordBridge"]["settings"]["gpt_access_method"] = gpt_access_method_values[self.methodList.GetSelection()]
		config.conf["WordBridge"]["settings"]["openai_key"] = self.apikeyTextCtrl.GetValue()
		config.conf["WordBridge"]["settings"]["coseeing_username"] = self.usernameTextCtrl.GetValue()
		config.conf["WordBridge"]["settings"]["coseeing_password"] = self.passwordTextCtrl.GetValue()
		config.conf["WordBridge"]["settings"]["max_char_count"] = self.maxCharCount.GetValue()
		config.conf["WordBridge"]["settings"]["auto_display_report"] = self.autoDisplayReport.GetValue()

	def onChangeChoice(self, evt):
		self.Freeze()
		# trigger a refresh of the settings
		self.onPanelActivated()
		self._sendLayoutUpdatedEvent()
		self._enableAccessElements(gpt_access_method_values[self.methodList.GetSelection()])
		self.Thaw()

	def _enableAccessElements(self, gpt_access_method):
		if gpt_access_method == "openai_api_key":
			self.accessCoseeingTextLabel.Disable()
			self.usernameTextLabel.Disable()
			self.passwordTextLabel.Disable()
			self.usernameTextCtrl.Disable()
			self.passwordTextCtrl.Disable()
			self.accessOpenAITextLabel.Enable()
			self.apikeyTextLabel.Enable()
			self.apikeyTextCtrl.Enable()
		else:
			self.accessCoseeingTextLabel.Enable()
			self.usernameTextLabel.Enable()
			self.passwordTextLabel.Enable()
			self.usernameTextCtrl.Enable()
			self.passwordTextCtrl.Enable()
			self.accessOpenAITextLabel.Disable()
			self.apikeyTextLabel.Disable()
			self.apikeyTextCtrl.Disable()

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
