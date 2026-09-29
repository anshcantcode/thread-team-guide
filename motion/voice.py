"""Generate the film's directed performances with the existing local Gemini key.

Only the public script is sent. Credentials stay in an HTTP header and are never
included in output, command arguments, or saved assets. Reuses completed takes.
"""
import argparse
import base64
import json
import time
from pathlib import Path
import urllib.error
import urllib.request
import wave

import numpy as np

ROOT = Path(__file__).resolve().parent
TAKES = [
    ('character_session', 'Aoede', 'Find flights from Chennai to Delhi tomorrow, after nine. [long pause] Wait. Mumbai instead.', 'One consistent female character throughout the entire take. Warm, clear medium-high female register, light Indian English accent. She is speaking naturally to her phone. First she makes the request; then leave two full seconds of silence; then she changes her mind, speaking the second line as a spontaneous correction. Keep exactly the same vocal timbre, register, accent and microphone distance in both sentences. The correction is quick, friendly and decisive, never a different character. Do not speak the words long pause. The first sentence should take about 3.5 seconds and the correction about 1.7 seconds.'),
    ('01_open', 'Charon', 'A conversation never moves in a straight line. Neither should your assistant.', 'Intimate, assured, warm male cinematic narration. Thoughtful rather than dramatic. First sentence is reflective; second sentence has quiet conviction. Around 6 seconds.'),
    ('02_meet', 'Charon', 'Meet Thread.', 'Same warm, close-miked male narrator. Simple, quietly confident product introduction. A little space between the words. Thread is one syllable, the normal English word.'),
    ('03_request', 'Aoede', 'Find flights from Chennai to Delhi tomorrow, after nine.', 'Natural young adult woman speaking to her phone. Conversational, clear, lightly Indian English, not an announcer. Brisk and comfortable, approximately 3.6 seconds. Nine means nine at night.'),
    ('04_reply', 'Charon', "I found a few flights to Delhi. The first option leaves at", 'Calm helpful assistant, normal conversational delivery, medium brisk pace. Do not complete this unfinished sentence or add anything. This take will be interrupted in the edit.'),
    ('05_interrupt', 'Aoede', 'Wait. Mumbai instead.', 'Same natural young adult woman. A spontaneous correction, lightly Indian English. Wait is slightly urgent but friendly, quick small pause, then Mumbai instead. No theatrical shouting. Around 1.6 seconds.'),
    ('06_confirm', 'Charon', 'Mumbai. Tomorrow. After nine. Got it.', 'Calm helpful assistant, reassuring and concise. Distinct short phrases, no long pauses, approximately 2.8 seconds.'),
    ('07_core', 'Charon', 'Change your mind. Keep the details. Thread stops the old task, and carries the right one forward.', 'Warm cinematic male narrator as in the opening. Thoughtful emphasis on keep and right. Natural pace, not booming trailer delivery. Around 7.5 seconds.'),
    ('08_personal', 'Charon', 'From a quick search, to the things you want to keep. Rich results. Your library. Your home screen.', 'Same close-miked cinematic male narrator, a little brighter and more forward now. Crisp, inviting phrasing, approximately 7 seconds. Clear but never salesy.'),
    ('09_phone', 'Charon', 'Now, on your phone. No laptop needed.', 'Same warm cinematic male narrator. Confident and direct, around 3 seconds. Land gently on needed.'),
    ('10_close', 'Charon', 'Go on. Change your mind. Keep the thread.', 'Same warm cinematic male narrator. Understated invitation, unhurried, around 4 seconds. Very short breaths between sentences; a warm decisive finish. No shouting or whispering.'),
]

