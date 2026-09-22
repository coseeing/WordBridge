import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import os
import threading
import time

PATH = os.path.dirname(__file__)
PACKAGE_PATH = os.path.join(PATH, "package")

# Installing the sandbox must precede every _wb_vendor import below, and it
# replaces the sys.path injection that used to expose package/ to the whole
# NVDA process.  See lib/vendor.py.
from .lib import vendor

vendor.install(vendor.default_roots(PACKAGE_PATH))
# cryptography cannot live behind the prefix -- its Rust extension resolves
# Python types by absolute module name -- so it is shadowed under its canonical
# name instead.  This must run before anything imports it, directly or through
# _wb_vendor.jwt / _wb_vendor.joserfc.  See SHADOWED in lib/vendor.py.
try:
	_SHADOWED, _SHADOW_EVICTED, _SHADOW_SKIPPED = vendor.install_shadowed(
		vendor.default_roots(PACKAGE_PATH)
	)
except Exception as _shadow_install_error:
	_SHADOWED, _SHADOW_EVICTED = [], []
	_SHADOW_SKIPPED = [f"install_shadowed: {type(_shadow_install_error).__name__}"]
# install_stdlib_gapfill() no longer raises (spec:270), but a defensive guard
# stays here too: it is called before `log` exists (see below), so a failure
# recorded in _STDLIB_GAPFILL_FAILURES is logged once the NVDA log module is
# available, instead of ever taking the add-on down at this line.
try:
	_STDLIB_GAPFILL_REGISTERED, _STDLIB_GAPFILL_FAILURES = vendor.install_stdlib_gapfill(PACKAGE_PATH)
except Exception as _stdlib_gapfill_install_error:
	_STDLIB_GAPFILL_REGISTERED = []
	_STDLIB_GAPFILL_FAILURES = [("install_stdlib_gapfill", _stdlib_gapfill_install_error)]

import addonHandler
import api
import config
from configobj.validate import VdtValueTooBigError, VdtValueTooSmallError
import globalPluginHandler
import gui
from logHandler import log
import nvwave
from scriptHandler import script
import textInfos
from tones import beep
import ui
import wx

import requests

from .dialogs import CORRECTOR_CONFIG_ID_DEFAULT, EXECUTION_CHANNEL_DEFAULT, LANGUAGE_DEFAULT, TYPO_CORRECTION_MODE_DEFAULT, configManager
from .dialogs import LLMSettingsPanel, FeedbackDialog
from .configManager import load_corrector_task_config, normalize_selection
from .dictionary import WBW_DICTIONARY_PATH
from .dictionary.dialog import DictionaryEntryDialog
from .lib.application.task_runner import run_typo_correction
from .lib.coseeing import build_coseeing_headers
from .lib import coseeing_auth
from .lib.coseeing_auth import shutdown_coseeing_auth, start_coseeing_auth
from .lib.decimalUtils import decimal_to_str_0
from .lib.report import generate_report
from .lib.tasks.typo.utils import strings_diff
from _wb_vendor.hanzidentifier import has_chinese


DEBUG_MODE = False
addonHandler.initTranslation()
ADDON_SUMMARY = "WordBridge"

# Make the unavailable-auth reason observable: without this, the auth half
# can fail to load with nothing in NVDA's log to diagnose it from. Only the
# exception type and str(error) that unavailable_reason() already formats are
# logged -- never _AUTH_IMPORT_ERROR itself or exc_info=True, either of which
# would add a traceback (and, for a SyntaxError, arbitrary source text) to the
# log. unavailable_reason() does deliberately include the sandbox roots
# (_wb_vendor.__path__), and on Windows that is the add-on install path --
# hence the Windows username. That's kept in because it's what distinguishes
# "the runtime bundle is missing" from "the bundle is present but a module
# failed to load"; the two are otherwise byte-identical, and without the path
# the message would not be actionable.
if not coseeing_auth.AUTH_AVAILABLE:
	log.warning(coseeing_auth.unavailable_reason())

