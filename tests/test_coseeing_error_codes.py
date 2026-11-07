"""The add-on speaks a specific message for each Coseeing error code.

The server answers {"detail", "code"} (plus "limit" on length errors). A
missing or unknown code, or a body the add-on cannot use, falls back to
the status-based messages older servers get.

_load_nvda_plugin is imported at function scope, never at module scope
(see tests/test_coseeing_auth_nvda.py).
"""

import re
import threading
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
LOCALE = ROOT / "addon" / "locale"

FAILED = "The Coseeing request failed. Please try again later."
UNAUTHORIZED = "Authentication error. Please sign in to Coseeing or check your account permissions."
RATE_LIMITED = (
	"Rate limit reached for requests or you exceeded your current quota. "
	"Please reduce the frequency of sending requests or check your account balance."
)

# code -> (status, English message with {limit} filled as 128, zh_TW)
MESSAGES = {
	"guest_text_too_long": (
		413,
		"Guests can correct up to {limit} characters at a time. Sign in to Coseeing to correct longer text.",
		"訪客每次最多可校對 {limit} 字，登入 Coseeing 即可校對更長的文字。",
	),
	"text_too_long": (
		413,
		"The text is too long. Up to {limit} characters can be corrected at a time.",
		"文字過長，每次最多可校對 {limit} 字。",
	),
	"guest_quota_exceeded": (
		429,
		"Today's guest quota has been used up. Please try again later or sign in to Coseeing.",
		"今日訪客額度已用完，請稍後再試或登入 Coseeing。",
	),
	"user_quota_exceeded": (
		429,
		"Your Coseeing account's quota has been used up.",
		"您的 Coseeing 帳戶額度已用完。",
	),
	"model_unavailable": (
		422,
		"The selected model is currently unavailable. Please choose another model in the settings.",
		"所選的模型目前無法使用，請在設定中改選其他模型。",
	),
	"provider_overloaded": (
		502,
		"The AI service is currently overloaded. Please try again later.",
		"AI 服務目前過載，請稍後再試。",
	),
	"provider_rate_limited": (
		502,
		"Coseeing's AI service has reached its usage limit for now. Please try again later or choose another model.",
		"Coseeing 的 AI 服務暫時達到用量上限，請稍後再試或改選其他模型。",
	),
	"provider_unreachable": (
		502,
		"The AI service could not be reached. Please try again later.",
		"暫時無法連線到 AI 服務，請稍後再試。",
	),
	"provider_configuration": (
		502,
		"Coseeing's AI service is misconfigured. Please choose another model or try again later.",
		"Coseeing 的 AI 服務設定有問題，請改選其他模型或稍後再試。",
	),
	"provider_error": (
		502,
		"The AI service returned an error. Please try again later.",
		"AI 服務發生錯誤，請稍後再試。",
	),
	"service_error": (
		500,
		"The Coseeing service encountered a problem. Please try again later.",
		"Coseeing 服務發生問題，請稍後再試。",
	),
	"sso_unavailable": (
		503,
		"The Coseeing sign-in service is currently unavailable. Please try again later.",
		"目前無法連線到 Coseeing 登入服務，請稍後再試。",
	),
	"account_unverified": (
		403,
		"Your Coseeing account could not be verified. Please make sure its email address is verified, then sign in again.",
		"無法確認您的 Coseeing 帳戶，請確認電子郵件已驗證後重新登入。",
	),
	"account_disabled": (
		403,
		"Your Coseeing account has been disabled. Please contact Coseeing.",
		"您的 Coseeing 帳戶已停用，請聯絡 Coseeing。",
	),
	"account_conflict": (
		409,
		"There is a conflict with your Coseeing account. Please contact Coseeing.",
		"Coseeing 帳戶發生衝突，請聯絡 Coseeing。",
	),
}


