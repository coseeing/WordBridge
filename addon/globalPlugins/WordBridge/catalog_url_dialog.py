"""The "Set Model List URL" dialog (retry spec R12, section 20).

It mirrors NVDA's update mirror dialog (gui/_SetURLDialog.py) without using
that private class: the URL is checked and saved on this dialog's OK, not
on the settings dialog's OK/Apply.
"""

import threading

import addonHandler
import gui
import wx
from gui import guiHelper
from gui.settingsDialogs import SettingsDialog

from . import catalog_updater
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
	return _(
		# Translators: Shown when the model list URL is not a complete web address.
		"Enter a complete web address, such as https://wordbridge.coseeing.org, or leave the field empty.",
	)


def _start_probe_thread(target, args):
	"""Run the URL test off the UI thread (a seam for tests). A daemon, so an
	unanswered request never holds NVDA's exit; its result is dropped when
	the dialog is gone (C21)."""
	thread = threading.Thread(target=target, args=args, name="wordbridge-catalog-url-test", daemon=True)
	thread.start()
	return thread


def _failure_tip(result) -> str:
	if result.kind == "network":
		# Translators: Part of the message after a failed test of the model list URL: a network error.
		return _("There was a network error. Check that you are connected to the internet and try again.")
	if result.kind == "http_status":
		# Translators: Part of the message after a failed test of the model list URL; {status} is the HTTP
		# status code the server answered with, for example 404.
		return _("The server answered with HTTP status {status}. Check that the URL is correct.").format(
			status=result.detail,
		)
	if result.kind == "not_a_list":
		# Translators: Part of the message after a failed test of the model list URL: the address answered,
		# but not with a model list.
		return _("The server's answer is not a WordBridge model list. Check that the URL is correct.")
	if result.kind == "no_models":
		# Translators: Part of the message after a failed test of the model list URL: the list has no usable model.
		return _("The model list offers no model WordBridge can use.")
	# Translators: Part of the message after a failed test of the model list URL, for any other failure.
	return _("Make sure you are connected to the internet and the URL is correct.")


def probe_result_message(result) -> str:
	"""The message shown after "Test..." for a ProbeResult (spec 20.5)."""
	if result.kind == "ok":
		if result.models == 1:
			# Translators: Shown after a successful test of the model list URL; {count} is the number of models (1).
			text = _("The model list loaded. It offers {count} model.")
		else:
			# Translators: Shown after a successful test of the model list URL; {count} is the number of models.
			text = _("The model list loaded. It offers {count} models.")
		return text.format(count=result.models)
	# Translators: Shown after a failed test of the model list URL; {tip} says what went wrong and what to do.
	return _("The model list URL failed the test. {tip}").format(tip=_failure_tip(result))


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
		self.urlCtrl.SetToolTip(
			wx.ToolTip(
				_(
					# Translators: Tooltip of the model list URL field in the WordBridge settings panel.
					"The address WordBridge downloads the model list from. Leave it empty to use only the Coseeing default.",
				),
			),
		)
		# Translators: Button next to the model list URL field that checks whether the address offers a model list.
		self.testButton = wx.Button(self, label=_("&Test..."))
		guiHelper.BoxSizerHelper(self, sizer=self.urlCtrl.GetContainingSizer()).addItem(self.testButton)
		self.testButton.Bind(wx.EVT_BUTTON, self._onTest)
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

	def _onTest(self, evt):
		"""Spec 20.3: validate first (no request for an invalid URL), then
		probe the text off the UI thread behind a progress dialog."""
		text = self.urlCtrl.GetValue().strip()
		check = validate_catalog_url(text)
		if check.error is not None:
			self._showError(invalid_url_message(check.error))
			self.urlCtrl.SetFocus()
			return
		self._progress = gui.IndeterminateProgressDialog(
			self,
			title=self.title,
			# Translators: Shown while WordBridge tests the model list URL.
			message=_("Validating the model list URL..."),
		)
		_start_probe_thread(self._runProbe, (text,))

	def _runProbe(self, text):
		"""Probe thread: the normal fetch and checks, nothing installed or cached."""
		wx.CallAfter(self._onProbeDone, text, catalog_updater.probe_url(text))

	def _onProbeDone(self, text, result):
		"""Main thread. The status changes only if the field still holds the
		tested text (C21); the message is shown either way."""
		if not self:
			return
		progress, self._progress = getattr(self, "_progress", None), None
		if progress is not None:
			progress.done()
		ok = result.kind == "ok"
		if self.urlCtrl.GetValue().strip() == text:
			self.testStatus = TEST_PASSED if ok else TEST_FAILED
		self._showResult(probe_result_message(result), ok)

	def _showResult(self, message, ok):
		if ok:
			# Translators: Title of the message after a successful test of the model list URL.
			gui.message.MessageDialog.alert(message, _("Success"), self)
		else:
			# Translators: Title of the message after a failed test of the model list URL.
			self._showErrorMessage(message, _("Error"))

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
		self._showErrorMessage(message, _("Error"))

	def _showErrorMessage(self, message, caption):
		"""An OK-only message with NVDA's error icon and sound, as NVDA's
		_SetURLDialog shows its failure (wx.ICON_ERROR). Main thread."""
		gui.message.MessageDialog(
			self,
			message,
			caption,
			dialogType=gui.message.DialogType.ERROR,
			buttons=(gui.message.DefaultButton.OK,),
		).ShowModal()

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
