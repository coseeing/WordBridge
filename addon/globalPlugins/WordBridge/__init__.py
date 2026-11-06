import os
import threading
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

PATH = os.path.dirname(__file__)
PACKAGE_PATH = os.path.join(PATH, "package")

# Installing the sandbox must precede every _wb_vendor import below, and it
# replaces the sys.path injection that used to expose package/ to the whole
# NVDA process.  See lib/vendor.py.
from .lib import vendor

vendor.install(vendor.default_roots(PACKAGE_PATH))
# cryptography is NVDA's own copy -- a second one in the process breaks NVDA
# Remote (see HOST_ONLY in lib/vendor.py) -- with the six files NVDA's build
# omits filled in behind it.  Must run before _wb_vendor.joserfc is imported,
# which lib/coseeing_auth below does transitively.  Never raises.
_CRYPTOGRAPHY_GAPFILL_INSTALLED = vendor.install_cryptography_gapfill(PACKAGE_PATH)
# install_stdlib_gapfill() no longer raises (spec:270), but a defensive guard
# stays here too: it is called before `log` exists (see below), so a failure
# recorded in _STDLIB_GAPFILL_FAILURES is logged once the NVDA log module is
# available, instead of ever taking the add-on down at this line.
try:
	_STDLIB_GAPFILL_REGISTERED, _STDLIB_GAPFILL_FAILURES = vendor.install_stdlib_gapfill(PACKAGE_PATH)
except Exception as _stdlib_gapfill_install_error:  # noqa: BLE001
	_STDLIB_GAPFILL_REGISTERED = []
	_STDLIB_GAPFILL_FAILURES = [("install_stdlib_gapfill", _stdlib_gapfill_install_error)]

import addonHandler
import api
import config
import globalPluginHandler
import gui
import nvwave
import requests
import textInfos
import ui
import wx
from _wb_vendor.hanzidentifier import has_chinese
from logHandler import log
from scriptHandler import script
from tones import beep

from . import catalog_updater
from .catalog_updater import CatalogUpdater
from .configManager import CorrectorTaskConfig, load_corrector_task_config
from .dialogs import FeedbackDialog, LLMSettingsPanel
from .dictionary import default_dictionary_repository
from .dictionary.dialog import DictionaryEntryDialog
from .lib import coseeing_auth
from .lib.application.task_runner import run_typo_correction
from .lib.catalog import COSEEING_GROUP, LOCAL_CHANNEL, registry
from .lib.catalog.cache import CatalogCache
from .lib.catalog.fallback import SENTINEL_ID
from .lib.catalog.remote import DEFAULT_CATALOG_URL, loggable
from .lib.catalog.sources import BundledCatalogSource
from .lib.coseeing import build_coseeing_headers
from .lib.coseeing_auth import shutdown_coseeing_auth, start_coseeing_auth
from .lib.decimalUtils import decimal_to_str_0
from .lib.llm import SUPPORTED_PROVIDERS
from .lib.paths import user_workspace_root
from .lib.progress_cue import ProgressCue
from .lib.report import generate_report
from .lib.tasks.typo.utils import strings_diff
from .settings_repository import SettingsRepository

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

# Without the gap-fill, joserfc cannot import on NVDA's trimmed cryptography
# and the auth half reports itself unavailable above -- say why once, at load.
if not _CRYPTOGRAPHY_GAPFILL_INSTALLED:
	log.warning(
		"WordBridge: cryptography gap-fill not installed"
		" -- Coseeing authentication may not work on this runtime",
	)

# Same privacy rule as above: only the exception type and str(error) for each
# gap-fill failure are logged, never a traceback.
for _gapfill_name, _gapfill_error in _STDLIB_GAPFILL_FAILURES:
	log.warning(
		"WordBridge: stdlib gap-fill module failed to load name=%s type=%s: %s",
		_gapfill_name,
		type(_gapfill_error).__name__,
		_gapfill_error,
	)

CORRECTOR_TASK_CONFIG_PATH = os.path.join(PATH, "setting", "task", "corrector.json")

