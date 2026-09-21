"""Allowlisted metadata from HTTP 429 responses that are already in memory.

This observer never reads a stream, sends a request, or changes a response.
Unknown fields and values outside the conservative formats below are omitted.
"""

from __future__ import annotations

import json
import re
import weakref
from email.utils import parsedate_to_datetime


def matches(value, pattern):
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


def quota_metadata(response):
    if response.status_code != 429:
        return None
    result = {"http_status": 429}
    retry = response.headers.get("retry-after", "")
    if matches(retry, r"[0-9]{1,9}"):
        result["retry_after"] = retry
    elif matches(retry, r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun), [0-9]{2} (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) [0-9]{4} [0-9]{2}:[0-9]{2}:[0-9]{2} GMT"):
        try:
            parsedate_to_datetime(retry)
            result["retry_after"] = retry
        except ValueError:
            pass

    # httpx.Response.content only returns _content or raises ResponseNotRead.
    # Inspecting the existing buffer also avoids touching an unread stream.
    content = response.__dict__.get("_content")
    if not isinstance(content, bytes) or len(content) > 65536:
        return result
    try:
        payload = json.loads(content)
    except (ValueError, UnicodeError, RecursionError):
        return result
    error = payload.get("error") if isinstance(payload, dict) else None
    details = error.get("details") if isinstance(error, dict) else None
    if not isinstance(details, list):
        return result
    retries, violations = [], []
    for detail in details[:16]:
        if not isinstance(detail, dict):
            continue
        kind = detail.get("@type")
        if kind == "type.googleapis.com/google.rpc.RetryInfo":
            delay = detail.get("retryDelay")
            if matches(delay, r"[0-9]{1,9}(?:\.[0-9]{1,9})?s"):
                retries.append({"retryDelay": delay})
        elif kind == "type.googleapis.com/google.rpc.QuotaFailure":
            items = detail.get("violations")
            if not isinstance(items, list):
                continue
            for item in items[:16]:
                if not isinstance(item, dict):
                    continue
                clean = {}
                formats = {
                    "quotaMetric": r"generativelanguage\.googleapis\.com/[a-z_]{1,100}",
                    "quotaId": r"(?:Generate|Embed)[A-Za-z0-9_-]{1,159}",
                }
                for name, pattern in formats.items():
                    if matches(item.get(name), pattern):
                        clean[name] = item[name]
                value = item.get("quotaValue")
                if type(value) is int and 0 <= value < 10**18:
                    clean["quotaValue"] = str(value)
                elif matches(value, r"[0-9]{1,18}"):
                    clean["quotaValue"] = value
                dimensions = item.get("quotaDimensions")
                if isinstance(dimensions, dict):
                    safe_dimensions = {}
                    for name, pattern in {
                        "model": r"(?:models/)?gemini-[A-Za-z0-9._-]{1,80}",
                        "location": r"(?:global|us|eu|(?:us|europe|asia|northamerica|southamerica|australia|africa|me)-[a-z]{1,20}[0-9])",
                    }.items():
                        if matches(dimensions.get(name), pattern):
                            safe_dimensions[name] = dimensions[name]
                    if safe_dimensions:
                        clean["quotaDimensions"] = safe_dimensions
                if clean:
                    violations.append(clean)
    if retries:
        result["retry_info"] = retries
    if violations:
        result["quota_violations"] = violations
    return result


class QuotaObserver:
    """Read only exact candidate function frames; keep no raw response objects."""

    def __init__(self, functions):
        self.functions = functions  # code object -> phase
        self.rows, self.errors = [], []
        self.seen = weakref.WeakSet()

    def capture(self, frame):
        phase = self.functions.get(frame.f_code)
        if phase is None:
            return
        try:
            response = frame.f_locals.get("response")
            if response is None or response.status_code != 429 or response in self.seen:
                return
            row = quota_metadata(response)
            row["phase"] = phase
            record = frame.f_locals.get("record", {})
            request_id = record.get("request_id") if isinstance(record, dict) else None
            if matches(request_id, r"[0-9a-f]{32}"):
                row["request_id"] = request_id
            self.rows.append(row)
            self.seen.add(response)
        except Exception as exc:
            # Never expose an exception message that could contain provider data.
            self.errors.append(type(exc).__name__)
