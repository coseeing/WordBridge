from concurrent.futures import Future
from types import SimpleNamespace

import pytest

from lib.coseeing import build_coseeing_headers


def test_guest_has_no_authorization_header():
	assert build_coseeing_headers(None) == {}


def test_signed_in_header_uses_access_token():
	assert build_coseeing_headers("access") == {"Authorization": "Bearer access"}


def test_empty_access_token_is_rejected():
	try:
		build_coseeing_headers("")
	except ValueError as error:
		assert str(error) == "access token must not be empty"
	else:
		assert False, "empty access token must not create a bearer header"


@pytest.mark.parametrize("access_token, expected_headers", [("access", {"Authorization": "Bearer access"}), (None, {})])
def test_proofreader_uses_completed_auth_future_and_preserves_payload(monkeypatch, access_token, expected_headers):
	from test_coseeing_auth_nvda import _load_nvda_plugin

	queued = []
	plugin_module, config, _ = _load_nvda_plugin(monkeypatch, {
		"corrector_config_id": "deepseek-v4-flash&DeepSeek",
		"execution_channel": "Coseeing",
		"api_key": {},
		"language": "zh_traditional",
		"typo_correction_mode": "standard",
		"customized_words_enable": False,
		"auto_display_report": False,
	}, [], queued)
	instance = object.__new__(plugin_module.GlobalPlugin)
	instance.latest_action = {}
	instance.readDictionary = lambda: []
	instance._coseeing_auth_terminated = False
	future = Future()
	future.set_result(access_token)
	monkeypatch.setattr(plugin_module, "get_coseeing_access_token", lambda: future)
	record = {}

	class Response:
		status_code = 200

		def json(self):
			return {"response": "修正", "interaction_id": "i-1", "cost": 0}

	def post(url, **kwargs):
		record.update(url=url, **kwargs)
		return Response()

	monkeypatch.setattr(plugin_module.requests, "post", post, raising=False)
	monkeypatch.setattr(plugin_module, "strings_diff", lambda request, response: [])
	monkeypatch.setattr(plugin_module.api, "copyToClip", lambda text: None, raising=False)
	monkeypatch.setattr(plugin_module, "ui", SimpleNamespace(message=lambda message: None))
	monkeypatch.setattr(plugin_module, "log", SimpleNamespace(warning=lambda *args: None))
	plugin_module.GlobalPlugin.correctTypo(instance, "原文")

	assert record == {
		"url": f"{plugin_module.COSEEING_BASE_URL}/proofreader",
		"headers": expected_headers,
		"json": {
			"request": "原文",
			"corrector_config_id": "deepseek-v4-flash&DeepSeek",
			"language": "zh_traditional",
			"typo_correction_mode": "standard",
			"customized_words": [],
		},
		"timeout": 120,
	}


def test_feedback_snapshots_input_and_waits_for_auth_without_blocking_ui(monkeypatch):
	from test_coseeing_auth_nvda import _load_nvda_plugin

	queued = []
	plugin_module, _, gui = _load_nvda_plugin(monkeypatch, {
		"corrector_config_id": "deepseek-v4-flash&DeepSeek",
		"execution_channel": "Coseeing",
		"api_key": {},
	}, [], queued)
	instance = object.__new__(plugin_module.GlobalPlugin)
	instance._coseeing_auth_terminated = False
	instance.latest_action = {"interaction_id": "i-old", "request": "原文", "response": "修正"}
	future = Future()
	monkeypatch.setattr(plugin_module, "get_coseeing_access_token", lambda: future)
	record = {}

	class Dialog:
		feedbackTextCtrl = SimpleNamespace(GetValue=lambda: "回饋")

		def __init__(self, *args):
			pass

		def __enter__(self):
			return self

		def __exit__(self, *args):
			return False

		def ShowModal(self):
			return plugin_module.wx.ID_OK

	monkeypatch.setattr(plugin_module, "FeedbackDialog", Dialog)
	plugin_module.wx.ID_OK = plugin_module.wx.OK
	def post(url, **kwargs):
		record.update(url=url, **kwargs)
		return SimpleNamespace(status_code=200, json=lambda: {})

	monkeypatch.setattr(plugin_module.requests, "post", post, raising=False)
	plugin_module.GlobalPlugin.script_correctionFeedback(instance, None)
	assert len(queued) == 1
	show, args = queued.pop()
	show(*args)
	instance.latest_action["interaction_id"] = "i-new"
	assert record == {}

	future.set_result(None)
	worker = instance._feedback_thread
	worker.join(timeout=1)
	assert record["url"] == f"{plugin_module.COSEEING_BASE_URL}/feedback"
	assert record["headers"] == {}
	assert record["json"] == {"interaction_id": "i-old", "review_content": "回饋"}
	assert record["timeout"] == 120


