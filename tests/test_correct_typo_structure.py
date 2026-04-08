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


def test_correct_typo_does_not_hide_runtime_vars_inside_missing_file_fallback():
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

	fallback_if = None
	for stmt in correct_typo.body:
		if isinstance(stmt, ast.If) and isinstance(stmt.test, ast.UnaryOp):
			fallback_if = stmt
			break

	assert fallback_if is not None
	assert "language" not in _assigned_names(fallback_if.body)
	assert "corrector_mode" not in _assigned_names(fallback_if.body)
	assert "corrector_config" not in _assigned_names(fallback_if.body)
