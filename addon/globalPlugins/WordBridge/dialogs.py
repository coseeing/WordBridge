from concurrent.futures import Future

import config
import os
import wx

import addonHandler

import gui
from gui import guiHelper, nvdaControls
from gui.contextHelp import ContextHelpMixin
from gui.settingsDialogs import SettingsPanel

from . import catalog_updater
from .dictionary.dialog import DictionaryEntryDialog
from .lib.catalog import COSEEING_GROUP, is_dropped_issue, registry
from .lib.catalog.fallback import SENTINEL_ID
from .lib.catalog.remote import validate_catalog_url
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

# lib/catalog must never reach _() (spec decision 9), so the sentinel's label
# ships plain -- SENTINEL_LABEL = "default" in lib/catalog/fallback.py
# -- and is the *only* catalog label that is not simply an identity mapping of
# a model or brand name; it is also, per spec decision 5, the default
# selection on every fresh install. Translating it here, keyed by the
# sentinel's corrector_config_id rather than by its text, is what keeps this
# from opening the door a remote payload rewriting the interface's own
# wording would be: the mapping is entirely client-side and keyed by an id
# the client itself defines, not by whatever string a catalog document
# happens to carry.
MODEL_LABEL_TRANSLATIONS = {
	SENTINEL_ID: _("default"),
}


def catalog_status_message(status):
	"""The panel's status line for an updater status, or None (spec 13.3).

	It explains why the Service Provider list below may be short. The open
	panel keeps it up to date, and it is also the panel's accessible
	description (retry spec R11).
	"""
	if status is None:
		return None
	if status.fetch == catalog_updater.FETCH_OFF:
		# Translators: Status line in the WordBridge settings panel when the model list URL is empty.
		return _("The model list URL is empty, so only the Coseeing default is available.")
	if status.fetch == catalog_updater.FETCH_INVALID:
		# Translators: Status line in the WordBridge settings panel when the stored model list URL is not a valid
		# address, so no model list was downloaded.
		return _("The model list URL is invalid, so no model list was loaded.")
	if status.source == catalog_updater.SOURCE_NONE and status.fetch == catalog_updater.FETCH_RUNNING:
		# Translators: Status line in the WordBridge settings panel while the model list is still being downloaded.
		return _("The model list is still loading. Until it loads, only the Coseeing default is available.")
	if status.source == catalog_updater.SOURCE_NONE and status.fetch == catalog_updater.FETCH_FAILED:
		# Translators: Status line in the WordBridge settings panel when the model list could not be downloaded
		# and no earlier copy is saved.
		return _(
			"The model list could not be loaded, so only the Coseeing default is available. See the NVDA log for details."
		)
	if status.source == catalog_updater.SOURCE_CACHE and status.fetch == catalog_updater.FETCH_FAILED:
		# Translators: Status line in the WordBridge settings panel when the model list could not be downloaded
		# and the copy saved earlier is used instead.
		return _("The model list could not be updated. WordBridge is using the list it saved earlier.")
	return None


def _dropped_entries_message(catalog):
	"""The panel's "N catalog entries could not be loaded" line, or None.

	Counting every issue would be a permanent false alarm: the shipped,
	fully healthy catalog always carries one "unreferenced_provider" lint
	issue. is_dropped_issue() keeps only what really failed to load; the
	log (__init__.py) still lists every issue.
	"""
	count = sum(1 for issue in catalog.issues if is_dropped_issue(issue))
	if count == 1:
		return _("{count} catalog entry could not be loaded; see the NVDA log for details.").format(count=count)
	if count > 1:
		return _("{count} catalog entries could not be loaded; see the NVDA log for details.").format(count=count)
	return None


def _url_identity(text):
	"""What "the URL changed" compares: the normalised key, or for an invalid
	value the text itself (an invalid and an empty URL both have no key)."""
	check = validate_catalog_url(text)
	return check.key if check.error is None else ("invalid", check.url)


def _display_labels(catalog, provider_group):
	"""labels_for(), with the sentinel's label passed through translation.

	Every other model/coseeing label passes through untouched -- see
	MODEL_LABEL_TRANSLATIONS's docstring for why only the sentinel is mapped.
	"""
	return tuple(
		MODEL_LABEL_TRANSLATIONS.get(item.corrector_config_id, item.label)
		for item in catalog.items_for(provider_group)
	)


