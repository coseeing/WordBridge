"""The "Set Model List URL" dialog (retry spec R12, section 20).

It mirrors NVDA's update mirror dialog (gui/_SetURLDialog.py) without using
that private class: the URL is checked and saved on this dialog's OK, not
on the settings dialog's OK/Apply.
"""

import gui
import wx

import addonHandler
from gui import guiHelper
from gui.settingsDialogs import SettingsDialog

from .lib.catalog.remote import validate_catalog_url

addonHandler.initTranslation()

TEST_UNTESTED, TEST_PASSED, TEST_FAILED = "untested", "passed", "failed"


def url_identity(text):
	"""What "the URL changed" compares: the normalised key, or for an invalid
	value the text itself (an invalid and an empty URL both have no key)."""
	check = validate_catalog_url(text)
	return check.key if check.error is None else ("invalid", check.url)


def invalid_url_message(error: str) -> str:
	"""The message for a validate_catalog_url() error."""
	if error == "insecure_scheme":
		# Translators: Shown when the model list URL uses plain http for a host other than this computer.
		return _("The model list URL must start with https://. http:// is allowed only for localhost.")
	# Translators: Shown when the model list URL is not a complete web address.
	return _("Enter a complete web address, such as https://wordbridge.coseeing.org, or leave the field empty.")


class CatalogUrlDialog(SettingsDialog):
	# Translators: Title of the dialog that changes the address the WordBridge model list is downloaded from.
	title = _("Set Model List URL")
	helpId = "WordBridge Settings"

	def __init__(self, parent, *, settings, panel):
		self._settings = settings
		self._panel = panel
		# The URL this dialog saved, or None; read after ShowModal().
		self.savedUrl = None
		self.testStatus = TEST_UNTESTED
		super().__init__(parent)

	def makeSettings(self, settingsSizer):
		settingsSizerHelper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)
		self.urlCtrl = settingsSizerHelper.addLabeledControl(
			# Translators: Label of the edit field for the web address the WordBridge model list is downloaded from.
			_("Model list URL:"),
			wx.TextCtrl,
			size=(self.scaleSize(375), -1),
			value=self._settings.catalog_url(),
		)
		self.urlCtrl.SetToolTip(wx.ToolTip(
			# Translators: Tooltip of the model list URL field in the WordBridge settings panel.
			_("The address WordBridge downloads the model list from. Leave it empty to use only the Coseeing default.")
		))
		# Translators: Button next to the model list URL field that checks whether the address offers a model list.
		self.testButton = wx.Button(self, label=_("&Test..."))
		guiHelper.BoxSizerHelper(self, sizer=self.urlCtrl.GetContainingSizer()).addItem(self.testButton)
		self.urlCtrl.Bind(wx.EVT_TEXT, self._onTextChange)
		self._updateTestButton()

	def postInit(self):
		self.urlCtrl.SetFocus()

	def _updateTestButton(self):
		self.testButton.Enable(bool(self.urlCtrl.GetValue().strip()))

	def _onTextChange(self, evt):
		"""A test applies only to the text it tested (C21)."""
		self.testStatus = TEST_UNTESTED
		self._updateTestButton()

	def onOk(self, evt):
		"""Spec 20.2: validate, compare, warn when not tested, save, then close."""
		text = self.urlCtrl.GetValue().strip()
		check = validate_catalog_url(text)
		if check.error is not None:
			self._showError(invalid_url_message(check.error))
			self.urlCtrl.SetFocus()
			return
		if url_identity(text) == url_identity(self._settings.catalog_url()):
			super().onOk(evt)
			return
		if text and self.testStatus != TEST_PASSED:
			answer = self._askSaveAnyway(self.testStatus == TEST_FAILED)
			if answer == gui.message.ReturnCode.NO:
				super().onOk(evt)
				return
			if answer != gui.message.ReturnCode.YES:
				return
		self._settings.save_catalog_url(text)
		self.savedUrl = text
		# Before closing, so NVDA does not report the old value when focus
		# returns to the box (gui/_SetURLDialog.py:127-129).
		self._panel._updateCatalogUrlBox()
		super().onOk(evt)

	def _showError(self, message):
		# Translators: Title of the message shown when the model list URL is not valid.
		gui.message.MessageDialog.alert(message, _("Error"), self)

	def _askSaveAnyway(self, failed):
		"""Yes saves, No closes without saving, Cancel (the default and the
		Escape answer) returns to this dialog."""
		if failed:
			# Translators: Asked when the user saves a model list URL whose test failed.
			message = _("The model list URL failed the test. Save it anyway?")
		else:
			# Translators: Asked when the user saves a model list URL that was not tested.
			message = _("The model list URL has not been tested. Save it without testing it first?")
		dialog = gui.message.MessageDialog(
			self,
			message,
			# Translators: Title of the question asked before saving a model list URL that did not pass the test.
			_("Warning"),
			dialogType=gui.message.DialogType.WARNING,
			buttons=gui.message.DefaultButtonSet.YES_NO_CANCEL,
		)
		dialog.setDefaultFocus(gui.message.ReturnCode.CANCEL)
		dialog.SetEscapeId(gui.message.ReturnCode.CANCEL)
		return dialog.ShowModal()