# The shadow is what keeps Coseeing login working, and when it stands down it
# does so silently -- so say so once, at load, rather than leaving a later
# TypeError deep in PyJWT as the only evidence.
if _SHADOW_SKIPPED:
	log.warning(
		"WordBridge: vendored packages not shadowed under their canonical names: %s"
		" -- Coseeing authentication will not work on this runtime",
		", ".join(_SHADOW_SKIPPED),
	)
elif _SHADOW_EVICTED:
	log.debug("WordBridge: shadowed %s, evicted %s", ", ".join(_SHADOWED), ", ".join(_SHADOW_EVICTED))

# Same privacy rule as above: only the exception type and str(error) for each
# gap-fill failure are logged, never a traceback.
for _gapfill_name, _gapfill_error in _STDLIB_GAPFILL_FAILURES:
	log.warning(
		"WordBridge: stdlib gap-fill module failed to load name=%s type=%s: %s",
		_gapfill_name, type(_gapfill_error).__name__, _gapfill_error,
	)

CORRECTOR_TASK_CONFIG_PATH = os.path.join(PATH, "setting", "task", "corrector.json")
correctorTaskConfig = load_corrector_task_config(CORRECTOR_TASK_CONFIG_PATH)

config.conf.spec["WordBridge"] = {
	"settings": {
		"corrector_config_id": f"string(default={CORRECTOR_CONFIG_ID_DEFAULT})",
		"execution_channel": f"string(default={EXECUTION_CHANNEL_DEFAULT})",
		"language": f"string(default={LANGUAGE_DEFAULT})",
		"typo_correction_mode": f"string(default={TYPO_CORRECTION_MODE_DEFAULT})",
		"api_key": {},
		"max_char_count": "integer(default=512,min=256,max=4096)",
		"auto_display_report": "boolean(default=False)",
		"customized_words_enable": "boolean(default=True)",
		"sound_effects_enable": "boolean(default=True)",
	}
}
COSEEING_BASE_URL = "https://wordbridge.coseeing.org"
# COSEEING_BASE_URL = "http://localhost:8000"
# Connect fast, but keep the read budget: a proofreading request is proxied to
# an LLM. Shutdown responsiveness comes from terminate()'s own budget, not from
# shortening this.
COSEEING_CONNECT_TIMEOUT = 10
COSEEING_READ_TIMEOUT = 120
COSEEING_TIMEOUT = (COSEEING_CONNECT_TIMEOUT, COSEEING_READ_TIMEOUT)
# terminate() must not wait for an in-flight request. Workers are daemons, so
# whatever is still running when this budget expires is abandoned.
TERMINATE_WAIT_SECONDS = 3


def get_coseeing_access_token(*, reconsider_guest=False):
	return coseeing_auth.get_coseeing_access_token(reconsider_guest=reconsider_guest)


