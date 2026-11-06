import os
from concurrent.futures import Future
from types import SimpleNamespace

import addonHandler
import config
import gui
import ui
import wx
from gui import guiHelper, nvdaControls
from gui.contextHelp import ContextHelpMixin
from gui.settingsDialogs import SettingsPanel
from logHandler import log

from . import catalog_updater
from .catalog_url_dialog import CatalogUrlDialog
from .dictionary.dialog import DictionaryEntryDialog
from .lib.catalog import COSEEING_GROUP, is_dropped_issue, registry
from .lib.catalog.fallback import SENTINEL_ID
from .lib.catalog.selection import SelectionState
from .lib.coseeing_auth import (
	clean_coseeing_auth,
	has_saved_coseeing_refresh_token,
	start_coseeing_auth,
)
from .lib.llm import SUPPORTED_PROVIDERS
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
	# Translators: An item of the Language choice in the WordBridge settings panel.
	"zh_traditional": _("Traditional Chinese"),
	# Translators: An item of the Language choice in the WordBridge settings panel.
	"zh_simplified": _("Simplified Chinese"),
	# Translators: An item of the Correction Mode choice in the WordBridge settings panel.
	"standard": _("Standard"),
	# Translators: An item of the Correction Mode choice in the WordBridge settings panel.
	"lite": _("Lite"),
	# Translators: Name of the kind of account that uses the user's own API key for a provider.
	"personal_api_key": _("Personal API Key"),
	# Translators: Name of the kind of account that signs in to Coseeing.
	"coseeing_account": _("Coseeing Account"),
}
LANGUAGE_LABELS = [LABEL_DICT[value] for value in LANGUAGE_VALUES]
TYPO_CORRECTION_MODE_LABELS = [LABEL_DICT[value] for value in TYPO_CORRECTION_MODE_VALUES]

SOUND_EFFECTS_URL = "https://www.zapsplat.com/music/medium-underwater-movement-whoosh-pass-by-1/"

# Win32 combo box message: nonzero while the drop-down list is open. NVDA's
# source does not define it (retry spec F7).
CB_GETDROPPEDSTATE = 0x0157
# How often a deferred live update checks again whether it may run (10.2).
DEFERRED_UPDATE_POLL_MS = 300

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
	# Translators: The model label of the Coseeing default in the WordBridge settings panel's model choice.
	SENTINEL_ID: _("default"),
}

# Every account box the panel may ever show, in the order the catalog lists
# its groups (sorted local providers, Coseeing last). The set is fixed by
# code: a catalog offers no other provider (build_catalog drops them), so the
# panel creates all of them up front and a live update only shows, hides and
# relabels, keeping window, Tab and visual order the same (retry spec R13).
ACCOUNT_BOX_GROUPS = tuple(sorted(SUPPORTED_PROVIDERS)) + (COSEEING_GROUP,)


def catalog_status_message(status):
	"""The panel's status line for an updater status, or None (spec 13.3).

	It explains why the Service Provider list below may be short. The open
	panel keeps it up to date, and it is also the panel's accessible
	description (retry spec R11).
	"""
	if status is None:
		return None
	bundled = status.source == catalog_updater.SOURCE_BUNDLED
	if status.fetch == catalog_updater.FETCH_OFF:
		if bundled:
			# Translators: Status line in the WordBridge settings panel when the model list URL is empty, so the
			# model list that was included when the add-on was released is used.
			return _("The model list URL is empty, so WordBridge is using the model list that came with the add-on.")
		# Translators: Status line in the WordBridge settings panel when the model list URL is empty.
		return _("The model list URL is empty, so only the Coseeing default is available.")
	if status.fetch == catalog_updater.FETCH_INVALID:
		if bundled:
			# Translators: Status line in the WordBridge settings panel when the stored model list URL is not a valid
			# address, so the model list that was included when the add-on was released is used.
			return _("The model list URL is invalid, so WordBridge is using the model list that came with the add-on.")
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
	if bundled and status.fetch == catalog_updater.FETCH_FAILED:
		# Translators: Status line in the WordBridge settings panel when the model list could not be downloaded
		# and no copy was saved earlier, so the model list that was included when the add-on was released is used.
		return _("The model list could not be updated. WordBridge is using the model list that came with the add-on.")
	return None