def test_feedback_auth_failure_skips_post_and_notifies_on_ui(monkeypatch):
	from test_coseeing_auth_nvda import _load_nvda_plugin

	queued = []
	plugin_module, _, _ = _load_nvda_plugin(monkeypatch, {
		"corrector_config_id": "deepseek-v4-flash&DeepSeek",
		"execution_channel": "Coseeing",
		"api_key": {},
	}, [], queued)
	instance = object.__new__(plugin_module.GlobalPlugin)
	instance._coseeing_auth_terminated = False
	future = Future()
	future.set_exception(RuntimeError("auth failed"))
	monkeypatch.setattr(plugin_module, "get_coseeing_access_token", lambda: future)
	class Timeout(Exception):
		pass

	posted = []
	monkeypatch.setattr(plugin_module.requests, "post", lambda *args, **kwargs: posted.append(args), raising=False)
	monkeypatch.setattr(plugin_module.requests, "exceptions", SimpleNamespace(Timeout=Timeout), raising=False)
	messages = []
	monkeypatch.setattr(plugin_module, "ui", SimpleNamespace(message=messages.append))

	instance._send_coseeing_feedback("i-1", "回饋")

	assert posted == []
	assert len(queued) == 1
	callback, args = queued.pop()
	callback(*args)
	assert "auth failed" in messages[0]


def _feedback_worker_fixture(monkeypatch, response, access_token="access"):
	from test_coseeing_auth_nvda import _load_nvda_plugin

	queued = []
	plugin_module, _, _ = _load_nvda_plugin(monkeypatch, {
		"corrector_config_id": "deepseek-v4-flash&DeepSeek",
		"execution_channel": "Coseeing",
		"api_key": {},
	}, [], queued)
	instance = object.__new__(plugin_module.GlobalPlugin)
	instance._coseeing_auth_terminated = False
	future = Future()
	future.set_result(access_token)
	monkeypatch.setattr(plugin_module, "get_coseeing_access_token", lambda: future)
	record = {}
	monkeypatch.setattr(
		plugin_module.requests,
		"post",
		lambda url, **kwargs: record.update(url=url, **kwargs) or response,
		raising=False,
	)
	class Timeout(Exception):
		pass

	monkeypatch.setattr(plugin_module.requests, "exceptions", SimpleNamespace(Timeout=Timeout), raising=False)
	messages = []
	monkeypatch.setattr(plugin_module, "ui", SimpleNamespace(message=messages.append))
	return plugin_module, instance, queued, record, messages


def test_feedback_uses_bearer_header_and_preserves_payload(monkeypatch):
	response = SimpleNamespace(status_code=200, json=lambda: {})
	plugin_module, instance, queued, record, messages = _feedback_worker_fixture(monkeypatch, response)

	instance._send_coseeing_feedback("i-1", "回饋")

	assert record == {
		"url": f"{plugin_module.COSEEING_BASE_URL}/feedback",
		"headers": {"Authorization": "Bearer access"},
		"json": {"interaction_id": "i-1", "review_content": "回饋"},
		"timeout": 120,
	}
	assert queued == []
	assert messages == []


def test_feedback_401_notifies_on_ui_after_recording_http_error(monkeypatch):
	response = SimpleNamespace(status_code=401, json=lambda: (_ for _ in ()).throw(AssertionError("decoded")))
	plugin_module, instance, queued, record, messages = _feedback_worker_fixture(monkeypatch, response)

	instance._send_coseeing_feedback("i-1", "回饋")

	assert record["url"].endswith("/feedback")
	assert len(queued) == 1
	callback, args = queued.pop()
	callback(*args)
	assert "Authentication error" in messages[0]


@pytest.mark.parametrize("response", [
	SimpleNamespace(status_code=200, json=lambda: (_ for _ in ()).throw(ValueError("invalid json"))),
])
def test_feedback_invalid_json_notifies_on_ui(monkeypatch, response):
	_, instance, queued, _, messages = _feedback_worker_fixture(monkeypatch, response)

	instance._send_coseeing_feedback("i-1", "回饋")

	assert len(queued) == 1
	callback, args = queued.pop()
	callback(*args)
	assert "invalid json" in messages[0]


def test_feedback_timeout_notifies_on_ui(monkeypatch):
	from test_coseeing_auth_nvda import _load_nvda_plugin

	class Timeout(Exception):
		pass

	queued = []
	plugin_module, _, _ = _load_nvda_plugin(monkeypatch, {
		"corrector_config_id": "deepseek-v4-flash&DeepSeek",
		"execution_channel": "Coseeing",
		"api_key": {},
	}, [], queued)
	instance = object.__new__(plugin_module.GlobalPlugin)
	instance._coseeing_auth_terminated = False
	future = Future()
	future.set_result("access")
	monkeypatch.setattr(plugin_module, "get_coseeing_access_token", lambda: future)
	monkeypatch.setattr(plugin_module.requests, "exceptions", SimpleNamespace(Timeout=Timeout), raising=False)
	monkeypatch.setattr(plugin_module.requests, "post", lambda *args, **kwargs: (_ for _ in ()).throw(Timeout()), raising=False)
	messages = []
	monkeypatch.setattr(plugin_module, "ui", SimpleNamespace(message=messages.append))

	instance._send_coseeing_feedback("i-1", "回饋")

	assert len(queued) == 1
	callback, args = queued.pop()
	callback(*args)
	assert "timed out" in messages[0]