config.conf.spec["WordBridge"] = {
	"settings": {
		# Empty means "not chosen yet". SettingsRepository resolves it against
		# the catalog at read time, which is what keeps this spec -- evaluated
		# at import -- independent of the catalog.
		"corrector_config_id": "string(default='')",
		"execution_channel": "string(default='')",
		"language": "string(default='')",
		"typo_correction_mode": "string(default='')",
		"api_key": {},
		"max_char_count": "integer(default=512,min=256,max=4096)",
		"auto_display_report": "boolean(default=False)",
		"customized_words_enable": "boolean(default=True)",
		"sound_effects_enable": "boolean(default=True)",
		# Where the provider/model list is downloaded from. Empty turns the
		# remote catalog off: only the model list bundled with the add-on (and
		# the Coseeing default) is offered.
		"catalog_url": f"string(default='{DEFAULT_CATALOG_URL}')",
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
# Upper bound on a worker waiting for an access token. A browser login can
# legitimately take the whole callback window, so this only has to outlast it;
# it exists so a token future that is never settled cannot pin the worker.
COSEEING_TOKEN_WAIT_SECONDS = coseeing_auth.COSEEING_LOGIN_CALLBACK_TIMEOUT + 20
# terminate() must not wait for an in-flight request. Workers are daemons, so
# whatever is still running when this budget expires is abandoned.
TERMINATE_WAIT_SECONDS = 3

# The last accepted remote catalog. Beside the dictionary and the reports in
# the NVDA user configuration directory, so it survives add-on updates. Pure
# path arithmetic: nothing is created or read at import.
CATALOG_CACHE_PATH = user_workspace_root() / "catalog" / "remote-catalog.json"


def _can_write_catalog_cache():
	"""NVDA's own rule for disk writes: never from secure mode or the launcher.

	Imported lazily, like every NVDA module this file does not need at import;
	any failure means "do not write".
	"""
	try:
		import NVDAState

		return bool(NVDAState.shouldWriteToDisk())
	except Exception:  # noqa: BLE001
		return False


def _catalog_http_get(url, **kwargs):
	# Looked up on every call, so the requests module NVDA provides is the one
	# used (and tests can replace it).
	return requests.get(url, **kwargs)


def _schedule_catalog_retry(delay_ms, callback):
	# The catalog retry timer (retry spec section 7.3): wx.CallLater runs the
	# callback on the main thread. Looked up on every call, so tests can
	# replace it.
	return wx.CallLater(delay_ms, callback)


def _start_catalog_thread(target, args):
	return catalog_updater.start_daemon_thread(target, args)


# Progress cue cadence, preserved from the sleep-polling loop this replaced:
# the wave started immediately and repeated, the beep started after a beat.
CORRECTION_SOUND_PATH = os.path.join(
	os.path.dirname(__file__),
	"sounds",
	"zapsplat_nature_water_underwater_whoosh_movement_pass_med_designed_001_59240.wav",
)
SOUND_CUE_INTERVAL_MS = 5000
BEEP_CUE_INITIAL_DELAY_MS = 1000
BEEP_CUE_INTERVAL_MS = 2000
BEEP_CUE_HZ = 261.6
BEEP_CUE_MS = 300


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
		# Set before anything below that can fail, so a failure -- or the
		# fallback notification in _load_corrector_task_config() -- can
		# still safely use self._notify()/self._run_on_ui(), both of which
		# read self._shutdown.
		self._shutdown = threading.Event()
		# The repository only stores the registry accessor here; nothing reads
		# the catalog until registry.initialize() below.
		self.settings = SettingsRepository(config.conf["WordBridge"]["settings"], registry.current)
		# Bundled ⊕ the cache for the configured URL: one small file read on
		# the main thread, next to the bundled file read. The network fetch
		# itself is deferred to the fetch thread (see _start_catalog_fetch).
		self._catalog_updater = self._make_catalog_updater()
		catalog_updater.install(self._catalog_updater)
		self.catalog = self._catalog_updater.initial_catalog(self.settings.catalog_url())
		registry.initialize(self.catalog)
		self._log_catalog_issues(self.catalog)
		self.correctorTaskConfig = self._load_corrector_task_config()
		gui.settingsDialogs.NVDASettingsDialog.categoryClasses.append(LLMSettingsPanel)
		self._catalog_choice_pending = False
		_, channel = self.settings.corrector_selection()
		if self._needs_catalog_choice():
			# U7: the user chose a local model and there is no model list to
			# run it from. Only a Yes in the switch dialog moves them to
			# Coseeing, so no Coseeing sign-in starts on their behalf.
			channel = LOCAL_CHANNEL
		wx.CallAfter(self._start_coseeing_auth, channel)
		# Same deferral as the sign-in: it runs once the wx main loop starts
		# dispatching, which is after NVDA has finished starting -- and, unlike
		# core.postNvdaStartup, also when the plugin is reloaded.
		wx.CallAfter(self._start_catalog_fetch)
		self.latest_action = CorrectionAction()
		self.correct_typo_thread = None
		self._feedback_thread = None
		self._progress_cue = None
		self._degraded_catalog_announced = False

	def _load_corrector_task_config(self):
		try:
			return load_corrector_task_config(CORRECTOR_TASK_CONFIG_PATH)
		except Exception as error:  # noqa: BLE001
			# A damaged task config used to take the add-on's import down.
			# This must be total (bare Exception, not a specific tuple): a
			# malformed corrector.json can fail in more ways than OSError/
			# ValueError/KeyError -- a JSON document that parses but isn't a
			# mapping (a list, a string, a number, null) raises TypeError out
			# of raw_config["template_name"], which a narrower tuple let
			# through and took plugin construction down with it. load_catalog
			# next door (lib/catalog/fallback.py) already takes this same
			# total-catch approach for exactly this reason.
			log.warning(
				"WordBridge: could not load the corrector task config type=%s: %s",
				type(error).__name__,
				error,
			)
			# Deferred the same way _start_coseeing_auth is deferred below:
			# self._notify() -> self._run_on_ui() schedules the real
			# ui.message() call via wx.CallAfter() instead of calling it here,
			# synchronously, mid-construction, before NVDA's UI is ready for it.
			self._notify(
				_(
					"The bundled correction settings file is damaged; WordBridge is using its built-in defaults."
				)
			)
			return CorrectorTaskConfig(
				template_name={"standard": "Standard_v1.json", "lite": "Lite_v1.json"},
				optional_guidance_enable={"keep_non_chinese_char": True, "no_explanation": True},
			)

	def _start_coseeing_auth(self, channel):
		if not self._shutdown.is_set():
			start_coseeing_auth(channel)

	def _make_catalog_updater(self):
		return CatalogUpdater(
			bundled_source=BundledCatalogSource(os.path.join(PATH, "setting")),
			cache=CatalogCache(CATALOG_CACHE_PATH, can_write=_can_write_catalog_cache),
			runnable_providers=SUPPORTED_PROVIDERS,
			http_get=_catalog_http_get,
			post_to_ui=self._run_on_ui,
			install=self._install_catalog,
			shutdown=self._shutdown,
			log=log,
			start_thread=_start_catalog_thread,
			schedule=_schedule_catalog_retry,
		)

	def _start_catalog_fetch(self):
		# Starting the thread is the only work done here, on the main thread.
		if self._shutdown.is_set():
			return
		self._catalog_updater.refresh(self.settings.catalog_url())

	def _needs_catalog_choice(self):
		"""A stored local selection the live list cannot run, while no remote or
		cached catalog is loaded (U7).

		Without one, the live list is the add-on's bundled model list (or
		nothing at all). A stored local model on that list runs as usual; one
		missing from it -- e.g. a model a later remote catalog added -- needs
		the user's choice. Keyed on the raw stored selection:
		normalize_selection() would resolve it to the Coseeing default, which
		is exactly what must not happen without the user's say-so.
		"""
		status = catalog_updater.status()
		if status is None:
			# No updater installed (the plugin is not running).
			return False
		if status.source not in (catalog_updater.SOURCE_NONE, catalog_updater.SOURCE_BUNDLED):
			return False
		stored_id, stored_channel = self.settings.stored_corrector_selection()
		if stored_channel != LOCAL_CHANNEL:
			return False
		return registry.current().find_selection(stored_id, LOCAL_CHANNEL) == (-1, -1)

	def _ask_switch_to_coseeing(self, text):
		"""Main thread. Ask whether to switch a local user to the Coseeing default (U7).

		No is focused and is the Escape answer, so nothing is sent anywhere
		unless the user explicitly says Yes. The information comes first in
		the message, so NVDA reads it before the question when the dialog opens.
		"""
		try:
			if self._shutdown.is_set():
				return
			dialog = gui.message.MessageDialog(
				gui.mainFrame,
				# Translators: Message of a Yes/No dialog shown when the user starts a correction with a model
				# that uses their own API key, but the model list has not been downloaded. Yes switches the
				# setting to the Coseeing default and sends the text to Coseeing; No sends nothing.
				_(
					"The model list is not available yet, so the model you selected cannot be used.\n\n"
					"Switch to the Coseeing default and correct this text with Coseeing? "
					"Your WordBridge setting will be changed to the Coseeing default."
				),
				# Translators: Title of the Yes/No dialog asking whether to switch to the Coseeing default; the
				# add-on name.
				_("WordBridge"),
				buttons=gui.message.DefaultButtonSet.YES_NO,
			)
			dialog.setDefaultFocus(gui.message.ReturnCode.NO)
			dialog.SetEscapeId(gui.message.ReturnCode.NO)
			answer = dialog.ShowModal()
		finally:
			self._catalog_choice_pending = False
		# ShowModal() runs a nested event loop, so terminate() may have run.
		if self._shutdown.is_set():
			return
		if answer == gui.message.ReturnCode.YES:
			# Always what the dialog said, even if the nested event loop
			# installed the model list meanwhile (decided by the user,
			# 2026-11-04; spec section 12.5).
			self.settings.save_corrector_selection(SENTINEL_ID, COSEEING_GROUP)
			self.startCorrection(text)
			return
		ui.message(self._catalog_choice_cancel_message())

	def _catalog_choice_cancel_message(self):
		# Translators: Spoken after the user answers No (or presses Escape) in the dialog asking whether to switch
		# to the Coseeing default because the model list is not available.
		return _("The text was not sent. Your model selection was not changed.")

	def _install_catalog(self, catalog):
		# Main thread only (the updater posts here through _run_on_ui), so the
		# settings panel's reads can never see two catalogs. A correction
		# already running keeps the snapshot it took (see correctTypo).
		registry.replace(catalog)
		self.catalog = catalog
		self._log_catalog_issues(catalog)

	def _log_catalog_issues(self, catalog):
		# location and detail can carry remote text (a provider name, a host):
		# escaped and bounded, so it can never forge a log line.
		for issue in catalog.issues:
			log.warning(
				"WordBridge: catalog issue code=%s location=%s: %s",
				issue.code,
				loggable(issue.location),
				loggable(issue.detail),
			)

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
		try:
			self._stop_progress_cue()
		except Exception:
			log.exception("WordBridge: stopping the progress cue failed during terminate()")
		deadline = time.monotonic() + TERMINATE_WAIT_SECONDS
		try:
			updater = getattr(self, "_catalog_updater", None)
			workers = [
				self.correct_typo_thread,
				self._feedback_thread,
				# A fetch blocked in a socket read cannot be interrupted; it is
				# a daemon, and it can neither write the cache nor post once
				# _shutdown is set, so abandoning it is safe.
				updater.thread if updater is not None else None,
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
				catalog_updater.uninstall()
			except Exception:
				log.exception("WordBridge: catalog_updater.uninstall() failed during terminate()")
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
		except Exception:  # noqa: BLE001
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
		log.info(f"This task costs {cost_text} USD.")

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
			gui.mainFrame.popupSettingsDialog, gui.settingsDialogs.NVDASettingsDialog, LLMSettingsPanel
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
		max_char_count = self.settings.max_char_count()
		if len(text) > max_char_count:
			ui.message(
				_(
					"The number of characters is {len_text}, which exceeds the maximum, {max_char_count}."
				).format(len_text=len(text), max_char_count=max_char_count)
			)
			log.warning(
				f"The number of characters is {len(text)}, which exceeds the maximum, {max_char_count}."
			)
			return False
		elif len(text) == 0:
			ui.message(_("No text is selected, unable to analyze."))
			log.warning("No text is selected, unable to analyze.")
			return False
		elif not has_chinese(text):
			ui.message(_("The selected text does not contain Chinese characters, unable to analyze."))
			log.warning("The selected text does not contain Chinese characters, unable to analyze.")
			return False

		return True

	def readDictionary(self):
		return default_dictionary_repository().load()

	def isNVDASettingsDialogCreate(self):
		create_state = gui.settingsDialogs.NVDASettingsDialog.DialogState.CREATED
		for dlg, state in gui.settingsDialogs.NVDASettingsDialog._instances.items():
			if isinstance(dlg, gui.settingsDialogs.NVDASettingsDialog) and state == create_state:
				return True
		return False

	def correctTypo(self, request):
		# One snapshot for the whole correction: the catalog can be swapped on
		# the main thread while this worker runs, and resolving the selection
		# against one catalog and looking it up in another could make
		# get_model() miss an id that was just resolved.
		catalog = registry.current()
		if self._needs_catalog_choice():
			# script_correction() asks first; this only guards a correction that
			# reached here some other way. A stored local model must never be
			# resolved to Coseeing behind the user's back (U7).
			self._notify(self._catalog_choice_cancel_message())
			return
		corrector_config_id, execution_channel = self.settings.corrector_selection(catalog=catalog)

		language = self.settings.language()
		corrector_mode = self.settings.typo_correction_mode()
		template_name = self.correctorTaskConfig.template_name[corrector_mode]
		optional_guidance_enable = self.correctorTaskConfig.optional_guidance_enable

		if self.settings.customized_words_enable():
			customized_words = [row["text"] for row in self.readDictionary()]
		else:
			customized_words = []
		if catalog.degraded and not self._degraded_catalog_announced:
			# Notify before marking announced: _run_on_ui() silently drops the
			# message when self._shutdown is already set, and the old order
			# (flag first) could mark this session's one-shot announcement
			# "delivered" even when it never reached the user.
			self._notify(_("The model list could not be loaded. Coseeing will choose a model for you."))
			self._degraded_catalog_announced = True
		if execution_channel == LOCAL_CHANNEL:
			model_entry = catalog.get_model(corrector_config_id)
			if model_entry is None:
				self._notify(
					_(
						"The selected model is no longer available. Please choose another one in WordBridge settings."
					)
				)
				return
			provider_entry = catalog.get_provider(model_entry.provider)
			if provider_entry is None:
				self._notify(
					_(
						"The selected provider is no longer available. Please choose another one in WordBridge settings."
					)
				)
				return
			credential = {"api_key": self.settings.api_key(model_entry.provider)}

			try:
				batch_mode = not DEBUG_MODE
				result = run_typo_correction(
					request=request,
					batch_mode=batch_mode,
					provider_name=model_entry.provider,
					model_name=model_entry.model,
					credential=credential,
					provider_entry=provider_entry,
					price_entry=model_entry.price_entry(),
					language=language,
					template_name=template_name,
					corrector_mode=corrector_mode,
					optional_guidance_enable=optional_guidance_enable,
					customized_words=customized_words,
					retries=2,
					backoff=1,
				)
			except Exception as e:  # noqa: BLE001
				# The user has already been notified. Re-raising here only
				# leaves an unhandled exception in a worker thread, which
				# lands in the NVDA log with nothing to act on.
				self._notify(
					_("Sorry, an error occurred during the program execution, the details are: {e}").format(
						e=e
					)
				)
				log.warning(f"Sorry, an error occurred during the program execution, the details are: {e}")
				return
			response = result.corrected_text
			diff = result.diff
			interaction_id = None
			cost = result.cost
		else:
			if self._shutdown.is_set():
				return
			try:
				access_token = get_coseeing_access_token().result(timeout=COSEEING_TOKEN_WAIT_SECONDS)
				headers = build_coseeing_headers(access_token)
			except Exception:  # noqa: BLE001
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
				data = self._post_coseeing_request(
					f"{COSEEING_BASE_URL}/proofreader", headers=headers, json=data
				)
			except Exception as error:  # noqa: BLE001
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
				self._notify(
					_("Authentication error. Please sign in to Coseeing or check your account permissions.")
				)
				return
			elif data.status_code == 429:
				self._notify(
					_("Rate limit reached for requests or you exceeded your current quota. ")
					+ _("Please reduce the frequency of sending requests or check your account balance.")
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

		self._run_on_ui(
			self._publish_latest_action,
			CorrectionAction(
				request=request,
				response=response,
				diff=diff,
				interaction_id=interaction_id,
			),
		)

		if request == response:
			self._notify(_("No errors in the selected text."))
			log.info("No errors in the selected text.")
			return

		self._run_on_ui(api.copyToClip, response)
		self._notify(_("The corrected text has been copied to the clipboard."))
		log.info("The corrected text has been copied to the clipboard.")

		self._report_cost(cost)

		if self.settings.auto_display_report():
			self._run_on_ui(self.showReport, diff)

	def startCorrection(self, text):
		# UI THREAD ONLY. NVDA runs scripts on the main thread, so admission,
		# the worker handle and the progress cue all live here -- which is what
		# makes them safe without a lock, and what keeps the cue cancellable
		# from terminate(). The previous shape wrapped this in a second thread
		# purely to run a sleep-polling cue loop; that outer thread was in no
		# one's join list, so it outlived terminate().
		if self._shutdown.is_set():
			return
		if self.correct_typo_thread is not None and self.correct_typo_thread.is_alive():
			self._notify(
				_(
					"Only one proofreading task can run at a time. Please wait until the current task has finished before starting another."
				)
			)
			return

		self.correct_typo_thread = threading.Thread(target=self._run_correction, args=(text,), daemon=True)
		self.correct_typo_thread.start()
		self._progress_cue = self._make_progress_cue()
		self._progress_cue.start()

	def _run_correction(self, text):
		# Worker thread. The finally is what guarantees the cue stops even when
		# correctTypo() raises: without it a failed correction would leave the
		# cue sounding for the rest of the NVDA session.
		try:
			self.correctTypo(text)
		finally:
			self._run_on_ui(self._finish_correction)

	def _finish_correction(self):
		self._stop_progress_cue()
		self.correct_typo_thread = None

	def _stop_progress_cue(self):
		cue, self._progress_cue = self._progress_cue, None
		if cue is not None:
			cue.stop()

	def _make_progress_cue(self):
		if self.settings.sound_effects_enable():
			return ProgressCue(
				schedule=wx.CallLater,
				tick=self._play_correction_sound,
				interval_ms=SOUND_CUE_INTERVAL_MS,
				initial_delay_ms=0,
			)
		return ProgressCue(
			schedule=wx.CallLater,
			tick=lambda: beep(BEEP_CUE_HZ, BEEP_CUE_MS),
			interval_ms=BEEP_CUE_INTERVAL_MS,
			initial_delay_ms=BEEP_CUE_INITIAL_DELAY_MS,
		)

	def _play_correction_sound(self):
		# asynchronous=True is load-bearing now that this runs on the UI
		# thread: a blocking playback would freeze NVDA for the length of the
		# wave. In the old background-thread loop it only blocked that thread.
		nvwave.playWaveFile(CORRECTION_SOUND_PATH, asynchronous=True)

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
				_(
					"The function cannot be executed. Please finish the configuration and close the setting window."
				)
			)
			log.warning(
				"The function cannot be executed. Please finish the configuration and close the setting window."
			)
			return

		text = self.getSelectedText()
		if not self.isTextValid(text):
			return
		if self._needs_catalog_choice():
			if not self._catalog_choice_pending:
				self._catalog_choice_pending = True
				wx.CallAfter(self._ask_switch_to_coseeing, text)
			return
		self.startCorrection(text)

	@script(
		gesture="kb:NVDA+alt+w",
		description=_("Open WordBridge settings"),
		category=ADDON_SUMMARY,
	)
	def script_openWordBridgeSettings(self, gesture):
		wx.CallAfter(
			gui.mainFrame.popupSettingsDialog, gui.settingsDialogs.NVDASettingsDialog, LLMSettingsPanel
		)

	@script(
		description=_("Show correction report"),
		category=ADDON_SUMMARY,
	)
	def script_showCorrectionReport(self, gesture):
		diff = self.latest_action.diff
		if diff is None:
			ui.message(_("No report has been generated yet."))
			log.warning("No report has been generated yet.")
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

			log.warning("You have not run a typos correction task with the Coseeing service provider yet.")
			return

		def show():
			if self._shutdown.is_set():
				return
			with FeedbackDialog(
				gui.mainFrame, latest_action.request, latest_action.response
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
			access_token = get_coseeing_access_token().result(timeout=COSEEING_TOKEN_WAIT_SECONDS)
			headers = build_coseeing_headers(access_token)
		except Exception:  # noqa: BLE001
			message = _("The Coseeing authentication failed. Please try again later.")
			self._notify(message)
			return
		message = None
		try:
			response = self._post_coseeing_request(
				f"{COSEEING_BASE_URL}/feedback",
				headers=headers,
				json={"interaction_id": interaction_id, "review_content": feedback_value},
			)
			if response is None or self._shutdown.is_set():
				return
			if response.status_code == 401:
				message = _(
					"Authentication error. Please sign in to Coseeing or check your account permissions."
				)
			elif response.status_code >= 400:
				message = _("Sorry, the Coseeing feedback request failed. Please try again later.")
			else:
				response.json()
		except Exception as error:  # noqa: BLE001
			timeout_type = getattr(getattr(requests, "exceptions", None), "Timeout", None)
			if timeout_type is not None and isinstance(error, timeout_type):
				message = _("The Coseeing feedback request timed out. Please try again later.")
			elif isinstance(error, ValueError):
				message = _("The Coseeing feedback response was invalid. Please try again later.")
			else:
				message = _("Sorry, the Coseeing feedback request failed. Please try again later.")
		if message is not None:
			self._notify(message)
