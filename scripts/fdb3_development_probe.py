"""Independent model probes, authored without benchmark IDs/transcripts/answers."""
import asyncio
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from thread_agent.fdb3 import LocalPlanner, sha256


async def main():
    target = Path(f".thread-run/raw/development-identifiers-{time.time_ns()}.json")
    planner = LocalPlanner("http://127.0.0.1:8097/v1","local-qwen",
                           model_journal=target.with_suffix('.jsonl'))
    await planner.setup()
    rows = []
    try:
        for text, expected in [("Find parcel R, Q, 7, 4.","RQ74"),
                               ("Find parcel Z dash 8.","Z-8")]:
            context = {"tools":{"lookup_parcel":{"kind":"read_only","description":"Look up parcel delivery status.",
                "args":{"parcel_id":{"type":"string","required":True,"description":"Parcel identifier."}}}},
                "state":{"intent":"","slots":{}},"messages":[{"message_index":0,"revision":1,
                "event_type":"user_speech_chunk","payload":{"text":text,"end_of_turn":True}}],
                "tool_results":[],"actions":[],"revision":1,"current_turn_start":0}
            try:
                decision = await planner.plan(context)
            except Exception as exc:
                rows.append({"text":text,"expected":expected,"passed":False,"error":str(exc),"error_type":type(exc).__name__})
                continue
            calls = decision.get("tool_calls")
            actual = calls[0].get("args",{}).get("parcel_id") if isinstance(calls,list) and calls and isinstance(calls[0],dict) else None
            passed = (isinstance(calls, list) and len(calls) == 1
                      and calls[0].get('api_name') == 'lookup_parcel'
                      and calls[0].get('args') == {'parcel_id': expected})
            rows.append({"text":text,"expected":expected,"actual":actual,"passed":passed,"decision":decision})
    finally:
        await planner.close()
        target.write_text(json.dumps({"provenance":"Independently authored developer text probes, not human audio",
            "source_sha256":sha256(__file__), "rows":rows,"usage":planner.requests},indent=2))
    print(json.dumps({"passed":sum(r["passed"] for r in rows),"total":len(rows)}))
    return all(r["passed"] for r in rows)


if __name__ == "__main__":
    raise SystemExit(0 if asyncio.run(main()) else 1)