def _correct(monkeypatch, status, json, warnings=None):
	"""Run one Coseeing correction whose /proofreader answer is (status, json)."""
	from test_coseeing_auth_nvda import _load_nvda_plugin

	queued = []
	plugin_module, _, _ = _load_nvda_plugin(
		monkeypatch,
		{
			"corrector_config_id": "default",
			"execution_channel": "Coseeing",
			"api_key": {},
			"language": "zh_traditional",
			"typo_correction_mode": "standard",
			"customized_words_enable": False,
			"auto_display_report": False,
		},
		[],
		queued,
		log_warnings=warnings,
	)
	instance = object.__new__(plugin_module.GlobalPlugin)
	instance.settings = plugin_module.settings
	instance.correctorTaskConfig = plugin_module.correctorTaskConfig
	instance.latest_action = plugin_module.CorrectionAction()
	instance.readDictionary = list
	instance._shutdown = threading.Event()
	instance.catalog = plugin_module.catalog
	instance._degraded_catalog_announced = False
	future = Future()
	future.set_result("access")
	monkeypatch.setattr(plugin_module, "get_coseeing_access_token", lambda: future)
	messages = []
	monkeypatch.setattr(plugin_module, "ui", SimpleNamespace(message=messages.append))
	response = SimpleNamespace(status_code=status, json=json)
	monkeypatch.setattr(plugin_module.requests, "post", lambda *args, **kwargs: response, raising=False)

	plugin_module.GlobalPlugin.correctTypo(instance, "原文")
	while queued:
		callback, args = queued.pop(0)
		callback(*args)
	return messages


@pytest.mark.parametrize("code", sorted(MESSAGES))
def test_each_code_speaks_its_message(monkeypatch, code):
	status, message, _ = MESSAGES[code]

	messages = _correct(monkeypatch, status, lambda: {"detail": "English", "code": code, "limit": 128})

	assert messages == [message.format(limit=128)]


@pytest.mark.parametrize(
	"status, expected",
	[(401, UNAUTHORIZED), (429, RATE_LIMITED), (413, FAILED), (503, FAILED)],
)
@pytest.mark.parametrize(
	"body",
	[{"detail": "x"}, {"detail": "x", "code": "made_up"}],
	ids=["no-code", "unknown"],
)
def test_unknown_or_missing_code_falls_back_by_status(monkeypatch, status, expected, body):
	assert _correct(monkeypatch, status, lambda: body) == [expected]


@pytest.mark.parametrize(
	"limit",
	[None, "128", True, 0, -5, 1.5],
	ids=["missing", "text", "bool", "zero", "negative", "float"],
)
def test_unusable_limit_falls_back_to_status_message(monkeypatch, limit):
	body = {"detail": "x", "code": "guest_text_too_long"}
	if limit is not None:
		body["limit"] = limit

	assert _correct(monkeypatch, 413, lambda: body) == [FAILED]


def _not_json():
	raise ValueError("not JSON")


@pytest.mark.parametrize("json", [_not_json, lambda: ["guest_quota_exceeded"], lambda: "text", lambda: None])
def test_non_object_body_falls_back(monkeypatch, json):
	assert _correct(monkeypatch, 429, json) == [RATE_LIMITED]


def test_code_and_status_are_logged_untranslated(monkeypatch):
	warnings = []

	_correct(monkeypatch, 413, lambda: {"detail": "x", "code": "guest_text_too_long", "limit": 128}, warnings)

	assert any("413" in str(entry) and "guest_text_too_long" in str(entry) for entry in warnings)


def _po_messages(locale):
	"""msgid -> msgstr for every entry of a locale's nvda.po, wrapped or not."""
	text = (LOCALE / locale / "LC_MESSAGES" / "nvda.po").read_text(encoding="utf8")

	def joined(block):
		return "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', block)).replace('\\"', '"')

	entries = {}
	for match in re.finditer(r'^msgid ((?:".*"\n)+)msgstr ((?:".*"\n?)+)', text, flags=re.MULTILINE):
		entries[joined(match.group(1))] = joined(match.group(2))
	return entries


def test_the_error_strings_have_translator_comments_and_translations():
	from test_catalog_url_dialog import ADDON, _assert_translated

	_assert_translated(ADDON / "__init__.py", {message: zh_tw for _, message, zh_tw in MESSAGES.values()})
	for locale in ("zh_CN", "zh_HK"):
		po = _po_messages(locale)
		for _, message, _ in MESSAGES.values():
			assert po.get(message), (locale, message)
			if "{limit}" in message:
				assert "{limit}" in po[message], (locale, message)
