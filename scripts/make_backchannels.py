"""Generate short, cached acknowledgments with the app's existing Gemini voices.

Run manually when changing voice assets. No network/model call occurs on a barge-in.
These are synthetic Gemini voices, not recordings or copies of an OpenAI voice.
"""
import asyncio
import base64
import json
from pathlib import Path
import re
import struct
import sys
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from thread_agent.live import ENDPOINT, VOICES
from thread_agent.planner import settings
import websockets


async def generate(voice):
    output=ROOT/'web'/'sounds'/f'ack-{voice}.wav'
    if output.exists(): return {'voice':voice,'path':str(output.relative_to(ROOT)),'existing':True}
    config=settings()
    async with websockets.connect(ENDPOINT,additional_headers={'x-goog-api-key':config['key']},open_timeout=15,max_size=8_000_000) as ws:
        await ws.send(json.dumps({'setup':{'model':'models/'+config['live_model'],
            'generationConfig':{'responseModalities':['AUDIO'],'speechConfig':{'voiceConfig':{'prebuiltVoiceConfig':{'voiceName':voice}}}},
            'outputAudioTranscription':{}, 'systemInstruction':{'parts':[{'text':'You record tiny conversational acknowledgment sounds. Produce exactly one soft, warm, short closed-mouth mm-hmm, with a gently rising, attentive intonation. Under one second. No other words, explanation, greeting, laughter or sound effects.'}]}}}))
        if 'setupComplete' not in json.loads(await asyncio.wait_for(ws.recv(),20)): raise RuntimeError('Voice setup failed')
        await ws.send(json.dumps({'clientContent':{'turns':[{'role':'user','parts':[{'text':'Record one soft mm-hmm now.'}]}],'turnComplete':True}}))
        pcm=bytearray();caption=''
        async with asyncio.timeout(25):
            async for raw in ws:
                content=json.loads(raw).get('serverContent',{})
                caption+=content.get('outputTranscription',{}).get('text','')
                for p in content.get('modelTurn',{}).get('parts',[]):
                    if p.get('inlineData',{}).get('mimeType','').startswith('audio/pcm'):pcm.extend(base64.b64decode(p['inlineData']['data']))
                if content.get('turnComplete') and pcm: break
    if len(pcm)>48000*2 or not pcm: raise RuntimeError('Acknowledgment must be short and nonempty')
    if re.sub('[^a-z]','',caption.lower()) not in ('mmhmm','mhm','hmm','mm','mhhm','mhhmm','mhmm','mhmh'):
        raise RuntimeError('Unexpected acknowledgment transcript: '+caption)
    samples=list(struct.unpack('<'+'h'*(len(pcm)//2),pcm))
    voiced=[i for i in range(0,len(samples),240) if max(map(abs,samples[i:i+240]),default=0)>250]
    if not voiced: raise RuntimeError('Acknowledgment is silent')
    samples=samples[max(0,voiced[0]-240):min(len(samples),voiced[-1]+480)]
    peak=max(map(abs,samples));scale=min(1,22000/peak)
    samples=[int(x*scale) for x in samples]
    # Tiny fades prevent a click at a trimmed sample boundary.
    for i in range(min(120,len(samples)//2)):
        samples[i]=int(samples[i]*i/120);samples[-i-1]=int(samples[-i-1]*i/120)
    output.parent.mkdir(parents=True,exist_ok=True)
    with wave.open(str(output),'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(24000);w.writeframes(struct.pack('<'+'h'*len(samples),*samples))
    return {'voice':voice,'path':str(output.relative_to(ROOT)),'seconds':round(len(samples)/24000,3),'caption':caption,'provider':config['live_model']}


async def main():
    results=[]
    for voice in VOICES:
        result=await generate(voice);results.append(result);print(json.dumps(result),flush=True)
    (ROOT/'web'/'sounds'/'sources.json').write_text(json.dumps(results,indent=2),encoding='utf-8')

if __name__=='__main__':asyncio.run(main())
