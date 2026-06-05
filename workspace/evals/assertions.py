import json
import sys

DEFAULT_F2_THRESHOLD = 0.8
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


def _compute_f_beta(input_text, output_text, expected_text, beta):
    predicted = _extract_edits(input_text, output_text)
    gold = _extract_edits(input_text, expected_text)

    true_positive = len(predicted & gold)
    false_positive = len(predicted - gold)
    false_negative = len(gold - predicted)

    if not predicted and not gold:
        return 1.0, 1.0, 1.0, true_positive, false_positive, false_negative

    precision = true_positive / len(predicted) if predicted else 1.0
    recall = true_positive / len(gold) if gold else 0.0

    denom = (beta ** 2) * precision + recall
    f_beta = 0.0 if denom == 0 else (
        (1 + beta ** 2) * precision * recall / denom
    )
    return f_beta, precision, recall, true_positive, false_positive, false_negative


def _get_thresholds(context):
    vars_dict = context.get("vars", {}) if isinstance(context, dict) else {}
    f2_threshold = _to_float_or_default(
        vars_dict.get("f2_threshold", vars_dict.get("f05_threshold")),
        DEFAULT_F2_THRESHOLD,
    )
    ned_threshold = _to_float_or_default(
        vars_dict.get("ned_threshold"),
        DEFAULT_NED_THRESHOLD,
    )
    return f2_threshold, ned_threshold


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
    f2_threshold, ned_threshold = _get_thresholds(context)

    (
        f2,
        precision,
        recall,
        true_positive,
        false_positive,
        false_negative,
    ) = _compute_f_beta(input_text, output_text, expected_text, beta=2.0)
    ned = _normalized_edit_distance(output_text, expected_text)

    passed = f2 >= f2_threshold and ned <= ned_threshold
    reason = (
        "f2={:.4f}, precision={:.4f}, recall={:.4f}, ned={:.4f}, "
        "tp={}, fp={}, fn={}, "
        "thresholds(f2>={:.2f}, ned<={:.2f})"
    ).format(
        f2,
        precision,
        recall,
        ned,
        true_positive,
        false_positive,
        false_negative,
        f2_threshold,
        ned_threshold,
    )

    return {
        "pass": passed,
        "score": f2,
        "named_scores": {
            "case_f2": f2,
            "case_precision": precision,
            "case_recall": recall,
            "case_ned": ned,
            "true_positives": true_positive,
            "false_positives": false_positive,
            "false_negatives": false_negative,
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
