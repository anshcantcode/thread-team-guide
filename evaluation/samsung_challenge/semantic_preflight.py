"""Pre-provider counterexamples to v1 semantic fixture assumptions.

Uses development rows only. Does not run a participant, read model outputs, or
rewrite frozen artifacts. The traces describe valid alternative behavior.
"""
from copy import deepcopy

from .generate import semantic_case
from .oracle import evaluate_case, get_path, selected


def latest_only_counterexample(schedule=0):
    case, witness = semantic_case("semantic_multicorrection", schedule, 0)
    latest_selector = next(rule["select"] for rule in case["oracle"] if rule["id"] == "correct_read")
    _, latest_call = selected(witness, latest_selector)[0]
    latest_id = latest_call["call_id"]
    trace = []
    for row in witness:
        if row.get("kind") == "event":
            trace.append(deepcopy(row))
        elif row.get("action") == "tool_call" and row.get("call_id") == latest_id:
            trace.append(deepcopy(row))
        elif row.get("kind") == "tool_completed" and row.get("call_id") == latest_id:
            trace.append(deepcopy(row))
        elif row.get("action") == "final_response":
            value = deepcopy(row)
            # No unspoken passenger/preferences invented by this semantic trace.
            value["state_snapshot"] = {"intent": "search", "slots": {}}
            trace.append(value)
    current_result = next(row["result"] for row in trace if row["kind"] == "tool_completed")
    first_indexed_reply = next(reply for reply in case["replies"] if reply["api_name"] == latest_call["api_name"] and reply["call_index"] == 0)
    return case, trace, {
        "strict_v1": evaluate_case(case, trace),
        "valid_behavior": "Wait for the completed correction chain, then make one lookup for the latest explicitly retained arguments.",
        "original_first_reply_matches_current_result": first_indexed_reply["deliveries"][0]["result"] == current_result,
        "participant_executions": 0,
        "model_outputs_inspected": 0,
    }


def other_returned_option_counterexample(family="semantic_novel_schema"):
    case, witness = semantic_case(family, 0, 0)
    grounding = next(rule for rule in case["oracle"] if rule["id"] == "grounded_read")
    container, index, key = grounding["path"].split(".")
    completion = next(row for row in witness if row.get("kind") == "tool_completed")
    alternate_path = f"{container}.{1 - int(index)}.{key}"
    alternate_value = get_path(completion["result"], alternate_path)
    trace = deepcopy(witness)
    final = next(row for row in trace if row.get("action") == "final_response")
    final["payload"]["text"] = f"Available option {alternate_value}."
    final["state_snapshot"] = {"intent": "search", "slots": {}}
    return case, trace, {
        "strict_v1": evaluate_case(case, trace),
        "valid_behavior": "Answer a general lookup using a different option genuinely returned by the same successful call.",
        "alternate_value_is_in_actual_result": alternate_value in completion["result"][container][1 - int(index)].values(),
        "participant_executions": 0,
        "model_outputs_inspected": 0,
    }
