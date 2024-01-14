from wx.lib.expando import ExpandoTextCtrl

import config
import wx

from gui import guiHelper, nvdaControls
from gui.settingsDialogs import MultiCategorySettingsDialog, SettingsDialog, SettingsPanel


model_list = ["gpt-3.5-turbo", "text-davinci-003"]
gpt_access_method_list = ["OpenAI API Key", "XXX Account"]

class OpenAIGeneralSettingsPanel(SettingsPanel):
	title = _("OpenAIGeneral")
	helpId = "OpenAIGeneralSettings"

	def makeSettings(self, settingsSizer):
		settingsSizerHelper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)

		# For selecting OpenAI model
		modelLabelText = _("OpenAI Model:")
		self.modelList = settingsSizerHelper.addLabeledControl(modelLabelText, wx.Choice, choices=model_list)
		self.modelList.SetToolTip(wx.ToolTip("Choose the openAI model for the GPT assistant"))
		self.modelList.SetSelection(model_list.index(config.conf["GPTAssistant"]["settings"]["model"]))

		# For selecting GPT access method
		accessMethodLabelText = _("GPT Access Method:")
		self.methodList = settingsSizerHelper.addLabeledControl(accessMethodLabelText, wx.Choice, choices=gpt_access_method_list)
		self.methodList.SetToolTip(wx.ToolTip("Choose the GPT access method"))
		if config.conf["GPTAssistant"]["settings"]["gpt_access_method"] in gpt_access_method_list:
			self.methodList.SetSelection(gpt_access_method_list.index(config.conf["GPTAssistant"]["settings"]["gpt_access_method"]))
		else:
			self.methodList.SetSelection(0)
			config.conf["GPTAssistant"]["settings"]["gpt_access_method"] = gpt_access_method_list[0]
		self.methodList.Bind(wx.EVT_CHOICE, self.onChangeChoice)

		# For setting account information
		accessPanel = wx.Panel(self)
		sizer = wx.GridBagSizer(5, 3)

		accessOpenAITextLabel = wx.StaticText(accessPanel, label="OpenAI Account")
		sizer.Add(accessOpenAITextLabel, pos=(0, 0), flag=wx.LEFT, border=0)

		apikeyTextLabel = wx.StaticText(accessPanel, label="API Key:")
		sizer.Add(apikeyTextLabel, pos=(1, 0), flag=wx.LEFT, border=10)
		show_key = "*" * (len(config.conf["GPTAssistant"]["settings"]["openai_key"]) - 4)
		show_key += config.conf["GPTAssistant"]["settings"]["openai_key"][-4:]
		self.apikeyTextCtrl = wx.TextCtrl(
			accessPanel,
			size=(self.scaleSize(375), -1),
			value=show_key,
			style=wx.TE_READONLY,
		)
		sizer.Add(self.apikeyTextCtrl, pos=(1, 1))

		apikeyChangeButton = wx.Button(accessPanel, label="C&hange...")
		sizer.Add(apikeyChangeButton, pos=(1, 2), border=20)
		apikeyChangeButton.Bind(wx.EVT_BUTTON, self.onChangeKey)

		accessXXXTextLabel = wx.StaticText(accessPanel, label="XXX Account")
		sizer.Add(accessXXXTextLabel, pos=(2, 0), flag=wx.LEFT, border=0)

		accountTextLabel = wx.StaticText(accessPanel, label="Account Name:")
		sizer.Add(accountTextLabel, pos=(3, 0), flag=wx.LEFT, border=10)
		self.accountTextCtrl = wx.TextCtrl(
			accessPanel,
			size=(self.scaleSize(375), -1),
			value=config.conf["GPTAssistant"]["settings"]["account_name"],
			style=wx.TE_READONLY,
		)
		sizer.Add(self.accountTextCtrl, pos=(3, 1))

		passwordTextLabel = wx.StaticText(accessPanel, label="Password:")
		sizer.Add(passwordTextLabel, pos=(4, 0), flag=wx.LEFT, border=10)

		self.passwordTextCtrl = wx.TextCtrl(
			accessPanel,
			size=(self.scaleSize(375), -1),
			value=config.conf["GPTAssistant"]["settings"]["password"],
			style=wx.TE_PASSWORD | wx.TE_READONLY,
		)
		sizer.Add(self.passwordTextCtrl, pos=(4, 1))

		accountChangeButton = wx.Button(accessPanel, label="C&hange...")
		sizer.Add(accountChangeButton, pos=(4, 2), border=20)
		accountChangeButton.Bind(wx.EVT_BUTTON, self.onChangeKey)

		if config.conf["GPTAssistant"]["settings"]["gpt_access_method"] == "OpenAI API Key":
			accessXXXTextLabel.Disable()
			accountTextLabel.Disable()
			passwordTextLabel.Disable()
			self.accountTextCtrl.Disable()
			self.passwordTextCtrl.Disable()
			accountChangeButton.Disable()
		else:
			accessOpenAITextLabel.Disable()
			apikeyTextLabel.Disable()
			self.apikeyTextCtrl.Disable()
			apikeyChangeButton.Disable()

		accessPanel.SetSizer(sizer)
		sizer.Fit(self)
		settingsSizerHelper.addItem(accessPanel)

		# For setting upper bound of correction word count
		maxTokensLabelText = _("Max Word Count")
		maxWordCount = config.conf["GPTAssistant"]["settings"]["max_word_count"]
		maxWordCountlowerBound = int(config.conf.getConfigValidation(
			("GPTAssistant", "settings", "max_word_count")
		).kwargs["min"])
		maxWordCountUpperBound = int(config.conf.getConfigValidation(
			("GPTAssistant", "settings", "max_word_count")
		).kwargs["max"])
		self.maxWordCount = settingsSizerHelper.addLabeledControl(
			maxTokensLabelText,
			nvdaControls.SelectOnFocusSpinCtrl,
			min=maxWordCountlowerBound,
			max=maxWordCountUpperBound,
			initial=maxWordCount
		)

		self.settingsSizer = settingsSizer

	def onSave(self):
		config.conf["GPTAssistant"]["settings"]["model"] = model_list[self.modelList.GetSelection()]
		config.conf["GPTAssistant"]["settings"]["gpt_access_method"] = gpt_access_method_list[self.methodList.GetSelection()]
		config.conf["GPTAssistant"]["settings"]["openai_key"] = self.apikeyTextCtrl.GetValue()
		config.conf["GPTAssistant"]["settings"]["account_name"] = self.accountTextCtrl.GetValue()
		config.conf["GPTAssistant"]["settings"]["password"] = self.passwordTextCtrl.GetValue()
		config.conf["GPTAssistant"]["settings"]["max_word_count"] = self.maxWordCount.GetValue()

	def _enterTriggersOnChangeKey(self, evt):
		if evt.KeyCode == wx.WXK_RETURN:
			self.onChangeKey(evt)
		else:
			evt.Skip()

	def onChangeKey(self, evt):
		if config.conf["GPTAssistant"]["settings"]["gpt_access_method"] == "OpenAI API Key":
			changeDisplay = OpenAIKeySettingDialog(self, multiInstanceAllowed=True)
		else:
			changeDisplay = XXXAccountSettingDialog(self, multiInstanceAllowed=True)
		ret = changeDisplay.ShowModal()
		if ret == wx.ID_OK:
			self.Freeze()
			# trigger a refresh of the settings
			self.onPanelActivated()
			self._sendLayoutUpdatedEvent()
			self.Thaw()

	def onChangeChoice(self, evt):
		config.conf["GPTAssistant"]["settings"]["gpt_access_method"] = gpt_access_method_list[self.methodList.GetSelection()]
		self.Freeze()
		# trigger a refresh of the settings
		self.onPanelActivated()
		self._sendLayoutUpdatedEvent()
		self.settingsSizer.Clear(delete_windows=True)
		self.makeSettings(self.settingsSizer)
		self.Thaw()

	def updateCurrentKey(self, key):
		self.apikeyTextCtrl.SetValue(key)

	def updateAccountInformation(self, account_name, password):
		self.accountTextCtrl.SetValue(account_name)
		self.passwordTextCtrl.SetValue(password)


