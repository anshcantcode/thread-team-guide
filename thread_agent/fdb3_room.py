"""Loopback WebRTC diagnostic. No cloud service, external keys, or gold metadata."""
import asyncio
import time
import uuid
from livekit import api, rtc
from livekit.agents.voice.room_io import RoomOptions
from .fdb3_voice import ThreadVoiceAgent, audio_frames


class LocalRoom:
    def __init__(self, sink):
        self.name = "thread-diagnostic-" + uuid.uuid4().hex
        self.agent, self.user = rtc.Room(), rtc.Room()
        self.sink = sink
        self.receivers = []
        self.receiver_errors = []
        self.closed = False
        self.stream_start_time = None
        self.source = rtc.AudioSource(48000, 1, queue_size_ms=100)

    def token(self, identity):
        # Public development credentials for a server bound ONLY to loopback.
        return (api.AccessToken("devkey", "secret").with_identity(identity)
                .with_grants(api.VideoGrants(room_join=True, room=self.name)).to_jwt())

    async def start(self, session, bridge):
        @self.user.on("track_subscribed")
        def subscribed(track, publication, participant):
            if track.kind == rtc.TrackKind.KIND_AUDIO and participant.identity == "thread-agent":
                self.receivers.append(asyncio.create_task(self.receive(track)))

        @session.on("agent_state_changed")
        def changed(event):
            if event.old_state == "speaking" and event.new_state == "listening":
                self.sink.completed.set()

        await self.agent.connect("ws://127.0.0.1:7880", self.token("thread-agent"))
        await self.user.connect("ws://127.0.0.1:7880", self.token("audio-user"))
        track = rtc.LocalAudioTrack.create_audio_track("recording", self.source)
        publication = await self.user.local_participant.publish_track(track,
            rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
        await session.start(agent=ThreadVoiceAgent(bridge),room=self.agent,
            room_options=RoomOptions(participant_identity="audio-user",text_input=False,text_output=False))
        await asyncio.wait_for(publication.wait_for_subscription(), 15)

    async def receive(self, track):
        stream = rtc.AudioStream(track, sample_rate=24000, num_channels=1)
        try:
            async for event in stream:
                await self.sink.capture_frame(event.frame)
        finally:
            await stream.aclose()

    async def play(self, path):
        # AudioSource supplies actual real-time playout/backpressure.
        async for frame in audio_frames(path, paced=False):
            if self.stream_start_time is None:
                self.stream_start_time = time.time()
            await self.source.capture_frame(frame)
        await self.source.wait_for_playout()

    async def close(self):
        if self.closed:
            return
        self.closed = True
        for task in self.receivers:
            task.cancel()
        results = await asyncio.gather(*self.receivers, return_exceptions=True)
        self.receiver_errors.extend(result for result in results
                                    if isinstance(result, BaseException)
                                    and not isinstance(result, asyncio.CancelledError))
        cleanup_errors = []
        for component, method in ((self.source, 'aclose'), (self.user, 'disconnect'),
                                  (self.agent, 'disconnect')):
            try:
                await getattr(component, method)()
            except BaseException as exc:
                cleanup_errors.append(exc)
        if self.receiver_errors:
            raise RuntimeError('WebRTC audio capture failed: ' +
                               type(self.receiver_errors[0]).__name__) from self.receiver_errors[0]
        if cleanup_errors:
            raise cleanup_errors[0]