def split_character():
    """Cut the two dialogue lines from one continuous, consistent performance."""
    path=ROOT/'audio/character_session.wav'
    if not path.exists():return
    with wave.open(str(path),'rb') as wav:
        rate=wav.getframerate()
        pcm=np.frombuffer(wav.readframes(wav.getnframes()),'<i2')
    block=round(rate*.01)
    rms=np.sqrt(np.mean(pcm[:len(pcm)//block*block].astype(float).reshape(-1,block)**2,axis=1))
    quiet=rms<max(75,rms.max()*.012)
    runs=[];start=None
    for i,q in enumerate(np.r_[quiet,False]):
        if q and start is None:start=i
        if not q and start is not None:
            a,b=start*.01,i*.01
            if a>2.0 and b-a>.35 and b<len(pcm)/rate-.6:runs.append((a,b))
            start=None
    if not runs:raise RuntimeError('No clean dialogue break in the combined take; inspect before cutting.')
    a,b=max(runs,key=lambda ab:ab[1]-ab[0])
    cut=round((a+b)/2*rate)
    for name,data in [('03_request',pcm[:cut]),('05_interrupt',pcm[cut:])]:
        with wave.open(str(ROOT/'audio'/f'{name}.wav'),'wb') as wav:
            wav.setparams((1,2,rate,0,'NONE',''));wav.writeframes(data.tobytes())
        take=next(t for t in TAKES if t[0]==name)
        meta={'model':'gemini-3.1-flash-tts-preview','voice':'Aoede','transcript':take[2],'direction':'Same continuous performance as the other user line. See character_session.json.','source_take':'character_session.wav','split_seconds':cut/rate,'seconds':len(data)/rate}
        (ROOT/'audio'/f'{name}.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
    print('Character lines split at',round(cut/rate,3),'seconds',flush=True)

def generate(selected, config_path=None, model='gemini-3.1-flash-tts-preview'):
    values = dict(line.split('=', 1) for line in Path(config_path or ROOT.parent / '.env').read_text().splitlines() if '=' in line and not line.lstrip().startswith('#'))
    key = values['THREAD_API_KEY'].strip().strip('"').strip("'")
    out = ROOT / 'audio'
    out.mkdir(exist_ok=True)
    for name, voice, words, direction in TAKES:
        if selected and name not in selected:
            continue
        path = out / (name + '.wav')
        if path.exists():
            print(name, 'already saved', flush=True)
            if name=='character_session':split_character()
            continue
        prompt = f'Produce only the spoken transcript below. This is a premium product film voiceover recorded in a dry professional studio. No music, no sound effects, no added words, no spoken directions.\nDIRECTOR: {direction}\nTRANSCRIPT:\n{words}'
        payload = {'contents':[{'parts':[{'text':prompt}]}], 'generationConfig':{'responseModalities':['AUDIO'], 'speechConfig':{'voiceConfig':{'prebuiltVoiceConfig':{'voiceName':voice}}}}}
        req = urllib.request.Request(f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent', data=json.dumps(payload).encode(), headers={'Content-Type':'application/json','x-goog-api-key':key})
        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                data = json.load(response)
        except urllib.error.HTTPError as exc:
            err=json.loads(exc.read()).get('error',{})
            print(name, 'HTTP', exc.code, err.get('status'), flush=True)
            for detail in err.get('details',[]):
                for violation in detail.get('violations',[]):
                    print('quota:', violation.get('quotaId'), flush=True)
            raise SystemExit(1) from None
        parts = data.get('candidates',[{}])[0].get('content',{}).get('parts',[])
        audio_parts = [part['inlineData'] for part in parts if 'inlineData' in part]
        if not audio_parts:
            print(name, 'no audio returned', flush=True)
            raise SystemExit(2)
        pcm = b''.join(base64.b64decode(p['data']) for p in audio_parts)
        with wave.open(str(path), 'wb') as wav:
            wav.setparams((1,2,24000,0,'NONE','not compressed'))
            wav.writeframes(pcm)
        (out / (name + '.json')).write_text(json.dumps({'model':model,'voice':voice,'transcript':words,'direction':direction,'mimeType':audio_parts[0].get('mimeType'),'seconds':len(pcm)/48000},indent=2),encoding='utf-8')
        print(name, round(len(pcm)/48000,2), 'seconds', flush=True)
        if name=='character_session':split_character()
        # The configured project's TTS quota is three requests per minute.
        # Spacing the remaining independent takes avoids throwing away a run.
        time.sleep(35)

if __name__ == '__main__':
    p=argparse.ArgumentParser()
    p.add_argument('takes', nargs='*')
    generate(p.parse_args().takes)
