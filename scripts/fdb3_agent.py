"""Room entrypoint for the same THREAD LiveKit pipeline. Requires existing credentials."""
import os
from pathlib import Path
import sys
import json
import threading
import uuid
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.fdb3_config import verify_whisper
from livekit import agents
from livekit.agents import AgentServer
from thread_agent.fdb3 import ControllerBridge, LocalPlanner, load_contract, load_registry
from thread_agent.fdb3_voice import WhisperSTT, ThreadVoiceAgent, create_session, append_journal, input_prompt


_collector_lock = threading.Lock()


class CollectingBridge(ControllerBridge):
    """Publish terminal invocation evidence before the actor receives its result."""
    def __init__(self, *args, room_name, telemetry_path, **kwargs):
        super().__init__(*args, **kwargs)
        self.room_name = room_name
        self.telemetry_path = Path(telemetry_path)

    def _journal_tool(self, phase, record):
        try:
            super()._journal_tool(phase, record)
        finally:
            if phase == 'finished':
                # The hook runs in the owned executor thread. Pending dispatch
                # intents stay in the durable journal, not the actual-call log.
                append_journal(self.telemetry_path, _collector_lock,
                               {'room': self.room_name, 'call': record})

# Do not pre-spawn one Python/Whisper worker per host CPU on a small GPU host.
# A single sequential benchmark room is the supported reproduction profile.
server = AgentServer(num_idle_processes=0, host="127.0.0.1",
                     port=int(os.environ.get("THREAD_AGENT_PORT", "8181")))


@server.rtc_session(agent_name=os.environ.get("THREAD_FDB3_AGENT_NAME", ""))
async def entrypoint(ctx):
    whisper_identity = verify_whisper(os.environ["THREAD_FDB3_WHISPER"])
    runtime = Path(os.environ["THREAD_FDB3_CONTRACT"])
    telemetry = Path(os.environ.get("THREAD_FDB3_TELEMETRY", "/tmp/agent_tool_calls.log"))
    telemetry.parent.mkdir(parents=True, exist_ok=True)
    journals = Path(os.environ.get("THREAD_FDB3_JOURNAL_DIR", "/tmp/thread-fdb3-journals"))
    journals.mkdir(parents=True, exist_ok=True)
    session_id = uuid.uuid4().hex
    evidence_path = journals / (session_id + '.session.json')
    planner = LocalPlanner(os.environ["THREAD_FDB3_ENDPOINT"], os.environ["THREAD_FDB3_MODEL"],
                           model_journal=journals / (session_id + '.model.jsonl'))
    bridge = CollectingBridge(load_contract(runtime),load_registry(runtime), planner,
                              room_name=ctx.room.name, telemetry_path=telemetry)
    bridge.tool_journal = journals / (session_id + '.jsonl')
    recognizer = WhisperSTT(os.environ["THREAD_FDB3_WHISPER"], prompt=input_prompt(runtime))
    recognizer.transcription_journal = journals / (session_id + '.stt.jsonl')
    await bridge.start()
    session = create_session(bridge,recognizer)
    errors = []
    session.on("error", lambda event: errors.append(str(event.error)))

    def save(status):
        # Agent-owned observability only. No recording IDs, labels, or evaluator
        # results enter this process. The probe reads these receipts after exit.
        body = {"status": status, "room": ctx.room.name, "recorded_at": time.time(),
                "actual_tool_calls": bridge.calls, "model_requests": planner.requests,
                "input_transcripts": recognizer.records, "stt_attempts": recognizer.attempts,
                "errors": errors + bridge.evidence_errors,
                "tool_journal": str(bridge.tool_journal),
                "whisper_device": recognizer.device, "compute_type": recognizer.compute_type,
                "whisper": whisper_identity}
        temporary = evidence_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(body, indent=2, default=str), encoding='utf-8')
        temporary.replace(evidence_path)

    async def shutdown():
        try:
            await session.aclose()
        except Exception as exc:
            errors.append('Session cleanup: ' + type(exc).__name__)
        try:
            await bridge.close()
        except Exception as exc:
            errors.append('Bridge cleanup: ' + type(exc).__name__)
        finally:
            save('closed')
    ctx.add_shutdown_callback(shutdown)
    await session.start(room=ctx.room,agent=ThreadVoiceAgent(bridge))
    save('ready')


if __name__ == "__main__":
    from scripts.fdb3_config import apply_environment
    apply_environment()
    agents.cli.run_app(server)
