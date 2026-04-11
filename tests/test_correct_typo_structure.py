import ast
from pathlib import Path


def _assigned_names(nodes):
	names = set()
	for node in nodes:
		for child in ast.walk(node):
			if isinstance(child, ast.Assign):
				for target in child.targets:
					if isinstance(target, ast.Name):
						names.add(target.id)
			elif isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
				names.add(child.target.id)
	return names


def test_correct_typo_uses_config_id_and_execution_channel_instead_of_filename_lookup():
	module_path = (
		Path(__file__).resolve().parents[1]
		/ "addon"
		/ "globalPlugins"
		/ "WordBridge"
		/ "__init__.py"
	)
	module = ast.parse(module_path.read_text(encoding="utf-8"))

	correct_typo = None
	for node in module.body:
		if isinstance(node, ast.ClassDef) and node.name == "GlobalPlugin":
			for item in node.body:
				if isinstance(item, ast.FunctionDef) and item.name == "correctTypo":
					correct_typo = item
					break

	assert correct_typo is not None

	string_constants = {
		child.value
		for child in ast.walk(correct_typo)
		if isinstance(child, ast.Constant) and isinstance(child.value, str)
	}
	used_names = {child.id for child in ast.walk(correct_typo) if isinstance(child, ast.Name)}

	assert "corrector_config_id" in string_constants
	assert "execution_channel" in string_constants
	assert "corrector_config_filename" not in string_constants
	assert "normalize_selection" in used_names


def test_correct_typo_uses_application_layer_instead_of_low_level_llm_assembly():
	module_path = (
		Path(__file__).resolve().parents[1]
		/ "addon"
		/ "globalPlugins"
		/ "WordBridge"
		/ "__init__.py"
	)
	module = ast.parse(module_path.read_text(encoding="utf-8"))

	low_level_names = {
		"LiteInstructionComposer",
		"StandardInstructionComposer",
		"LiteChineseTextPolicy",
		"StandardChineseTextPolicy",
		"ChineseTypoCorrector",
		"CorrectionOrchestrator",
		"get_provider",
		"get_provider_model_adapter",
	}

	correct_typo = None
	for node in module.body:
		if isinstance(node, ast.ClassDef) and node.name == "GlobalPlugin":
			for item in node.body:
				if isinstance(item, ast.FunctionDef) and item.name == "correctTypo":
					correct_typo = item
					break

	assert correct_typo is not None

	used_names = {child.id for child in ast.walk(correct_typo) if isinstance(child, ast.Name)}
	assert "run_typo_correction" in used_names
	assert low_level_names.isdisjoint(used_names)


def test_legacy_compatibility_modules_are_removed():
	lib_dir = (
		Path(__file__).resolve().parents[1]
		/ "addon"
		/ "globalPlugins"
		/ "WordBridge"
		/ "lib"
	)
	legacy_paths = [
		lib_dir / "provider.py",
		lib_dir / "provider_model_adapter.py",
		lib_dir / "instruction_composer.py",
		lib_dir / "language_text_policy.py",
		lib_dir / "typo_corrector.py",
	]

	for path in legacy_paths:
		assert not path.exists(), f"legacy compatibility module should be removed: {path.name}"


def test_typo_specific_dictionary_and_helpers_live_under_tasks_typo():
	root = Path(__file__).resolve().parents[1] / "addon" / "globalPlugins" / "WordBridge" / "lib"

	assert not (root / "chinese_dictionary.py").exists()
	assert (root / "tasks" / "typo" / "chinese_dictionary.py").exists()
	assert (root / "tasks" / "typo" / "utils.py").exists()
	assert (root / "tasks" / "typo" / "data" / "dict_revised_2015_20231228_csv.csv").exists()


def test_task_execution_helpers_live_under_tasks_layer():
	root = Path(__file__).resolve().parents[1] / "addon" / "globalPlugins" / "WordBridge" / "lib"
	assert (root / "tasks" / "concurrency.py").exists()
	if (root / "utils.py").exists():
		utils_module = ast.parse((root / "utils.py").read_text(encoding="utf-8"))
		assert "parallel_map" not in {node.name for node in utils_module.body if isinstance(node, ast.FunctionDef)}


def test_chinese_text_helpers_live_under_text_layer():
	root = Path(__file__).resolve().parents[1] / "addon" / "globalPlugins" / "WordBridge" / "lib"
	assert (root / "text" / "chinese.py").exists()
	if (root / "utils.py").exists():
		utils_module = ast.parse((root / "utils.py").read_text(encoding="utf-8"))
		utils_functions = {node.name for node in utils_module.body if isinstance(node, ast.FunctionDef)}
		utils_assignments = {
			target.id
			for node in utils_module.body
			if isinstance(node, ast.Assign)
			for target in node.targets
			if isinstance(target, ast.Name)
		}
		assert {"is_chinese_character", "has_chinese", "has_simplified_chinese_char", "has_traditional_chinese_char", "get_descs"}.isdisjoint(utils_functions)
		assert {"SEPERATOR", "PUNCTUATION", "ZH_UNICODE_INTERVALS"}.isdisjoint(utils_assignments)


def test_cost_calculator_lives_under_llm_layer():
	root = Path(__file__).resolve().parents[1] / "addon" / "globalPlugins" / "WordBridge" / "lib"

	assert not (root / "cost_calculator.py").exists()
	assert (root / "llm" / "cost_calculator.py").exists()


def test_dialogs_account_groups_follow_provider_group_order():
	module_path = (
		Path(__file__).resolve().parents[1]
		/ "addon"
		/ "globalPlugins"
		/ "WordBridge"
		/ "dialogs.py"
	)
	source = module_path.read_text(encoding="utf-8")

	assert "zip(configManager.provider_groups, configManager.endpoint_labels)" in source
