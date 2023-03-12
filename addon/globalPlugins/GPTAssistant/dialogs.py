from wx.lib.expando import ExpandoTextCtrl

import config
import wx

from gui import guiHelper, nvdaControls
from gui.settingsDialogs import MultiCategorySettingsDialog, NVDASettingsDialog, SettingsDialog, SettingsPanel


class OpenAIGeneralSettingsPanel(SettingsPanel):
	title = _("OpenAIGeneral")
	helpId = "OpenAIGeneralSettings"

	def makeSettings(self, settingsSizer):
		settingsSizerHelper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)
		modelLabelText = _("OpenAI Model:")
		choices=['text-davinci-003', 'text-curie-001', 'text-babbage-001', 'text-ada-001']
		self.modelList=settingsSizerHelper.addLabeledControl(modelLabelText, wx.Choice, choices=choices)
		self.modelList.SetToolTip(wx.ToolTip("Choose the openAI model for the GPT assistant"))
		self.modelList.SetSelection(0)
		#self.oldLanguage = config.conf["general"]["language"]
		#index = choices.index(self.oldLanguage)
		#self.languageList.SetSelection(index)

		keyLabel = _("&OpenAI Key")
		keyBoxSizer = wx.StaticBoxSizer(wx.HORIZONTAL, self, label=keyLabel)
		keyBox = keyBoxSizer.GetStaticBox()
		keyGroup = guiHelper.BoxSizerHelper(self, sizer=keyBoxSizer)
		settingsSizerHelper.addItem(keyGroup)

		self.keyNameCtrl = ExpandoTextCtrl(
			keyBox,
			size=(self.scaleSize(250), -1),
			value="",
			style=wx.TE_READONLY,
		)

		changeKeyBtn = wx.Button(keyBox, label=_("C&hange..."))
		self.bindHelpEvent("OpenAIKeyChange", self.keyNameCtrl)
		self.bindHelpEvent("OpenAIKeyChange", changeKeyBtn)
		keyGroup.addItem(
			guiHelper.associateElements(
				self.keyNameCtrl,
				changeKeyBtn
			)
		)
		changeKeyBtn.Bind(wx.EVT_BUTTON, self.onChangeKey)

		maxTokensLabelText = _("Max Tokens")
		maxTokensLowerBound = 25
		maxTokensUpperBound = 100
		self.maxTokensEdit = settingsSizerHelper.addLabeledControl(
			maxTokensLabelText,
			nvdaControls.SelectOnFocusSpinCtrl,
			min=maxTokensLowerBound,
			max=maxTokensUpperBound,
			initial=50
		)
		self.bindHelpEvent("GeneralSettingsMaxToken", self.maxTokensEdit)

		temperatureLabelText = _("Temperature")
		temperatureLowerBound = 25
		temperatureUpperBound = 100
		self.temperatureEdit = settingsSizerHelper.addLabeledControl(
			temperatureLabelText,
			nvdaControls.SelectOnFocusSpinCtrl,
			min=temperatureLowerBound,
			max=temperatureUpperBound,
			initial=50
		)
		self.bindHelpEvent("GeneralSettingsTemperature", self.temperatureEdit)

		topPLabelText = _("TopP")
		topPLowerBound = 25
		topPUpperBound = 100
		self.topPEdit = settingsSizerHelper.addLabeledControl(
			topPLabelText,
			nvdaControls.SelectOnFocusSpinCtrl,
			min=topPLowerBound,
			max=topPUpperBound,
			initial=50
		)
		self.bindHelpEvent("GeneralSettingsTopP", self.topPEdit)

	def onSave(self):
		pass
		#choices=['lsssssssssss1', 'lsssssssss2', 'l3sssssss']
		#print(f"config.getUserDefaultConfigPath() = {config.getUserDefaultConfigPath()}")
		#config.conf["general"]["language"] = choices[self.languageList.GetSelection()]

	def onChangeKey(self, evt):
		changeDisplay = OpenAIKeySettingDialog(self, multiInstanceAllowed=True)
		ret = changeDisplay.ShowModal()
		if ret == wx.ID_OK:
			self.Freeze()
			# trigger a refresh of the settings
			self.onPanelActivated()
			self._sendLayoutUpdatedEvent()
			self.Thaw()

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

		openAIAPIKeyLabelText = _("OpenAI Key")

		keyLabel = _("&Key")
		keyBoxSizer = wx.StaticBoxSizer(wx.HORIZONTAL, self, label=keyLabel)
		keyBox = keyBoxSizer.GetStaticBox()
		keyGroup = guiHelper.BoxSizerHelper(self, sizer=keyBoxSizer)
		settingsSizerHelper.addItem(keyGroup)

		self.keyNameCtrl = ExpandoTextCtrl(
			keyBox,
			size=(self.scaleSize(250), -1),
			value="",
			style=wx.TE_READONLY,
		)