def _provider_group_label(catalog, group):
	"""The caption for a provider group: its ProviderEntry.label when one
	exists (Task 2's oracle test proved every shipped provider label equals
	its key, so this changes nothing rendered today), falling back to the
	raw group name for groups with no provider entry -- Coseeing, by design.
	"""
	provider_entry = catalog.get_provider(group)
	return provider_entry.label if provider_entry is not None else group


class LLMSettingsPanel(SettingsPanel):
	# Translators: Title of the WordBridge category in NVDA's settings dialog; the add-on name.
	title = _("WordBridge")
	helpId = "WordBridge Settings"

	def makeSettings(self, settingsSizer):
		# R1: after a failed fetch, opening the panel fetches at once. First,
		# so the status read below already says "loading". makeSettings runs
		# once per settings dialog; switching categories does not fetch.
		catalog_updater.retry_on_panel_open()
		# NVDA's _buildGui has set this already; the live update needs it.
		self.settingsSizer = settingsSizer
		settingsSizerHelper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)

		self.catalog = registry.current()
		self.settings = SettingsRepository(config.conf["WordBridge"]["settings"], registry.current)
		# D12: remember whether the stored selection resolved as stored. One the
		# catalog cannot offer (offline with no model list, a retired model) is
		# shown as the default, but it is only overwritten if the user actually
		# changes the Service Provider or model choice. No stored channel has
		# nothing to protect: a fresh install, or an upgrader whose channel was
		# never written because it equalled 2026.9.3's default ("Coseeing";
		# NVDA does not store a value equal to the spec default). It counts as
		# resolved, so OK writes the shown default and starts the Coseeing
		# sign-in, as on main. A stored "local" channel keeps D12 and U7.
		baseline = self._storedBaseline(self.catalog)
		self._applyBaseline(baseline)
		self.selection = baseline[2]
		# C22: a pick the user made, kept by a live rebuild, is saved even when
		# it equals the recomputed baseline. Only _rebuild sets this.
		self._keptUserPick = False

		# The dropped-entries line (spec: "the settings panel shows a summary
		# line" when catalog entries failed to load) and the status line
		# explaining a short Service Provider list always exist, so their
		# place in the window order never changes; each is hidden while it
		# has nothing to say. Not in the Tab order; NVDA+B reads them. The
		# status is also the panel's accessible description (R11).
		droppedMessage = _dropped_entries_message(self.catalog)
		self.catalogIssuesText = settingsSizerHelper.addItem(wx.StaticText(self, label=droppedMessage or ""))
		settingsSizer.Show(self.catalogIssuesText, droppedMessage is not None)
		statusMessage = catalog_status_message(catalog_updater.status())
		self.catalogStatusText = settingsSizerHelper.addItem(wx.StaticText(self, label=statusMessage or ""))
		settingsSizer.Show(self.catalogStatusText, statusMessage is not None)
		self.panelDescription = statusMessage or ""

		# For selecting provider
		providerLabelText = _("Service Provider:")
		self.providerList = settingsSizerHelper.addLabeledControl(
			providerLabelText,
			wx.Choice,
			choices=[_provider_group_label(self.catalog, group) for group in self.catalog.provider_groups],
		)
		self.providerList.SetToolTip(wx.ToolTip(_("Choose the service provider for the WordBridge")))
		self.providerList.Bind(wx.EVT_CHOICE, self.onChangeProviderChoice)
		self.providerList.SetSelection(self.selection.provider_group_index)

		# For selecting LLM
		modelLabelText = _("Large Language Model:")
		self.modelList = settingsSizerHelper.addLabeledControl(
			modelLabelText,
			wx.Choice,
			choices=list(_display_labels(self.catalog, self.selection.provider_group)),
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
				label=_provider_group_label(self.catalog, group) + " " + _("Authentication")
			)
			self.accountGroupSizerMap[group] = accountBoxSizer
			self.accountGroupSizerHelper = guiHelper.BoxSizerHelper(self, sizer=accountBoxSizer)
			settingsSizerHelper.addItem(self.accountGroupSizerHelper)
			if group == COSEEING_GROUP:
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
		maxCharCountlowerBound, maxCharCountUpperBound = self.settings.max_char_count_bounds()
		maxCharCount = self.settings.max_char_count()
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

		# The last control, so every existing control keeps its Tab position.
		self.catalogUrlCtrl = settingsSizerHelper.addLabeledControl(
			# Translators: Label of the edit field for the web address the WordBridge model list is downloaded from.
			_("Model list URL:"),
			wx.TextCtrl,
			size=(self.scaleSize(375), -1),
			value=self.settings.catalog_url(),
		)
		self.catalogUrlCtrl.SetToolTip(wx.ToolTip(
			# Translators: Tooltip of the model list URL field in the WordBridge settings panel.
			_("The address WordBridge downloads the model list from. Leave it empty to use only the Coseeing default.")
		))

		# R2: follow catalog changes while the panel exists (retry spec 10.1).
		self._pendingRebuild = False
		self._pendingAnnouncement = None
		self._deferTimer = None
		catalog_updater.add_listener(self._onCatalogChange)
		# Destroy events bubble up from child windows, see _onPanelDestroy.
		self.Bind(wx.EVT_WINDOW_DESTROY, self._onPanelDestroy)

	def _onPanelDestroy(self, evt):
		if evt.GetEventObject() is self:
			catalog_updater.remove_listener(self._onCatalogChange)
			timer, self._deferTimer = self._deferTimer, None
			if timer is not None:
				timer.Stop()
		evt.Skip()

	def _onCatalogChange(self, change):
		"""Main thread: the updater's listener (retry spec 10.1)."""
		if not self:
			# The window is gone (OK destroys the dialog later, F5).
			catalog_updater.remove_listener(self._onCatalogChange)
			return
		if change.outcome == catalog_updater.FETCH_SUCCEEDED or (
			change.outcome == catalog_updater.FETCH_FAILED and change.user_initiated
		):
			# Only the latest speakable outcome is kept (C11); a background
			# failure is never spoken (R8) and leaves it as it is.
			self._pendingAnnouncement = change.outcome
		if change.catalog_changed:
			self._pendingRebuild = True
		if self._updateStatusLine():
			self._sendLayoutUpdatedEvent()
		self._applyPendingUpdate()

	def _applyPendingUpdate(self):
		if not self:
			return
		if self._pendingRebuild:
			self._pendingRebuild = False
			self.Freeze()
			try:
				layoutChanged = self._rebuild()
			finally:
				self.Thaw()
			if layoutChanged:
				self._sendLayoutUpdatedEvent()

	def _rebuild(self) -> bool:
		"""Replace the choices for the live catalog; True when the set of shown
		windows changed. Never moves focus and never shows the panel: it does
		not call onPanelActivated(), which is Show() (F2)."""
		new = registry.current()
		selection, keptUserPick = self._chooseSelection(new)
		self._applyBaseline(self._storedBaseline(new))
		self._keptUserPick = keptUserPick
		self.catalog = new
		self.selection = selection
		providerLabels = [_provider_group_label(new, group) for group in new.provider_groups]
		if self.providerList.GetItems() != providerLabels:
			self.providerList.SetItems(providerLabels)
		modelLabels = list(_display_labels(new, selection.provider_group))
		if self.modelList.GetItems() != modelLabels:
			self.modelList.SetItems(modelLabels)
		self.providerList.SetSelection(selection.provider_group_index)
		self.modelList.SetSelection(selection.model_index)
		return False

	def _storedBaseline(self, catalog) -> tuple:
		"""(stored, storedResolved, restored SelectionState) for `catalog`: the
		D12 rule, with the stored selection re-read from config (Apply may have
		written a new one since the panel opened)."""
		stored = self.settings.stored_corrector_selection()
		resolved = self.settings.corrector_selection(catalog=catalog)
		storedResolved = resolved == stored or not stored[1]
		return stored, storedResolved, SelectionState.restore(catalog, *resolved)

	def _applyBaseline(self, baseline) -> None:
		stored, storedResolved, restored = baseline
		self._storedSelection = stored
		self._storedSelectionResolved = storedResolved
		self._restoredIndices = (restored.provider_group_index, restored.model_index)

	def _chooseSelection(self, new) -> tuple:
		"""(SelectionState for `new`, whether it is a pick the user made here).

		R4 as read by C8 (R7): a selection the user made in this panel is
		kept if `new` still offers it; otherwise, and for an untouched panel,
		the stored selection as resolved in `new` (or its default).
		"""
		shown = (self.providerList.GetSelection(), self.modelList.GetSelection())
		touched = shown != self._restoredIndices or self._keptUserPick
		if touched and min(shown) >= 0:
			pick = self.catalog.get_item(*shown)
			indices = new.find_selection(pick.corrector_config_id, pick.execution_channel)
			if indices != (-1, -1):
				return SelectionState(new, *indices), True
		restored = self._storedBaseline(new)[2]
		return SelectionState(new, restored.provider_group_index, restored.model_index), False

	def _setLine(self, line, text) -> bool:
		"""Show `text` on a line, or hide the line without one. True when its
		visibility changed (the panel then needs a layout event)."""
		shown = bool(text)
		changed = shown != self.settingsSizer.IsShown(line)
		line.SetLabel(text or "")
		self.settingsSizer.Show(line, shown)
		return changed

	def _updateStatusLine(self) -> bool:
		"""The status line and the accessible description (R11) from the
		updater's current status; True when the line appeared or vanished."""
		message = catalog_status_message(catalog_updater.status())
		self.panelDescription = message or ""
		return self._setLine(self.catalogStatusText, message)

	def _refreshModelChoice(self):
		self.modelList.SetItems(list(_display_labels(self.catalog, self.selection.provider_group)))
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

	def isValid(self):
		check = validate_catalog_url(self.catalogUrlCtrl.GetValue())
		if check.error is not None:
			if check.error == "insecure_scheme":
				# Translators: Shown in NVDA's "Invalid configuration" message when the model list URL uses plain
				# http for a host other than this computer.
				message = _("The model list URL must start with https://. http:// is allowed only for localhost.")
			else:
				# Translators: Shown in NVDA's "Invalid configuration" message when the model list URL is not a
				# complete web address.
				message = _("Enter a complete web address, such as https://wordbridge.coseeing.org, or leave the field empty.")
			self._validationErrorMessageBox(
				message=message,
				# Translators: The option name in NVDA's "Invalid configuration" message; the model list URL label
				# without the colon.
				option=_("Model list URL"),
			)
			self.catalogUrlCtrl.SetFocus()
			return False
		return super().isValid()

	def onSave(self):
		self.selection.provider_group_index = self.providerList.GetSelection()
		self.selection.model_index = self.modelList.GetSelection()
		selected_item = self.selection.current_item()
		chosen = (self.selection.provider_group_index, self.selection.model_index)
		if self._storedSelectionResolved or chosen != self._restoredIndices or self._keptUserPick:
			self.settings.save_corrector_selection(
				selected_item.corrector_config_id, selected_item.execution_channel
			)
			signInChannel = selected_item.execution_channel
		else:
			# Nothing the user chose was saved, so their stored channel stands;
			# a stored local model must not trigger a Coseeing sign-in (U7).
			signInChannel = self._storedSelection[1]
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

		# Saved as typed (stripped), and only when it really changed, so an
		# untouched default never lands in nvda.ini. The refresh is deferred
		# past the dialog's save sequence, for OK and Apply alike.
		catalogUrl = self.catalogUrlCtrl.GetValue().strip()
		if _url_identity(catalogUrl) != _url_identity(self.settings.catalog_url()):
			self.settings.save_catalog_url(catalogUrl)
			wx.CallAfter(catalog_updater.request_refresh, catalogUrl)

		wx.CallAfter(lambda: start_coseeing_auth(signInChannel, silent=False))

	def onChangeProviderChoice(self, evt):
		self.selection.choose_provider_group(self.providerList.GetSelection())

		self.Freeze()
		# trigger a refresh of the settings
		self._refreshAccountInfo()
		self._refreshModelChoice()
		self.onPanelActivated()
		self._sendLayoutUpdatedEvent()
		self.Thaw()


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