# The sources whose list stays usable while a fetch fails: each has a
# "could not be updated" line, and none for its fetch in progress.
_STALE_SOURCES = (catalog_updater.SOURCE_CACHE, catalog_updater.SOURCE_BUNDLED)


def _stale_list_message(source):
	"""The "could not be updated ... WordBridge is using ..." line for `source`."""
	return catalog_status_message(
		catalog_updater.UpdaterStatus(source=source, fetch=catalog_updater.FETCH_FAILED)
	)


def _is_stale_list_message(message):
	return message is not None and any(message == _stale_list_message(source) for source in _STALE_SOURCES)


def _status_line_message(status, keep_stale):
	"""catalog_status_message(), except that `keep_stale` (a same-key refresh
	while the saved or the bundled list is in use) keeps the stale-list text
	for cache/running and bundled/running, which have none of their own. A
	failing retry then leaves the line as it is instead of hiding and
	showing it (C24)."""
	if (
		keep_stale
		and status is not None
		and status.source in _STALE_SOURCES
		and status.fetch == catalog_updater.FETCH_RUNNING
	):
		return _stale_list_message(status.source)
	return catalog_status_message(status)


def _announcement_text(outcome):
	"""What NVDA says after a live update of the open panel (R3)."""
	if outcome == catalog_updater.FETCH_SUCCEEDED:
		# Translators: Spoken when the open WordBridge settings panel has just shown a newly downloaded list of
		# providers and models.
		return _("Model list updated.")
	# Translators: Spoken when downloading the list of providers and models failed while the WordBridge settings
	# panel is open.
	return _("Model list update failed.")


