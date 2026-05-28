import json
import sys

DEFAULT_F05_THRESHOLD = 0.8
DEFAULT_NED_THRESHOLD = 0.1


def _as_text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _levenshtein_distance(a, b):
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i]
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            curr.append(min(
                prev[j] + 1,
                curr[j - 1] + 1,
                prev[j - 1] + cost,
            ))
        prev = curr
    return prev[-1]


def _normalized_edit_distance(a, b):
    denom = max(len(a), len(b))
    if denom == 0:
        return 0.0
    return _levenshtein_distance(a, b) / denom


def _extract_edits(src, tgt):
    rows = len(src) + 1
    cols = len(tgt) + 1
    dp = [[0] * cols for _ in range(rows)]

    for i in range(1, rows):
        dp[i][0] = i
    for j in range(1, cols):
        dp[0][j] = j

    for i in range(1, rows):
        for j in range(1, cols):
            cost = 0 if src[i - 1] == tgt[j - 1] else 1
            dp[i][j] = min(
                dp[i - 1][j] + 1,
                dp[i][j - 1] + 1,
                dp[i - 1][j - 1] + cost,
            )

    edits = []
    i = len(src)
    j = len(tgt)
    while i > 0 or j > 0:
        if i > 0 and j > 0 and src[i - 1] == tgt[j - 1]:
            i -= 1
            j -= 1
            continue

        if i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + 1:
            edits.append(("replace", i - 1, src[i - 1], tgt[j - 1]))
            i -= 1
            j -= 1
            continue

        if i > 0 and dp[i][j] == dp[i - 1][j] + 1:
            edits.append(("delete", i - 1, src[i - 1], ""))
            i -= 1
            continue

        edits.append(("insert", i, "", tgt[j - 1]))
        j -= 1

    edits.reverse()
    return set(edits)


def _compute_f05(input_text, output_text, expected_text):
    predicted = _extract_edits(input_text, output_text)
    gold = _extract_edits(input_text, expected_text)

    if not predicted and not gold:
        return 1.0, 1.0, 1.0

    true_positive = len(predicted & gold)
    precision = true_positive / len(predicted) if predicted else 1.0
    recall = true_positive / len(gold) if gold else 0.0

    beta = 0.5
    denom = (beta ** 2) * precision + recall
    f05 = 0.0 if denom == 0 else (1 + beta ** 2) * precision * recall / denom
    return f05, precision, recall


def _get_thresholds(context):
    vars_dict = context.get("vars", {}) if isinstance(context, dict) else {}
    f05_threshold = _to_float_or_default(
        vars_dict.get("f05_threshold"),
        DEFAULT_F05_THRESHOLD,
    )
    ned_threshold = _to_float_or_default(
        vars_dict.get("ned_threshold"),
        DEFAULT_NED_THRESHOLD,
    )
    return f05_threshold, ned_threshold


def _to_float_or_default(value, default_value):
    if value is None:
        return float(default_value)
    if isinstance(value, str) and value.strip() == "":
        return float(default_value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default_value)


def _get_expected_input(context):
    vars_dict = context.get("vars", {}) if isinstance(context, dict) else {}
    input_text = _as_text(vars_dict.get("input", ""))
    expected_text = _as_text(vars_dict.get("expected", ""))
    return input_text, expected_text


def get_assert(output, context):
    """Promptfoo assertion entry point."""
    output_text = output.get("output") if isinstance(output, dict) else output
    output_text = _as_text(output_text)
    input_text, expected_text = _get_expected_input(context)
    f05_threshold, ned_threshold = _get_thresholds(context)

    f05, precision, recall = _compute_f05(input_text, output_text, expected_text)
    ned = _normalized_edit_distance(output_text, expected_text)

    passed = f05 >= f05_threshold and ned <= ned_threshold
    reason = (
        "f0.5={:.4f}, precision={:.4f}, recall={:.4f}, ned={:.4f}, "
        "thresholds(f0.5>={:.2f}, ned<={:.2f})"
    ).format(f05, precision, recall, ned, f05_threshold, ned_threshold)

    return {
        "pass": passed,
        "score": f05,
        "metrics": {
            "f0_5": f05,
            "precision": precision,
            "recall": recall,
            "ned": ned,
        },
        "reason": reason,
    }


def _to_grading_result(result):
    if isinstance(result, dict):
        return result
    if isinstance(result, bool):
        return {"pass": result, "score": 1.0 if result else 0.0}
    if isinstance(result, (int, float)):
        score = float(result)
        return {"pass": score >= 0.5, "score": score}
    return {"pass": False, "score": 0.0, "reason": "Invalid assertion result"}


if __name__ == "__main__":
    output_arg = sys.argv[1] if len(sys.argv) > 1 else ""
    context_arg = sys.argv[2] if len(sys.argv) > 2 else "{}"
    try:
        context_obj = json.loads(context_arg)
    except json.JSONDecodeError:
        context_obj = {}

    result_obj = _to_grading_result(get_assert(output_arg, context_obj))
    print(json.dumps(result_obj))
