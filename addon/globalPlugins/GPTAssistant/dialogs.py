from wx.lib.expando import ExpandoTextCtrl

import config
import wx

from gui import guiHelper, nvdaControls
from gui.settingsDialogs import MultiCategorySettingsDialog, SettingsDialog, SettingsPanel


model_list = ["gpt-3.5-turbo", "text-davinci-003"]


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

		# For setting OpenAI API key
		keyLabel = _("&OpenAI Key")
		keyBoxSizer = wx.StaticBoxSizer(wx.HORIZONTAL, self, label=keyLabel)
		keyBox = keyBoxSizer.GetStaticBox()
		keyGroup = guiHelper.BoxSizerHelper(self, sizer=keyBoxSizer)
		settingsSizerHelper.addItem(keyGroup)

		self.keyNameCtrl = ExpandoTextCtrl(
			keyBox,
			size=(self.scaleSize(500), -1),
			value=config.conf["GPTAssistant"]["settings"]["openai_key"],
			style=wx.TE_READONLY,
		)
		self.keyNameCtrl.Bind(wx.EVT_CHAR_HOOK, self._enterTriggersOnChangeKey)

		changeKeyBtn = wx.Button(keyBox, label=_("C&hange..."))
		keyGroup.addItem(
			guiHelper.associateElements(
				self.keyNameCtrl,
				changeKeyBtn
			)
		)
		changeKeyBtn.Bind(wx.EVT_BUTTON, self.onChangeKey)

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

	def onSave(self):
		config.conf["GPTAssistant"]["settings"]["model"] = model_list[self.modelList.GetSelection()]
		config.conf["GPTAssistant"]["settings"]["openai_key"] = self.keyNameCtrl.GetValue()
		config.conf["GPTAssistant"]["settings"]["max_word_count"] = self.maxWordCount.GetValue()

	def _enterTriggersOnChangeKey(self, evt):
		if evt.KeyCode == wx.WXK_RETURN:
			self.onChangeKey(evt)
		else:
			evt.Skip()

	def onChangeKey(self, evt):
		changeDisplay = OpenAIKeySettingDialog(self, multiInstanceAllowed=True)
		ret = changeDisplay.ShowModal()
		if ret == wx.ID_OK:
			self.Freeze()
			# trigger a refresh of the settings
			self.onPanelActivated()
			self._sendLayoutUpdatedEvent()
			self.Thaw()

	def updateCurrentKey(self, key):
		self.keyNameCtrl.SetValue(key)


class GPTAssistantSettingsDialog(MultiCategorySettingsDialog):
	# translators: title of the dialog.
	dialogTitle = _("Settings")
	title = "% s - %s" % (_("GPT Assistant"), dialogTitle)
	INITIAL_SIZE = (1000, 480)
	MIN_SIZE = (470, 240)

	categoryClasses = [
		OpenAIGeneralSettingsPanel
	]

	def __init__(self, parent, initialCategory=None):
		super().__init__(parent, initialCategory)


class OpenAIKeySettingDialog(SettingsDialog):
	title = _("Set OpenAI Key")
	helpId = "SelectOpenAIKey"

	def makeSettings(self, settingsSizer):
		settingsSizerHelper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)

		keyLabel = _("&Key")
		keyBoxSizer = wx.StaticBoxSizer(wx.HORIZONTAL, self, label=keyLabel)
		keyBox = keyBoxSizer.GetStaticBox()
		keyGroup = guiHelper.BoxSizerHelper(self, sizer=keyBoxSizer)
		settingsSizerHelper.addItem(keyGroup)

		self.keyNameCtrl = ExpandoTextCtrl(
			keyBox,
			size=(self.scaleSize(250), -1),
			value=config.conf["GPTAssistant"]["settings"]["openai_key"],
		)

	def onOk(self, evt):
		super().onOk(evt)
		self.Parent.updateCurrentKey(self.keyNameCtrl.GetValue())
