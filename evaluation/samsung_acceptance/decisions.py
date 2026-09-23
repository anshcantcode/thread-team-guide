"""Opt-in private decision snapshots from existing Python profile events.

No requests, stream reads, runtime patches or references to mutable decisions.
Only imported candidate code objects are observed; prompts/headers/media stay out.
"""
from __future__ import annotations

import dis
import hashlib
import json
import math


LIMIT = 1_048_576
OMIT = {"apikey", "secretgeminiapikey", "threadapikey", "geminiapikey", "googleapikey",
        "xgoogapikey", "headers", "requestheaders", "responseheaders", "prompt", "systeminstruction",
        "inlinedata", "filedata", "querystring", "thought", "thoughtsignature"}


def snapshot(value, secrets):
    """Copy JSON data, omitting private fields and redacting credential values."""
    def clean(item):
        if isinstance(item, str):
            for secret in secrets:
                item = item.replace(secret, "[credential removed]")
            return item
        if isinstance(item, dict):
            return {clean(key): clean(child) for key, child in item.items()
                    if isinstance(key, str) and key.replace("_", "").replace("-", "").casefold() not in OMIT}
        if isinstance(item, (list, tuple)):
            return [clean(child) for child in item]
        return item
    packed = json.dumps(clean(value), ensure_ascii=False, allow_nan=False)
    if len(packed.encode()) > LIMIT:
        raise ValueError("decision snapshot exceeds private evidence limit")
    return json.loads(packed)


def buffered_response(response, phase):
    if response is None:
        return {"state": "absent"}
    result = {"http_status": response.status_code}
    content = response.__dict__.get("_content")
    if not isinstance(content, bytes):
        return {**result, "state": "not_buffered"}
    if len(content) > LIMIT:
        return {**result, "state": "oversized"}
    try:
        payload = json.loads(content)
    except (ValueError, UnicodeError, RecursionError):
        return {**result, "state": "invalid_json"}
    if not isinstance(payload, dict):
        return {**result, "state": "non_object_json"}
    result.update(state="buffered_json", **{key: payload[key] for key in
                  ("modelVersion", "responseId", "usageMetadata", "promptFeedback") if key in payload})
    if phase == "embedding":
        embedding = payload.get("embedding")
        if isinstance(embedding, dict) and "values" in embedding:
            values = embedding["values"]
            if isinstance(values, list) and all(type(v) in (int, float) and math.isfinite(v) for v in values):
                result["embedding_values"] = values
            else:
                result["embedding_values_state"] = "invalid_numeric_vector"
    elif isinstance(payload.get("candidates"), list):
        result["candidates"] = []
        for candidate in payload["candidates"]:
            if not isinstance(candidate, dict):
                continue
            row = {key: candidate[key] for key in ("index", "finishReason", "safetyRatings") if key in candidate}
            content = candidate.get("content")
            if isinstance(content, dict) and isinstance(content.get("parts"), list):
                text = "".join(part["text"] for part in content["parts"] if isinstance(part, dict)
                               and not part.get("thought") and isinstance(part.get("text"), str))
                row["non_thought_text_sha256"] = hashlib.sha256(text.encode()).hexdigest()
                try:
                    row["native_decision"] = json.loads(text)
                    row["decision_state"] = "parsed_json"
                except (ValueError, RecursionError):
                    # Malformed text can contain arbitrary prompts/header material.
                    row["decision_state"] = "invalid_json" if text else "no_non_thought_text"
            result["candidates"].append(row)
    return result


class DecisionObserver:
    def __init__(self, functions, secrets=()):
        self.functions = functions  # exact code object -> (stage, phase)
        self.secrets = tuple(sorted({s for s in secrets if s}, key=len, reverse=True))
        self.rows, self.errors = [], []

    def capture(self, frame, event, result):
        target = self.functions.get(frame.f_code)
        if target is None:
            return
        stage, phase = target
        if event != ("call" if stage == "controller_apply" else "return"):
            return
        # Async profile returns also mark suspension. Keep only completion/unwind.
        if event == "return" and frame.f_lasti >= 0 and dis.opname[frame.f_code.co_code[frame.f_lasti]] in {"YIELD_VALUE", "YIELD_FROM"}:
            return
        row = {"stage": stage, "phase": phase}
        try:
            local = frame.f_locals
            record = local.get("record", local.get("evidence"))
            if isinstance(record, dict):
                row["runtime_metadata"] = record
            context = local.get("context")
            if isinstance(context, dict) and "revision" in context:
                row["revision"] = context["revision"]
            elif stage == "controller_apply":
                row["revision"] = getattr(local.get("self"), "revision", None)
            if stage in {"provider_response", "embedding_return"}:
                response = local.get("response")
                row["provider_response"] = buffered_response(response, phase)
                # Link to transport evidence without retaining URL/headers/body.
                request = response.__dict__.get("_request") if response is not None else None
                content = request.__dict__.get("_content") if request is not None else None
                if isinstance(content, bytes):
                    row["request_body_sha256"] = hashlib.sha256(content).hexdigest()
            if stage == "controller_apply":
                row["decision"] = local.get("decision")
            elif stage in {"planner_return", "embedding_return"}:
                row["return_state"] = "no_return_value" if result is None else "returned"
                if result is not None:
                    row["value"] = result
            self.rows.append(snapshot(row, self.secrets))
        except Exception as exc:
            error = {"stage": stage, "phase": phase, "error_type": type(exc).__name__}
            self.errors.append(error)
            self.rows.append({**error, "capture_state": "failed"})
