import ast
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVER_ROOT = PROJECT_ROOT / "server"
SERVER_MAIN = SERVER_ROOT / "main.py"
SERVER_CORRECTOR_DIR = SERVER_ROOT / "setting" / "corrector"


def _get_proofreader_function():
	module = ast.parse(SERVER_MAIN.read_text(encoding="utf-8"))
	for node in module.body:
		if isinstance(node, ast.FunctionDef) and node.name == "proofreader":
			return node
	return None


def test_server_proofreader_uses_application_layer_runner():
	proofreader = _get_proofreader_function()

	assert proofreader is not None

	used_names = {child.id for child in ast.walk(proofreader) if isinstance(child, ast.Name)}

	assert "run_typo_correction" in used_names
	assert "ChineseTypoCorrector" not in used_names
	assert "ChineseTypoCorrectorLite" not in used_names


def test_server_proofreader_reads_flat_corrector_schema():
	proofreader = _get_proofreader_function()

	assert proofreader is not None

	string_constants = {
		child.value
		for child in ast.walk(proofreader)
		if isinstance(child, ast.Constant) and isinstance(child.value, str)
	}

	assert "corrector_config_id" in string_constants
	assert "llm_access_method" not in string_constants
	assert "secret_key" not in string_constants
	assert "corrector_config_filename" not in string_constants


def test_server_proofreader_looks_up_config_by_id():
	proofreader = _get_proofreader_function()

	assert proofreader is not None

	calls = [
		node for node in ast.walk(proofreader)
		if isinstance(node, ast.Call)
		and isinstance(node.func, ast.Attribute)
		and node.func.attr == "get_config"
	]

	assert calls, "proofreader should resolve configs through configManager.get_config"
	assert any(
		any(isinstance(arg, ast.Name) and arg.id == "corrector_config_id" for arg in call.args)
		for call in calls
	)


def test_addon_and_server_corrector_catalogs_match_by_model_provider_pair():
	addon_dir = PROJECT_ROOT / "addon" / "globalPlugins" / "WordBridge" / "setting" / "corrector"
	addon_configs = {}
	server_configs = {}

	for path in addon_dir.glob("*.json"):
		with path.open("r", encoding="utf-8") as f:
			config = json.load(f)
		addon_configs[(config["model"], config["provider"])] = config

	for path in SERVER_CORRECTOR_DIR.glob("*.json"):
		with path.open("r", encoding="utf-8") as f:
			config = json.load(f)
		server_configs[(config["model"], config["provider"])] = config

	assert addon_configs == server_configs
