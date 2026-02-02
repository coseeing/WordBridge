import json

def print_test_results(model_name, test_text, response, diff, corrector):
	cost = corrector.get_total_cost()

	print(f"\n=== Test Results ({model_name}) ===")
	print(f"Input:  {test_text}")
	print(f"Output: {response}")
	print(f"Cost:   ${cost} USD")
	print(f"API calls: {len(corrector.response_history)}")
	print(f"Diff:   {diff}")

	print("\n=== API Response ===")
	print(json.dumps(corrector.response_history[0], indent=2, ensure_ascii=False))
