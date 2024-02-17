from configobj.validate import VdtValueTooBigError, VdtValueTooSmallError

import config
import wx
import addonHandler

from gui import guiHelper, nvdaControls
from gui.settingsDialogs import SettingsPanel


addonHandler.initTranslation()

model_list = ["gpt-3.5-turbo"]
gpt_access_method_list = [_("OpenAI API Key"), _("Coseeing Account")]
gpt_access_methods = ["openai_api_key", "coseeing_account"]


class OpenAIGeneralSettingsPanel(SettingsPanel):
	title = _("GPT Assistant")
	helpId = "GPTAssistantSettings"

	def makeSettings(self, settingsSizer):
		settingsSizerHelper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)

		# For selecting OpenAI model
		modelLabelText = _("OpenAI Model:")
		self.modelList = settingsSizerHelper.addLabeledControl(modelLabelText, wx.Choice, choices=model_list)
		self.modelList.SetToolTip(wx.ToolTip(_("Choose the OpenAI model for the GPT assistant")))
		if config.conf["GPTAssistant"]["settings"]["model"] in model_list:
			self.modelList.SetSelection(model_list.index(config.conf["GPTAssistant"]["settings"]["model"]))
		else:
			self.modelList.SetSelection(0)
			config.conf["GPTAssistant"]["settings"]["model"] = model_list[0]

		# For selecting GPT access method
		accessMethodLabelText = _("GPT Access Method:")
		self.methodList = settingsSizerHelper.addLabeledControl(
			accessMethodLabelText,
			wx.Choice,
			choices=gpt_access_method_list,
		)
		self.methodList.SetToolTip(wx.ToolTip(_("Choose the GPT access method")))
		if config.conf["GPTAssistant"]["settings"]["gpt_access_method"] in gpt_access_methods:
			self.methodList.SetSelection(
				gpt_access_methods.index(config.conf["GPTAssistant"]["settings"]["gpt_access_method"])
			)
		else:
			self.methodList.SetSelection(0)
			config.conf["GPTAssistant"]["settings"]["gpt_access_method"] = gpt_access_methods[0]
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
			value=config.conf["GPTAssistant"]["settings"]["openai_key"],
		)
		sizer.Add(self.apikeyTextCtrl, pos=(1, 1))

		self.accessCoseeingTextLabel = wx.StaticText(accessPanel, label=_("Coseeing Account"))
		sizer.Add(self.accessCoseeingTextLabel, pos=(2, 0), flag=wx.LEFT, border=0)

		self.usernameTextLabel = wx.StaticText(accessPanel, label=_("Username:"))
		sizer.Add(self.usernameTextLabel, pos=(3, 0), flag=wx.LEFT, border=10)
		self.usernameTextCtrl = wx.TextCtrl(
			accessPanel,
			size=(self.scaleSize(375), -1),
			value=config.conf["GPTAssistant"]["settings"]["coseeing_username"],
		)
		sizer.Add(self.usernameTextCtrl, pos=(3, 1))

		self.passwordTextLabel = wx.StaticText(accessPanel, label=_("Password:"))
		sizer.Add(self.passwordTextLabel, pos=(4, 0), flag=wx.LEFT, border=10)

		self.passwordTextCtrl = wx.TextCtrl(
			accessPanel,
			size=(self.scaleSize(375), -1),
			value=config.conf["GPTAssistant"]["settings"]["coseeing_password"],
			style=wx.TE_PASSWORD,
		)
		sizer.Add(self.passwordTextCtrl, pos=(4, 1))

		self._enableAccessElements(gpt_access_methods[self.methodList.GetSelection()])

		accessPanel.SetSizer(sizer)
		sizer.Fit(self)
		settingsSizerHelper.addItem(accessPanel)

		# For setting upper bound of correction character count
		maxTokensLabelText = _("Max Character Count")
		try:
			maxCharCount = config.conf["GPTAssistant"]["settings"]["max_char_count"]
		except VdtValueTooBigError:
			maxCharCount = int(config.conf.getConfigValidation(
				("GPTAssistant", "settings", "max_char_count")
			).kwargs["max"])
		except VdtValueTooSmallError:
			maxCharCount = int(config.conf.getConfigValidation(
				("GPTAssistant", "settings", "max_char_count")
			).kwargs["min"])

		maxCharCountlowerBound = int(config.conf.getConfigValidation(
			("GPTAssistant", "settings", "max_char_count")
		).kwargs["min"])
		maxCharCountUpperBound = int(config.conf.getConfigValidation(
			("GPTAssistant", "settings", "max_char_count")
		).kwargs["max"])
		self.maxCharCount = settingsSizerHelper.addLabeledControl(
			maxTokensLabelText,
			nvdaControls.SelectOnFocusSpinCtrl,
			min=maxCharCountlowerBound,
			max=maxCharCountUpperBound,
			initial=maxCharCount
		)

		self.settingsSizer = settingsSizer

	def onSave(self):
		current_gpt_access_method = gpt_access_methods[self.methodList.GetSelection()]
		config.conf["GPTAssistant"]["settings"]["model"] = model_list[self.modelList.GetSelection()]
		config.conf["GPTAssistant"]["settings"]["gpt_access_method"] = current_gpt_access_method
		config.conf["GPTAssistant"]["settings"]["openai_key"] = self.apikeyTextCtrl.GetValue()
		config.conf["GPTAssistant"]["settings"]["coseeing_username"] = self.usernameTextCtrl.GetValue()
		config.conf["GPTAssistant"]["settings"]["coseeing_password"] = self.passwordTextCtrl.GetValue()
		config.conf["GPTAssistant"]["settings"]["max_char_count"] = self.maxCharCount.GetValue()

	def onChangeChoice(self, evt):
		self.Freeze()
		# trigger a refresh of the settings
		self.onPanelActivated()
		self._sendLayoutUpdatedEvent()
		self._enableAccessElements(gpt_access_methods[self.methodList.GetSelection()])
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
