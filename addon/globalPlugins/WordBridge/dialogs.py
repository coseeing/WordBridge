from configobj.validate import VdtValueTooBigError, VdtValueTooSmallError
from concurrent.futures import Future

import config
import os
import wx

import addonHandler

import gui
from gui import guiHelper, nvdaControls
from gui.contextHelp import ContextHelpMixin
from gui.settingsDialogs import SettingsPanel

from .dictionary.dialog import DictionaryEntryDialog
from .lib.catalog import registry
from .lib.catalog.selection import SelectionState
from .lib.coseeing_auth import (
	clean_coseeing_auth,
	has_saved_coseeing_refresh_token,
	start_coseeing_auth,
)
from .settings_repository import (
	LANGUAGE_VALUES,
	TYPO_CORRECTION_MODE_VALUES,
	SettingsRepository,
)

addonHandler.initTranslation()

# UI strings only. Model and provider display names live in the catalog now;
# sending them through here would make a future remote payload a channel for
# rewriting the interface's own wording.
LABEL_DICT = {
	"zh_traditional": _("Traditional Chinese"),
	"zh_simplified": _("Simplified Chinese"),
	"standard": _("Standard"),
	"lite": _("Lite"),
	"personal_api_key": _("Personal API Key"),
	"coseeing_account": _("Coseeing Account"),
}
LANGUAGE_LABELS = [LABEL_DICT[value] for value in LANGUAGE_VALUES]
TYPO_CORRECTION_MODE_LABELS = [LABEL_DICT[value] for value in TYPO_CORRECTION_MODE_VALUES]

SOUND_EFFECTS_URL = "https://www.zapsplat.com/music/medium-underwater-movement-whoosh-pass-by-1/"