class OpenAIKeySettingDialog(SettingsDialog):
	title = _("Set OpenAI Key")
	helpId = "SelectOpenAIKey"

	def makeSettings(self, settingsSizer):
		openaiTextLabel = wx.StaticText(self, label="OpenAI Key:")
		self.setOpenaiTextCtrl = wx.TextCtrl(
			self,
			size=(self.scaleSize(400), -1),
			value=config.conf["GPTAssistant"]["settings"]["openai_key"],
		)

		settingsSizer.Add(openaiTextLabel)
		settingsSizer.Add(self.setOpenaiTextCtrl)

	def onOk(self, evt):
		super().onOk(evt)
		self.Parent.updateCurrentKey(self.setOpenaiTextCtrl.GetValue())


class XXXAccountSettingDialog(SettingsDialog):
	title = _("Set XXX Account Information")
	helpId = "SetXXXAccountKey"

	def makeSettings(self, settingsSizer):
		accountTextLabel = wx.StaticText(self, label="Account Name:")
		self.setAccountTextCtrl = wx.TextCtrl(
			self,
			size=(self.scaleSize(300), -1),
			value=config.conf["GPTAssistant"]["settings"]["account_name"],
		)

		passwordTextLabel = wx.StaticText(self, label="Password:")
		self.setPasswordTextCtrl = wx.TextCtrl(
			self,
			size=(self.scaleSize(300), -1),
			value=config.conf["GPTAssistant"]["settings"]["password"],
		)

		settingsSizer.Add(accountTextLabel)
		settingsSizer.Add(self.setAccountTextCtrl)
		settingsSizer.Add(passwordTextLabel)
		settingsSizer.Add(self.setPasswordTextCtrl)

	def onOk(self, evt):
		super().onOk(evt)
		self.Parent.updateAccountInformation(
			self.setAccountTextCtrl.GetValue(),
			self.setPasswordTextCtrl.GetValue(),
		)
