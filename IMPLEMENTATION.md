# Participant implementation

The official evaluation entry point is `participant.agent:ParticipantAgent`,
configured in `submission.yaml`. The earlier `thread.v1` adapter remains a
separate historical interface for the consumer application and replay tools.

The participant accepts events through queues, tracks the current request and
cancels obsolete planning and tool work after corrections. Tool schemas are read
at runtime. The controller validates arguments, rejects stale results, requires
current permission for actions that change something, prevents duplicate
effects and retains outcomes that arrive after an interruption.

Gemini handles general interpretation. Narrow local rules support explicitly
recognized complete text requests and runtime tool-catalogue questions. They do
not replace general language understanding. Audio and image handling uses actual
media bytes and checks their structure before provider calls. Citations must
match evidence returned by tools.

The source is split between `participant/` for official evaluation and
`thread_agent/`, `android/` and `web/` for the existing application. Packaging
scripts copy selected official kit files unchanged and add the participant,
requirements, setup guidance and a file-hash manifest.

See [the engineering update](docs/ENGINEERING_UPDATE.md) for the change list,
[Gemini setup](docs/GEMINI_SETUP.md) for configuration, and
[the evidence summary](docs/submission/EVIDENCE.md) for recorded results and
remaining failures. The [answer-preservation proposal](proposals/manual-receipt/README.md)
is saved separately and is not active runtime code.