@dataclass(frozen=True)
class CorrectionAction:
	request: str | None = None
	response: str | None = None
	diff: list | None = None
	interaction_id: str | None = None


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		gui.settingsDialogs.NVDASettingsDialog.categoryClasses.append(LLMSettingsPanel)
		self._shutdown = threading.Event()
		settings = config.conf["WordBridge"]["settings"]
		_, channel, _ = normalize_selection(
			configManager,
			settings["corrector_config_id"],
			settings["execution_channel"],
		)
		wx.CallAfter(self._start_coseeing_auth, channel)
		self.latest_action = CorrectionAction()
		self.correct_typo_thread = None
		self._feedback_thread = None

	def _start_coseeing_auth(self, channel):
		if not self._shutdown.is_set():
			start_coseeing_auth(channel)

	def terminate(self, *args, **kwargs):
		# R02: terminate() must never raise. Each step below is isolated in
		# its own try/except so that a failure in one step cannot skip the
		# steps after it -- in particular shutdown_coseeing_auth(), the
		# categoryClasses removal (which would otherwise leak the settings
		# panel for the rest of the NVDA session) and super().terminate()
		# must all still run. Every caught exception is logged with a
		# traceback rather than swallowed. The finally must run even when the
		# wait loop raises something except Exception does not catch, such
		# as a KeyboardInterrupt.
		self._shutdown.set()
		deadline = time.monotonic() + TERMINATE_WAIT_SECONDS
		try:
			workers = [
				self.correct_typo_thread,
				self._feedback_thread,
			]
			for worker in workers:
				if worker is None or not worker.is_alive():
					continue
				remaining = deadline - time.monotonic()
				if remaining <= 0:
					break
				worker.join(timeout=remaining)
			if any(worker is not None and worker.is_alive() for worker in workers):
				log.warning(
					"WordBridge: background work still running after %s seconds, abandoning it",
					TERMINATE_WAIT_SECONDS,
				)
		except Exception:
			log.exception("WordBridge: error while waiting for background work to finish during terminate()")
		finally:
			try:
				shutdown_coseeing_auth()
			except Exception:
				log.exception("WordBridge: shutdown_coseeing_auth() failed during terminate()")
			try:
				categoryClasses = gui.settingsDialogs.NVDASettingsDialog.categoryClasses
				if LLMSettingsPanel in categoryClasses:
					categoryClasses.remove(LLMSettingsPanel)
			except Exception:
				log.exception("WordBridge: removing LLMSettingsPanel failed during terminate()")
			try:
				super().terminate(*args, **kwargs)
			except Exception:
				log.exception("WordBridge: super().terminate() failed")

	def _run_on_ui(self, function, *args):
		if self._shutdown.is_set():
			return
		def deliver():
			if self._shutdown.is_set():
				return
			function(*args)
		try:
			wx.CallAfter(deliver)
		except Exception:
			return

	def _notify(self, message):
		self._run_on_ui(ui.message, message)

	def _report_cost(self, cost):
		try:
			# The Coseeing channel hands back cost as a plain JSON int/float
			# (data.json()["cost"]); the local channel already hands back a
			# Decimal (Executor.get_total_cost()). Coercing here, in the one
			# place both channels converge, means decimal_to_str_0() -- which
			# rejects non-Decimal input outright -- never sees anything but a
			# Decimal, from either channel. str() first avoids the
			# binary-float artefact Decimal(0.1) would produce.
			cost = cost if isinstance(cost, Decimal) else Decimal(str(cost))
			cost_text = decimal_to_str_0(cost)
		except (TypeError, ValueError, InvalidOperation) as error:
			# Never fabricate a zero and never hide the cause: the user is
			# told the number is unavailable, the log says why.
			log.warning(
				"WordBridge: could not format the task cost type=%s: %s",
				type(error).__name__,
				error,
			)
			self._notify(_("This task's cost is unavailable."))
			return
		self._notify(_("This task costs {cost} USD.").format(cost=cost_text))
		log.info(_("This task costs {cost} USD.").format(cost=cost_text))

	def _publish_latest_action(self, action):
		# Sole writer of self.latest_action. Must only ever be invoked via
		# self._run_on_ui(self._publish_latest_action, ...), so it always runs
		# on the UI thread -- this is what makes a single self.latest_action
		# read on the UI thread internally consistent (request/response/
		# interaction_id all from the same task) without needing a lock.
		#
		# THE NAME IS LOAD-BEARING: this must NOT be called _set_latest_action.
		# GlobalPlugin inherits NVDA's baseObject.AutoPropertyObject, whose
		# AutoPropertyType metaclass turns every `_get_x`/`_set_x`/`_del_x`
		# method in the class body into a property `x`:
		#     props = {n[5:] for n in namespace if n[0:5] in ("_get_","_set_","_del_")}
		# With a `_set_latest_action` method, `self.latest_action = action`
		# below stops being an attribute store and becomes a call back into
		# this same method -- unbounded recursion, triggered on the very first
		# write in __init__. NVDA wedges during global plugin initialization
		# with no traceback, which takes the whole screen reader down.
		self.latest_action = action

	def _post_coseeing_request(self, url, **kwargs):
		if self._shutdown.is_set():
			return None
		kwargs.setdefault("timeout", COSEEING_TIMEOUT)
		response = requests.post(url, **kwargs)
		if self._shutdown.is_set():
			return None
		return response

	def onSettings(self, evt):
		wx.CallAfter(
			gui.mainFrame.popupSettingsDialog,
			gui.settingsDialogs.NVDASettingsDialog,
			LLMSettingsPanel
		)

	def OnPreview(self, file):
		def openfile():
			os.startfile(file)
		self._run_on_ui(openfile)

	def showReport(self, diff_data):
		try:
			report_path = generate_report(diff_data)
		except OSError as error:
			log.warning("WordBridge: could not generate the report: %s: %s", type(error).__name__, error)
			self._notify(_("The correction report could not be generated."))
			return
		self.OnPreview(str(report_path))

	def getSelectedText(self):
		obj = api.getFocusObject()
		text = obj.makeTextInfo(textInfos.POSITION_SELECTION).text
		return text

	def isTextValid(self, text):
		try:
			max_char_count = config.conf["WordBridge"]["settings"]["max_char_count"]
		except VdtValueTooBigError:
			max_char_count = int(config.conf.getConfigValidation(
				("WordBridge", "settings", "max_char_count")
			).kwargs["max"])
		except VdtValueTooSmallError:
			max_char_count = int(config.conf.getConfigValidation(
				("WordBridge", "settings", "max_char_count")
			).kwargs["min"])
		if len(text) > max_char_count:
			ui.message(
				_("The number of characters is {len_text}, which exceeds the maximum, {max_char_count}.").format(
					len_text=len(text),
					max_char_count=max_char_count
				)
			)
			log.warning(
				_("The number of characters is {len_text}, which exceeds the maximum, {max_char_count}.").format(
					len_text=len(text),
					max_char_count=max_char_count
				)
			)
			return False
		elif len(text) == 0:
			ui.message(_("No text is selected, unable to analyze."))
			log.warning(_("No text is selected, unable to analyze."))
			return False
		elif not has_chinese(text):
			ui.message(_("The selected text does not contain Chinese characters, unable to analyze."))
			log.warning(_("The selected text does not contain Chinese characters, unable to analyze."))
			return False

		return True

	def readDictionary(self):
		dictionary_path = os.path.join(WBW_DICTIONARY_PATH, "data.csv")
		if not os.path.exists(dictionary_path):
			open(dictionary_path, 'w', encoding='utf-8').close()
		with open(dictionary_path, encoding='utf8', newline='') as csvfile:
			reader = csv.DictReader(csvfile)
			word_list = list(reader)
		return word_list

	def isNVDASettingsDialogCreate(self):
		create_state = gui.settingsDialogs.NVDASettingsDialog.DialogState.CREATED
		for dlg, state in gui.settingsDialogs.NVDASettingsDialog._instances.items():
			if isinstance(dlg, gui.settingsDialogs.NVDASettingsDialog) and state == create_state:
				return True
		return False

	def correctTypo(self, request):
		corrector_config_id = config.conf["WordBridge"]["settings"]["corrector_config_id"]
		execution_channel = config.conf["WordBridge"]["settings"]["execution_channel"]
		corrector_config_id, execution_channel, corrector_config = normalize_selection(
			configManager,
			corrector_config_id,
			execution_channel,
		)

		language = config.conf["WordBridge"]["settings"]["language"]
		corrector_mode = config.conf["WordBridge"]["settings"]["typo_correction_mode"]

		provider = corrector_config.provider
		model_name = corrector_config.model
		template_name = correctorTaskConfig.template_name[corrector_mode]
		optional_guidance_enable = correctorTaskConfig.optional_guidance_enable

		if config.conf["WordBridge"]["settings"]["customized_words_enable"]:
			customized_words = [row["text"] for row in self.readDictionary()]
		else:
			customized_words = []
		if execution_channel == "local":
			if provider not in config.conf["WordBridge"]["settings"]["api_key"]:
				config.conf["WordBridge"]["settings"]["api_key"][provider] = ""
			credential = {
				"api_key": config.conf["WordBridge"]["settings"]["api_key"][provider],
			}

			try:
				batch_mode = not DEBUG_MODE
				result = run_typo_correction(
					request=request,
					batch_mode=batch_mode,
					provider_name=provider,
					model_name=model_name,
					credential=credential,
					language=language,
					template_name=template_name,
					corrector_mode=corrector_mode,
					optional_guidance_enable=optional_guidance_enable,
					customized_words=customized_words,
					retries=2,
					backoff=1,
				)
			except Exception as e:
				# The user has already been notified. Re-raising here only
				# leaves an unhandled exception in a worker thread, which
				# lands in the NVDA log with nothing to act on.
				self._notify(_("Sorry, an error occurred during the program execution, the details are: {e}").format(e=e))
				log.warning(_("Sorry, an error occurred during the program execution, the details are: {e}").format(e=e))
				return
			response = result.corrected_text
			interaction_id = None
			cost = result.cost
		else:
			if self._shutdown.is_set():
				return
			try:
				access_token = get_coseeing_access_token().result()
				headers = build_coseeing_headers(access_token)
			except Exception:
				self._notify(_("Sorry, an error occurred while authenticating with Coseeing."))
				return

			data = {
				"request": request,
				"corrector_config_id": corrector_config_id,
				"language": language,
				"typo_correction_mode": corrector_mode,
				"customized_words": customized_words,
			}
			try:
				data = self._post_coseeing_request(f"{COSEEING_BASE_URL}/proofreader", headers=headers, json=data)
			except Exception as error:
				timeout_type = getattr(getattr(requests, "exceptions", None), "Timeout", None)
				message = (
					_("The Coseeing request timed out. Please try again later.")
					if timeout_type is not None and isinstance(error, timeout_type)
					else _("The Coseeing request failed. Please try again later.")
				)
				self._notify(message)
				return
			if data is None or self._shutdown.is_set():
				return
			if data.status_code == 401:
				self._notify(_("Authentication error. Please sign in to Coseeing or check your account permissions."))
				return
			elif data.status_code == 429:
				self._notify(
					_("Rate limit reached for requests or you exceeded your current quota. ") +\
					_("Please reduce the frequency of sending requests or check your account balance.")
				)
				return
			elif data.status_code >= 400:
				self._notify(_("The Coseeing request failed. Please try again later."))
				return
			try:
				result = data.json()
				response = result["response"]
				interaction_id = result["interaction_id"]
				cost = result["cost"]
			except (ValueError, KeyError, TypeError):
				self._notify(_("The Coseeing response was invalid. Please try again later."))
				return

		diff = strings_diff(request, response)

		self._run_on_ui(self._publish_latest_action, CorrectionAction(
			request=request,
			response=response,
			diff=diff,
			interaction_id=interaction_id,
		))

		if request == response:
			self._notify(_("No errors in the selected text."))
			log.info(_("No errors in the selected text."))
			return

		self._run_on_ui(api.copyToClip, response)
		self._notify(_("The corrected text has been copied to the clipboard."))
		log.info(_("The corrected text has been copied to the clipboard."))

		self._report_cost(cost)

		if config.conf["WordBridge"]["settings"]["auto_display_report"]:
			self._run_on_ui(self.showReport, diff)

	def correctionAction(self, text):
		if self.correct_typo_thread and self.correct_typo_thread.is_alive():
			self._notify(_("Only one proofreading task can run at a time. Please wait until the current task has finished before starting another."))
			return

		self.correct_typo_thread = threading.Thread(target=self.correctTypo, args=(text,), daemon=True)
		self.correct_typo_thread.start()

		while self.correct_typo_thread.is_alive():
			if config.conf["WordBridge"]["settings"]["sound_effects_enable"]:
				nvwave.playWaveFile(
					os.path.join(os.path.dirname(__file__), "sounds", "zapsplat_nature_water_underwater_whoosh_movement_pass_med_designed_001_59240.wav"),
					asynchronous=False,
				)
				time.sleep(5)
			else:
				time.sleep(1)
				beep(261.6, 300)
				time.sleep(1)


		self.correct_typo_thread = None

	@script(
		gesture="kb:NVDA+alt+d",
		description=_("Open personal dictionary editor"),
		category=ADDON_SUMMARY,
	)
	def script_openCustomDictionary(self, gesture):
		gui.mainFrame.popupSettingsDialog(DictionaryEntryDialog)

	@script(
		gesture="kb:NVDA+alt+o",
		description=_("Execute typo correction"),
		category=ADDON_SUMMARY,
	)
	def script_correction(self, gesture):
		if self.isNVDASettingsDialogCreate():
			ui.message(
				_("The function cannot be executed. Please finish the configuration and close the setting window.")
			)
			log.warning(
				_("The function cannot be executed. Please finish the configuration and close the setting window.")
			)
			return

		text = self.getSelectedText()
		if not self.isTextValid(text):
			return
		action_thread = threading.Thread(target=self.correctionAction, args=(text,), daemon=True)
		action_thread.start()

	@script(
		gesture="kb:NVDA+alt+w",
		description=_("Open WordBridge settings"),
		category=ADDON_SUMMARY,
	)
	def script_openWordBridgeSettings(self, gesture):
		wx.CallAfter(
			gui.mainFrame.popupSettingsDialog,
			gui.settingsDialogs.NVDASettingsDialog,
			LLMSettingsPanel
		)

	@script(
		description=_("Show correction report"),
		category=ADDON_SUMMARY,
	)
	def script_showCorrectionReport(self, gesture):
		diff = self.latest_action.diff
		if diff is None:
			ui.message(_("No report has been generated yet."))
			log.warning(_("No report has been generated yet."))
			return

		self.showReport(diff)

	@script(
		gesture="kb:NVDA+alt+f",
		description=_("Submit correction feedback"),
		category=ADDON_SUMMARY,
	)
	def script_correctionFeedback(self, gesture):
		# Sample latest_action exactly once, here, before show() is scheduled.
		# ShowModal() below runs a nested wx event loop, which can deliver a
		# pending _publish_latest_action callback for a different, later task
		# while the dialog is open. Reading self.latest_action again after
		# ShowModal() returns would then attach this feedback to the wrong
		# interaction. The guard, the dialog and the POST must all close over
		# this one local instead.
		latest_action = self.latest_action
		if latest_action.interaction_id is None:
			ui.message(_("You have not run a typos correction task with the Coseeing service provider yet."))

			log.warning(_("You have not run a typos correction task with the Coseeing service provider yet."))
			return

		def show():
			if self._shutdown.is_set():
				return
			with FeedbackDialog(
				gui.mainFrame,
				latest_action.request,
				latest_action.response
			) as feedbackDialog:
				if feedbackDialog.ShowModal() != wx.ID_OK:
					return
				feedback_value = feedbackDialog.feedbackTextCtrl.GetValue()
				if not feedback_value:
					return
			# ShowModal() above runs a nested wx event loop, so terminate()
			# can be dispatched and run to completion while the dialog was
			# open. Re-check here, now that the dialog is closed, so a
			# feedback thread is not started after terminate() has already
			# joined the workers and shut auth down.
			if self._shutdown.is_set():
				return
			interaction_id = latest_action.interaction_id
			self._feedback_thread = threading.Thread(
				target=self._send_coseeing_feedback,
				args=(interaction_id, feedback_value),
				name="wordbridge-feedback",
				daemon=True,
			)
			self._feedback_thread.start()

		wx.CallAfter(show)

	def _send_coseeing_feedback(self, interaction_id, feedback_value):
		try:
			access_token = get_coseeing_access_token().result()
			headers = build_coseeing_headers(access_token)
		except Exception as error:
			message = _("The Coseeing authentication failed. Please try again later.")
			self._notify(message)
			return
		message = None
		try:
			response = self._post_coseeing_request(
				f"{COSEEING_BASE_URL}/feedback", headers=headers,
				json={"interaction_id": interaction_id, "review_content": feedback_value}
			)
			if response is None or self._shutdown.is_set():
				return
			if response.status_code == 401:
				message = _("Authentication error. Please sign in to Coseeing or check your account permissions.")
			elif response.status_code >= 400:
				message = _("Sorry, the Coseeing feedback request failed. Please try again later.")
			else:
				response.json()
		except Exception as error:
			timeout_type = getattr(getattr(requests, "exceptions", None), "Timeout", None)
			if timeout_type is not None and isinstance(error, timeout_type):
				message = _("The Coseeing feedback request timed out. Please try again later.")
			elif isinstance(error, ValueError):
				message = _("The Coseeing feedback response was invalid. Please try again later.")
			else:
				message = _("Sorry, the Coseeing feedback request failed. Please try again later.")
		if message is not None:
			self._notify(message)