def _dropped_entries_message(catalog):
	"""The panel's "N catalog entries could not be loaded" line, or None.

	Counting every issue would be a permanent false alarm: the shipped,
	fully healthy catalog always carries one "unreferenced_provider" lint
	issue. is_dropped_issue() keeps only what really failed to load; the
	log (__init__.py) still lists every issue.
	"""
	count = sum(1 for issue in catalog.issues if is_dropped_issue(issue))
	if count == 1:
		# Translators: Line in the WordBridge settings panel when one entry of the model list could not be loaded.
		return _("{count} catalog entry could not be loaded; see the NVDA log for details.").format(count=count)
	if count > 1:
		# Translators: Line in the WordBridge settings panel when several entries of the model list could not be loaded;
		# {count} is their number.
		return _("{count} catalog entries could not be loaded; see the NVDA log for details.").format(count=count)
	return None


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
		# Thread.start() can raise; the settings must still open (log the
		# type only, D15).
		try:
			retried = catalog_updater.retry_on_panel_open()
		except Exception as error:  # noqa: BLE001
			log.warning("WordBridge: catalog fetch on settings panel open failed type=%s", type(error).__name__)
			retried = False
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
		# A fetch R1 started from cache/failed keeps that line (C24).
		statusMessage = _status_line_message(catalog_updater.status(), keep_stale=retried)
		self._statusMessage = statusMessage
		self.catalogStatusText = settingsSizerHelper.addItem(wx.StaticText(self, label=statusMessage or ""))
		settingsSizer.Show(self.catalogStatusText, statusMessage is not None)
		self.panelDescription = statusMessage or ""

		# For selecting provider
		# Translators: Label of the choice of the service provider in the WordBridge settings panel.
		providerLabelText = _("Service Provider:")
		self.providerList = settingsSizerHelper.addLabeledControl(
			providerLabelText,
			wx.Choice,
			choices=[_provider_group_label(self.catalog, group) for group in self.catalog.provider_groups],
		)
		# Translators: Tooltip of the service provider choice in the WordBridge settings panel.
		self.providerList.SetToolTip(wx.ToolTip(_("Choose the service provider for the WordBridge")))
		self.providerList.Bind(wx.EVT_CHOICE, self.onChangeProviderChoice)
		self.providerList.SetSelection(self.selection.provider_group_index)

		# For selecting LLM
		# Translators: Label of the choice of the large language model in the WordBridge settings panel.
		modelLabelText = _("Large Language Model:")
		self.modelList = settingsSizerHelper.addLabeledControl(
			modelLabelText,
			wx.Choice,
			choices=list(_display_labels(self.catalog, self.selection.provider_group)),
		)
		# Translators: Tooltip of the large language model choice in the WordBridge settings panel.
		self.modelList.SetToolTip(wx.ToolTip(_("Choose the large language model for the Word Bridge")))
		self.modelList.SetSelection(self.selection.model_index)

		# For setting account information: a box for every provider the panel
		# may ever show, hidden unless selected (R13). Never created later.
		self.accountGroupSizerMap = {}
		self.accountTextCtrlMap = {}
		self._accountCaptions = {}
		self._shownAccountGroup = None
		for group in ACCOUNT_BOX_GROUPS:
			self._makeAccountBox(settingsSizerHelper, group)

		self._refreshAccountInfo()

		# For selecting language
		# Translators: Label of the choice of the correction language in the WordBridge settings panel.
		languageLabelText = _("Language:")
		self.languageList = settingsSizerHelper.addLabeledControl(
			languageLabelText,
			wx.Choice,
			choices=LANGUAGE_LABELS
		)
		# Translators: Tooltip of the language choice in the WordBridge settings panel.
		self.languageList.SetToolTip(wx.ToolTip(_("Choose the language for the Word Bridge")))
		self.languageList.SetSelection(LANGUAGE_VALUES.index(self.settings.language()))

		# For selecting typo correction mode
		# Translators: Label of the choice of the correction mode in the WordBridge settings panel.
		typoCorrectionModeLabelText = _("Correction Mode:")
		self.typoCorrectionModeList = settingsSizerHelper.addLabeledControl(
			typoCorrectionModeLabelText,
			wx.Choice,
			choices=TYPO_CORRECTION_MODE_LABELS
		)
		# Translators: Tooltip of the correction mode choice in the WordBridge settings panel.
		self.typoCorrectionModeList.SetToolTip(wx.ToolTip(_("Choose the typo correction mode for the Word Bridge")))
		self.typoCorrectionModeList.SetSelection(
			TYPO_CORRECTION_MODE_VALUES.index(self.settings.typo_correction_mode())
		)

		# For setting upper bound of correction character count
		# Translators: Label of the field for the largest number of characters WordBridge corrects at once.
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
			# Translators: Check box in the WordBridge settings panel: show the typo report after each correction.
			wx.CheckBox(self, label=_("Auto display typo report"))
		)
		self.autoDisplayReportEnable.SetValue(self.settings.auto_display_report())

		# A setting and its button share a group, as NVDA's "NVDA Development"
		# group; the controls keep their full labels, as NVDA's do.
		# For setting custom dictionary
		# Translators: Label of the group in the WordBridge settings panel holding the personal dictionary settings.
		dictionaryBox = self._addGroup(settingsSizerHelper, _("Personal dictionary"))
		self.customizedWordEnable = dictionaryBox.helper.addItem(
			# Translators: Check box in the WordBridge settings panel: use the user's own dictionary in corrections.
			wx.CheckBox(dictionaryBox.box, label=_("Apply personal dictionary"))
		)
		self.customizedWordEnable.SetValue(self.settings.customized_words_enable())

		self.wordDictionaryCtrl = dictionaryBox.helper.addItem(
			wx.Button(
				dictionaryBox.box,
				# Translators: Button in the WordBridge settings panel that opens the personal dictionary.
				label=_("Edit dictionary"),
			)
		)
		self.wordDictionaryCtrl.Bind(wx.EVT_BUTTON, self.onEditDictionary)

		# For setting sound effects
		# Translators: Label of the group in the WordBridge settings panel holding the sound effect settings.
		soundEffectsBox = self._addGroup(settingsSizerHelper, _("Sound effects"))
		self.soundEffectsEnable = soundEffectsBox.helper.addItem(
			# Translators: Check box in the WordBridge settings panel: play sounds while a correction runs.
			wx.CheckBox(soundEffectsBox.box, label=_("Enable sound effect cues"))
		)
		self.soundEffectsEnable.SetValue(self.settings.sound_effects_enable())

		self.soundEffectsCtrl = soundEffectsBox.helper.addItem(
			wx.Button(
				soundEffectsBox.box,
				# Translators: Button in the WordBridge settings panel that opens the web page crediting the sound effects.
				label=_("Sound effect credits"),
			)
		)
		self.soundEffectsCtrl.Bind(wx.EVT_BUTTON, self.onSoundEffects)

		# The last item, so every other control keeps its Tab position (RC
		# D16). As NVDA's update mirror group: a read-only box showing the URL
		# and a button opening the dialog that changes it (R12). An
		# ExpandoTextCtrl, because a read-only wx.TextCtrl takes no keyboard
		# focus (gui/settingsDialogs.py:944-949).
		from wx.lib.expando import ExpandoTextCtrl

		# Translators: Label of the group in the WordBridge settings panel showing the address the model list is
		# downloaded from.
		catalogUrlSizer = wx.StaticBoxSizer(wx.HORIZONTAL, self, label=_("Model list URL"))
		catalogUrlGroup = catalogUrlSizer.GetStaticBox()
		catalogUrlHelper = guiHelper.BoxSizerHelper(self, sizer=catalogUrlSizer)
		settingsSizerHelper.addItem(catalogUrlHelper)
		self.catalogUrlBox = ExpandoTextCtrl(catalogUrlGroup, size=(self.scaleSize(375), -1), style=wx.TE_READONLY)
		# Translators: Button in the model list URL group of the WordBridge settings panel that opens the dialog
		# changing the address.
		self.catalogUrlChangeButton = wx.Button(catalogUrlGroup, label=_("Change..."))
		catalogUrlHelper.addItem(guiHelper.associateElements(self.catalogUrlBox, self.catalogUrlChangeButton))
		self.catalogUrlBox.Bind(wx.EVT_CHAR_HOOK, self._onCatalogUrlBoxKey)
		self.catalogUrlChangeButton.Bind(wx.EVT_BUTTON, self.onChangeCatalogUrl)
		self._updateCatalogUrlBox()

		# R2: follow catalog changes while the panel exists (retry spec 10.1).
		self._pendingRebuild = False
		self._pendingAnnouncement = None
		self._deferTimer = None
		self._layoutPending = False
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
		self._applyPendingUpdate(change)

	def _applyPendingUpdate(self, change=None):
		"""Apply a notification's status line (when `change` is given) and a
		pending rebuild inside one Freeze, then send at most one layout event:
		each one scrolls the panel back to the top."""
		if not self:
			return
		deferred = self._mustDefer()
		rebuild = self._pendingRebuild and not deferred
		layoutChanged = False
		if change is not None or rebuild:
			self.Freeze()
			try:
				if change is not None:
					# Never focusable and never inside a drop-down: always now.
					layoutChanged = self._updateStatusLine(change)
					# The URL may have been saved since (C20).
					self._updateCatalogUrlBox()
				if rebuild:
					self._pendingRebuild = False
					layoutChanged = self._rebuild() or layoutChanged
			finally:
				self.Thaw()
		if layoutChanged:
			self._requestLayout()
		if deferred:
			# The announcement waits for the rebuild (spec 11, condition 4).
			if self._deferTimer is None:
				self._deferTimer = wx.CallLater(DEFERRED_UPDATE_POLL_MS, self._onDeferTimer)
			return
		timer, self._deferTimer = self._deferTimer, None
		if timer is not None:
			timer.Stop()
		outcome, self._pendingAnnouncement = self._pendingAnnouncement, None
		# Dropped, not kept, when the panel cannot speak now (spec 11).
		if outcome is not None and self._canAnnounce():
			# Default priority: queued behind what NVDA is saying.
			ui.message(_announcement_text(outcome))

	def _canAnnounce(self) -> bool:
		"""The WordBridge category is the one shown and the settings dialog is
		the active window (not another application, a message box or the URL
		dialog in front, C11, C20)."""
		try:
			return bool(self.IsShown() and self.GetTopLevelParent().IsActive())
		except Exception:  # noqa: BLE001
			return False

	def _onDeferTimer(self):
		self._deferTimer = None
		if not self:
			return
		self._applyPendingUpdate()

	def _mustDefer(self) -> bool:
		"""A pending rebuild waits while a choice's drop-down list is open
		(its items would change under the user) or while focus is in the
		shown account box and the rebuild would hide that box (retry spec
		10.2). Focus anywhere else stays where it is."""
		if not self._pendingRebuild:
			return False
		if self._isDroppedDown(self.providerList) or self._isDroppedDown(self.modelList):
			return True
		focus = self._findFocus()
		if focus is None:
			return False
		shown = self._shownAccountGroup
		control = self.coseeingCleanButton if shown == COSEEING_GROUP else self.accountTextCtrlMap.get(shown)
		if control is None or focus is not control:
			return False
		selection, _keptUserPick = self._chooseSelection(registry.current())
		return selection.provider_group != shown

	def _isDroppedDown(self, choice) -> bool:
		try:
			import winUser

			return winUser.sendMessage(choice.GetHandle(), CB_GETDROPPEDSTATE, 0, 0) != 0
		except Exception:  # noqa: BLE001
			return False

	def _findFocus(self):
		try:
			return wx.Window.FindFocus()
		except Exception:  # noqa: BLE001
			return None

	def _requestLayout(self) -> None:
		"""A layout event now, or a layout when the panel is shown again.

		NVDA answers the event by laying out and re-scrolling the container
		every category shares (gui/settingsDialogs.py:722-728), so one sent
		while another category is shown would scroll that category back to
		the top (batch-2 review I1)."""
		if self.IsShown():
			self._sendLayoutUpdatedEvent()
		else:
			self._layoutPending = True

	def onPanelActivated(self):
		super().onPanelActivated()
		# NVDA lays out the container on the switch back (_doCategoryChange);
		# the panel's own sizer only needs the layout a hidden update skipped.
		if getattr(self, "_layoutPending", False):
			self._layoutPending = False
			self.Layout()

	def _rebuild(self) -> bool:
		"""Replace the choices for the live catalog; True when the set of shown
		windows changed. Never moves focus and never shows the panel: it does
		not call onPanelActivated(), which is Show() (F2)."""
		new = registry.current()
		selection, keptUserPick = self._chooseSelection(new)
		baseline = self._storedBaseline(new)
		providerLabels = [_provider_group_label(new, group) for group in new.provider_groups]
		if self.providerList.GetItems() != providerLabels:
			self.providerList.SetItems(providerLabels)
		modelLabels = list(_display_labels(new, selection.provider_group))
		if self.modelList.GetItems() != modelLabels:
			self.modelList.SetItems(modelLabels)
		self.providerList.SetSelection(selection.provider_group_index)
		self.modelList.SetSelection(selection.model_index)
		# Only now that the choices show `new` (a wx failure above leaves the
		# panel's state matching its widgets, final review m3); the account
		# boxes below read self.catalog and self.selection.
		self._applyBaseline(baseline)
		self._keptUserPick = keptUserPick
		self.catalog = new
		self.selection = selection
		self._updateAccountCaptions()
		accountChanged = self._refreshAccountInfo()
		droppedChanged = self._setLine(self.catalogIssuesText, _dropped_entries_message(new))
		return accountChanged or droppedChanged

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

	def _updateStatusLine(self, change) -> bool:
		"""The status line and the accessible description (R11) from the
		updater's current status; True when the line appeared or vanished.
		A refresh that keeps the URL key keeps a shown stale-list line (C24)."""
		keepStale = not change.catalog_changed and _is_stale_list_message(self._statusMessage)
		message = _status_line_message(catalog_updater.status(), keep_stale=keepStale)
		self._statusMessage = message
		self.panelDescription = message or ""
		return self._setLine(self.catalogStatusText, message)

	def _accountCaption(self, group):
		# Translators: The end of an account box's caption in the WordBridge settings panel, after the provider name,
		# for example "OpenAI Authentication".
		return _provider_group_label(self.catalog, group) + " " + _("Authentication")

	def _addGroup(self, settingsSizerHelper, label):
		"""Append a labelled group. Its controls are children of `box`, so
		NVDA reads the group's label when focus enters it; `helper` is built
		on the box, so a labelled control it adds is one too (as NVDA's
		Magnifier panel)."""
		sizer = wx.StaticBoxSizer(wx.VERTICAL, self, label=label)
		box = sizer.GetStaticBox()
		helper = guiHelper.BoxSizerHelper(box, sizer=sizer)
		settingsSizerHelper.addItem(helper)
		return SimpleNamespace(sizer=sizer, box=box, helper=helper)

	def _makeAccountBox(self, settingsSizerHelper, group) -> None:
		"""Append the account box of `group` (makeSettings only, R13)."""
		caption = self._accountCaption(group)
		accountBox = self._addGroup(settingsSizerHelper, caption)
		accountGroupSizerHelper = accountBox.helper
		self.accountGroupSizerMap[group] = accountBox.sizer
		self._accountCaptions[group] = caption
		if group == COSEEING_GROUP:
			# Translators: Button in the Coseeing account box that signs out and removes the saved Coseeing sign-in.
			self.coseeingCleanButton = wx.Button(accountBox.box, label=_("clean"))
			self.coseeingCleanButton.Enable(has_saved_coseeing_refresh_token())
			self.coseeingCleanButton.Bind(wx.EVT_BUTTON, self.onCleanCoseeingAuth)
			accountGroupSizerHelper.addItem(self.coseeingCleanButton)
		else:
			self.accountTextCtrlMap[group] = accountGroupSizerHelper.addLabeledControl(
				# Translators: Label of the field for a provider's API key in the WordBridge settings panel.
				_("API Key:"),
				wx.TextCtrl,
				size=(self.scaleSize(375), -1),
				# Never api_key(): it would store "" for every unused provider.
				value=self.settings.stored_api_key(group),
			)

	def _updateAccountCaptions(self) -> None:
		"""Relabel the boxes for the live catalog, in place."""
		for group, box in self.accountGroupSizerMap.items():
			caption = self._accountCaption(group)
			if caption != self._accountCaptions.get(group):
				box.GetStaticBox().SetLabel(caption)
				self._accountCaptions[group] = caption

	def _refreshModelChoice(self):
		self.modelList.SetItems(list(_display_labels(self.catalog, self.selection.provider_group)))
		self.modelList.SetSelection(0)

	def _refreshAccountInfo(self) -> bool:
		"""Show only the selected group's box, including over boxes of groups
		the catalog does not offer (R13). True when the shown box changed."""
		shownGroup = self.selection.provider_group
		for group, box in self.accountGroupSizerMap.items():
			if group == shownGroup:
				self.settingsSizer.Show(box, recursive=True)
			else:
				self.settingsSizer.Hide(box, recursive=True)
		changed = shownGroup != self._shownAccountGroup
		self._shownAccountGroup = shownGroup
		return changed

	def onCleanCoseeingAuth(self, event) -> None:
		self.coseeingCleanButton.Disable()
		future = clean_coseeing_auth()
		future.add_done_callback(
			lambda done: wx.CallAfter(self._finishCleanCoseeingAuth, done)
		)

	def _finishCleanCoseeingAuth(self, done: Future[None]) -> None:
		try:
			done.result()
		except Exception:  # noqa: BLE001
			self.coseeingCleanButton.Enable(has_saved_coseeing_refresh_token())
		else:
			self.coseeingCleanButton.Enable(False)

	def onEditDictionary(self, event):
		gui.mainFrame.popupSettingsDialog(DictionaryEntryDialog)

	def onSoundEffects(self, event):
		def openfile():
			os.startfile(SOUND_EFFECTS_URL)
		wx.CallAfter(openfile)

	def _updateCatalogUrlBox(self) -> None:
		"""Show the stored URL; set only when it changed, so NVDA does not
		re-read an unchanged box."""
		# Translators: Shown in the model list URL group of the WordBridge settings panel when the URL is empty.
		value = self.settings.catalog_url() or _("No model list URL")
		if self.catalogUrlBox.GetValue() != value:
			self.catalogUrlBox.SetValue(value)

	def _onCatalogUrlBoxKey(self, evt):
		if evt.GetKeyCode() == wx.WXK_RETURN:
			self.onChangeCatalogUrl(evt)
		else:
			evt.Skip()

	def onChangeCatalogUrl(self, evt):
		"""Spec 20.1: the dialog saves the URL on its own OK; a saved change
		then switches and refreshes at once (D8, R10), like Apply used to."""
		dialog = CatalogUrlDialog(self, settings=self.settings, panel=self)
		if dialog.ShowModal() == wx.ID_OK and dialog.savedUrl is not None:
			catalog_updater.request_refresh(dialog.savedUrl)
		self._updateCatalogUrlBox()

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
		# What is shown is now what is stored (or still protected by D12), so
		# a later rebuild measures "touched" against this, not the baseline of
		# the panel's opening (final review I1, R4/R7). The D12 skip branch
		# saved nothing and recomputes the same baseline.
		self._applyBaseline(self._storedBaseline(self.catalog))
		self._keptUserPick = False
		self.settings.save_language(LANGUAGE_VALUES[self.languageList.GetSelection()])
		self.settings.save_typo_correction_mode(
			TYPO_CORRECTION_MODE_VALUES[self.typoCorrectionModeList.GetSelection()]
		)
		self.settings.save_max_char_count(self.maxCharCountSpinCtrl.GetValue())
		self.settings.save_auto_display_report(self.autoDisplayReportEnable.GetValue())
		self.settings.save_customized_words_enable(self.customizedWordEnable.GetValue())
		self.settings.save_sound_effects_enable(self.soundEffectsEnable.GetValue())

		# Only a key the user changed is written: an unused provider's empty
		# box adds no entry, and an untouched stored key stays as it is (R13).
		for group, control in self.accountTextCtrlMap.items():
			value = control.GetValue()
			if value != self.settings.stored_api_key(group):
				self.settings.save_api_key(group, value)

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
		# Translators: This is the label for the feedback dialog for Coseeing.
		super().__init__(parent, title=_("Feedback Coseeing"))
		mainSizer = wx.BoxSizer(wx.VERTICAL)
		sHelper = guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)

		# Here are text Controls for request, response and feedback. Only feedback can be editable.
		self.requestTextCtrl = sHelper.addLabeledControl(
			# Translators: Label of the read-only field with the text sent for correction in the Coseeing feedback dialog.
			_("Request:"),
			wx.TextCtrl,
			style=wx.TE_READONLY | wx.TE_MULTILINE,
			size=wx.Size(800, 70)
		)
		self.requestTextCtrl.SetValue(request)
		self.responseTextCtrl = sHelper.addLabeledControl(
			# Translators: Label of the read-only field with the corrected text in the Coseeing feedback dialog.
			_("Response:"),
			wx.TextCtrl,
			style=wx.TE_READONLY | wx.TE_MULTILINE,
			size=wx.Size(800, 70)
		)
		self.responseTextCtrl.SetValue(response)
		self.feedbackTextCtrl = sHelper.addLabeledControl(
			# Translators: Label of the field where the user writes feedback in the Coseeing feedback dialog.
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