class LLMSettingsPanel(SettingsPanel):
	title = _("WordBridge")
	helpId = "WordBridge Settings"

	def makeSettings(self, settingsSizer):
		settingsSizerHelper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)

		self.catalog = registry.current()
		self.settings = SettingsRepository(config.conf["WordBridge"]["settings"], registry.current)
		self.selection = SelectionState.restore(self.catalog, *self.settings.corrector_selection())

		# For selecting provider
		providerLabelText = _("Service Provider:")
		self.providerList = settingsSizerHelper.addLabeledControl(
			providerLabelText,
			wx.Choice,
			choices=list(self.catalog.provider_groups),
		)
		self.providerList.SetToolTip(wx.ToolTip(_("Choose the service provider for the WordBridge")))
		self.providerList.Bind(wx.EVT_CHOICE, self.onChangeProviderChoice)
		self.providerList.SetSelection(self.selection.provider_group_index)

		# For selecting LLM
		modelLabelText = _("Large Language Model:")
		self.modelList = settingsSizerHelper.addLabeledControl(
			modelLabelText,
			wx.Choice,
			choices=list(self.catalog.labels_for(self.selection.provider_group)),
		)
		self.modelList.SetToolTip(wx.ToolTip(_("Choose the large language model for the Word Bridge")))
		self.modelList.SetSelection(self.selection.model_index)

		# For setting account information
		self.accountGroupSizerMap = {}
		self.accountTextCtrlMap = {}
		for group in self.catalog.provider_groups:
			accountBoxSizer = wx.StaticBoxSizer(
				wx.VERTICAL,
				self,
				label=group + " " + _("Authentication")
			)
			self.accountGroupSizerMap[group] = accountBoxSizer
			self.accountGroupSizerHelper = guiHelper.BoxSizerHelper(self, sizer=accountBoxSizer)
			settingsSizerHelper.addItem(self.accountGroupSizerHelper)
			if group == "Coseeing":
				self.coseeingCleanButton = wx.Button(self, label=_("clean"))
				self.coseeingCleanButton.Enable(has_saved_coseeing_refresh_token())
				self.coseeingCleanButton.Bind(wx.EVT_BUTTON, self.onCleanCoseeingAuth)
				self.accountGroupSizerHelper.addItem(self.coseeingCleanButton)
				continue

			self.accountTextCtrlMap[group] = self.accountGroupSizerHelper.addLabeledControl(
				_("API Key:"),
				wx.TextCtrl,
				size=(self.scaleSize(375), -1),
				value=self.settings.api_key(group),
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
		self.languageList.SetSelection(LANGUAGE_VALUES.index(self.settings.language()))

		# For selecting typo correction mode
		typoCorrectionModeLabelText = _("Correction Mode:")
		self.typoCorrectionModeList = settingsSizerHelper.addLabeledControl(
			typoCorrectionModeLabelText,
			wx.Choice,
			choices=TYPO_CORRECTION_MODE_LABELS
		)
		self.typoCorrectionModeList.SetToolTip(wx.ToolTip(_("Choose the typo correction mode for the Word Bridge")))
		self.typoCorrectionModeList.SetSelection(
			TYPO_CORRECTION_MODE_VALUES.index(self.settings.typo_correction_mode())
		)

		# For setting upper bound of correction character count
		maxTokensLabelText = _("Max character count")
		# max_char_count() is a bare subscript (SettingsRepository is the sole
		# reader of the settings mapping), but the clamp bounds themselves
		# come from config.conf.getConfigValidation(), not from the settings
		# mapping -- so catching the validator's exceptions here, around the
		# repository call, keeps that read the settings mapping's only reader
		# without silently losing the clamp-to-bounds behaviour for an
		# out-of-range stored value.
		try:
			maxCharCount = self.settings.max_char_count()
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
		self.autoDisplayReportEnable.SetValue(self.settings.auto_display_report())

		# For setting custom dictionary
		self.customizedWordEnable = settingsSizerHelper.addItem(
			wx.CheckBox(self, label=_("Apply personal dictionary"))
		)
		self.customizedWordEnable.SetValue(self.settings.customized_words_enable())

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
		self.soundEffectsEnable.SetValue(self.settings.sound_effects_enable())

		self.soundEffectsCtrl = settingsSizerHelper.addItem(
			wx.Button(
				self,
				label=_("Sound effect credits"),
			)
		)
		self.soundEffectsCtrl.Bind(wx.EVT_BUTTON, self.onSoundEffects)

		self.settingsSizer = settingsSizer

	def _refreshModelChoice(self):
		self.modelList.SetItems(list(self.catalog.labels_for(self.selection.provider_group)))
		self.modelList.SetSelection(0)

	def _refreshAccountInfo(self):
		for group in self.catalog.provider_groups:
			if group == self.selection.provider_group:
				self.settingsSizer.Show(self.accountGroupSizerMap[group], recursive=True)
			else:
				self.settingsSizer.Hide(self.accountGroupSizerMap[group], recursive=True)

	def onCleanCoseeingAuth(self, event) -> None:
		self.coseeingCleanButton.Disable()
		future = clean_coseeing_auth()
		future.add_done_callback(
			lambda done: wx.CallAfter(self._finishCleanCoseeingAuth, done)
		)

	def _finishCleanCoseeingAuth(self, done: Future[None]) -> None:
		try:
			done.result()
		except Exception:
			self.coseeingCleanButton.Enable(has_saved_coseeing_refresh_token())
		else:
			self.coseeingCleanButton.Enable(False)

	def onEditDictionary(self, event):
		gui.mainFrame.popupSettingsDialog(DictionaryEntryDialog)

	def onSoundEffects(self, event):
		def openfile():
			os.startfile(SOUND_EFFECTS_URL)
		wx.CallAfter(openfile)

	def onSave(self):
		self.selection.provider_group_index = self.providerList.GetSelection()
		self.selection.model_index = self.modelList.GetSelection()
		selected_item = self.selection.current_item()
		self.settings.save_corrector_selection(
			selected_item.corrector_config_id, selected_item.execution_channel
		)
		self.settings.save_language(LANGUAGE_VALUES[self.languageList.GetSelection()])
		self.settings.save_typo_correction_mode(
			TYPO_CORRECTION_MODE_VALUES[self.typoCorrectionModeList.GetSelection()]
		)
		self.settings.save_max_char_count(self.maxCharCountSpinCtrl.GetValue())
		self.settings.save_auto_display_report(self.autoDisplayReportEnable.GetValue())
		self.settings.save_customized_words_enable(self.customizedWordEnable.GetValue())
		self.settings.save_sound_effects_enable(self.soundEffectsEnable.GetValue())

		for group, control in self.accountTextCtrlMap.items():
			self.settings.save_api_key(group, control.GetValue())

		wx.CallAfter(lambda: start_coseeing_auth(selected_item.execution_channel, silent=False))

	def onChangeProviderChoice(self, evt):
		self.selection.choose_provider_group(self.providerList.GetSelection())

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
