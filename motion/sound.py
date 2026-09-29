"""Original score, editorial sound design, directed VO edit and caption sidecars."""
import json
from pathlib import Path
import subprocess
import wave

import numpy as np
from scipy import signal

ROOT=Path(__file__).resolve().parent
SR=48000
DURATION=58.
N=round(SR*DURATION)
RNG=np.random.default_rng(417)

def read(path):
    with wave.open(str(path),'rb') as w:
        a=np.frombuffer(w.readframes(w.getnframes()),'<i2').astype(np.float64)/32768
        rate=w.getframerate()
    return signal.resample_poly(a,SR,rate)

def write(path,a):
    with wave.open(str(path),'wb') as w:
        w.setparams((2 if a.ndim==2 else 1,2,SR,0,'NONE',''))
        w.writeframes(np.round(np.clip(a,-.999,.999)*32767).astype('<i2').tobytes())

def trim(a):
    # Only trim leading and trailing room silence, preserving natural pauses.
    block=480
    level=np.sqrt(np.mean(a[:len(a)//block*block].reshape(-1,block)**2,axis=1))
    active=np.where(level>max(.0018,np.max(level)*.015))[0]
    if not len(active):raise ValueError('Silent voice take')
    return a[max(0,(active[0]-5)*block):min(len(a),(active[-1]+11)*block)]

def put(track,a,start,gain=1.,pan=0.):
    if a.ndim==1:
        a=np.stack([a*np.sqrt((1-pan)/2),a*np.sqrt((1+pan)/2)],axis=1)
    at=round(start*SR)
    lo=max(0,-at);hi=min(len(a),len(track)-at)
    if hi>lo:track[max(0,at):at+hi]+=a[lo:hi]*gain

def freq(note):return 440.*2**((note-69)/12)

def glass(note,seconds=3.):
    t=np.arange(round(seconds*SR))/SR
    f=freq(note)
    tone=sum(np.sin(2*np.pi*f*h*t+idx*.6)*np.exp(-t*(1.4+idx*.65))*amp for idx,(h,amp) in enumerate([(1.,1.),(2.001,.24),(3.996,.07)]))
    return tone*(1-np.exp(-t*120))*np.minimum(1.,(seconds-t)*5.)

def soft_pad(notes,seconds):
    t=np.arange(round(seconds*SR))/SR
    y=np.zeros((len(t),2))
    for i,note in enumerate(notes):
        f=freq(note)
        for side,detune in [(0,.9987),(1,1.0013)]:
            phase=2*np.pi*f*detune*t+.45*np.sin(2*np.pi*.08*t+i)
            y[:,side]+=np.sin(phase)+.16*np.sin(phase*2.+.3)+.055*np.sin(phase*3.)
    env=np.sin(np.pi*np.clip(t/2,0,1)/2)**2*np.sin(np.pi*np.clip((seconds-t)/2.8,0,1)/2)**2
    return y*env[:,None]/len(notes)

def whoosh(seconds=.75,reverse=False):
    t=np.arange(round(seconds*SR))/SR
    noise=RNG.normal(0,1,len(t))
    noise=signal.sosfilt(signal.butter(2,[350,3500],btype='bandpass',fs=SR,output='sos'),noise)
    env=np.sin(np.pi*t/seconds)**2
    y=noise*env*.16+np.sin(2*np.pi*(185*t+70*t*t))*env*.026
    if reverse:y=y[::-1]
    pan=np.linspace(-.65,.65,len(y))
    return np.stack([y*np.sqrt((1-pan)/2),y*np.sqrt((1+pan)/2)],axis=1)

def stamp(seconds):
    ms=round(seconds*1000);h,ms=divmod(ms,3600000);m,ms=divmod(ms,60000);s,ms=divmod(ms,1000)
    return f'{h:02}:{m:02}:{s:02},{ms:03}'

def build():
    voice=np.zeros((N,2));music=np.zeros((N,2));fx=np.zeros((N,2))
    cues=[('01_open',.85,6.40),('02_meet',8.22,2.35),('03_request',11.82,3.88),('04_reply',15.73,2.20),('05_interrupt',17.90,2.35),('06_confirm',20.42,4.42),('07_core',25.98,8.18),('08_personal',35.18,9.25),('09_phone',45.72,4.04),('10_close',51.14,4.9)]
    edits=[]
    for name,start,budget in cues:
        a=trim(read(ROOT/'audio'/f'{name}.wav'))
        original=len(a)/SR
        speed=1.
        if name!='04_reply' and len(a)/SR>budget:
            speed=(len(a)/SR)/budget
            if speed>1.18:raise ValueError(f'{name} needs a new performance, not a rushed time stretch: {speed}')
            raw=ROOT/'audio'/f'{name}-trim.wav';write(raw,a)
            fit=ROOT/'audio'/f'{name}-fit.wav'
            subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(raw),'-af',f'atempo={speed}','-ar',str(SR),str(fit)],check=True)
            a=read(fit)
        a=signal.sosfilt(signal.butter(2,85,btype='highpass',fs=SR,output='sos'),a)
        # Gentle compression evens the directed takes without crushing consonants.
        envelope=np.sqrt(signal.lfilter([1/960]*960,[1],a*a)+1e-10)
        a*=np.minimum(1.,(.14/np.maximum(envelope,.001))**.35)
        active=a[np.abs(a)>.015]
        rms=np.sqrt(np.mean(active*active))
        a*=.125/max(rms,.01)
        a=np.tanh(a*.9)/.9
        if name=='04_reply':
            a=a[:round(budget*SR)]
            a[-round(.025*SR):]*=np.linspace(1,0,round(.025*SR))
            # A tiny falling granular echo makes the interruption audible.
            grain=a[-round(.075*SR):]
            for j in range(3):put(fx,signal.resample(grain,round(len(grain)*(1+j*.17))),17.925+j*.047,.22/(j+1),-.15+j*.15)
        else:
            k=min(round(.012*SR),len(a)//2)
            a[:k]*=np.linspace(0,1,k);a[-k:]*=np.linspace(1,0,k)
        put(voice,a,start,1.25,0.)
        # Short, dark room reflections; assistant and narrator remain intelligible.
        if name not in ['03_request','05_interrupt']:
            for delay,gain,pan in [(.053,.032,-.35),(.089,.024,.35),(.139,.016,-.2)]:
                put(fx,signal.sosfilt(signal.butter(1,2700,fs=SR,output='sos'),a),start+delay,gain,pan)
        meta=json.loads((ROOT/'audio'/f'{name}.json').read_text())
        words=meta['transcript']
        if name=='04_reply':words='I found a few flights to Delhi. The—'
        edits.append({'take':name,'start':start,'end':start+len(a)/SR,'source_seconds_trimmed':original,'tempo_factor':speed,'text':words})

    # Original harmonic score: F minor add9 / Db maj9 / Ab add9 / Eb sus.
    pad_sections=[(0.,11.8,[41,53,56,60,67],.09),(7.5,12.8,[37,49,53,56,63],.085),(20.3,8.0,[44,51,56,58,60],.11),(25.6,12.0,[39,51,55,58,65],.11),(34.6,13.3,[41,53,56,60,67],.12),(45.1,8.5,[37,49,53,56,63],.10),(50.5,7.5,[44,51,56,60,63],.12)]
    for at,sec,notes,gain in pad_sections:put(music,soft_pad(notes,sec),at,gain)
    beat=60/96
    # Soft analog pulse, sparse glass arpeggio, then an extra rhythmic layer.
    for i,at in enumerate(np.arange(7.5,50.5,beat)):
        if 17.65<at<20.3:continue
        t=np.arange(round(.42*SR))/SR
        sub=np.sin(2*np.pi*(48*t+28*(1-np.exp(-t*22))/22))*np.exp(-t*12)
        sub*=np.minimum(1.,t*300)
        if i%2==0:put(music,sub,at,.06 if at<34.6 else .075)
        if i%2==1:
            note=[65,72,68,75,72,68,63,67][i//2%8]
            put(music,glass(note,2.7),at,.019 if at<34.6 else .027,(-.6 if i%4==1 else .6))
        if 34.6<at<45.1:
            noise=RNG.normal(0,1,round(.045*SR))
            noise=signal.sosfilt(signal.butter(1,6500,btype='highpass',fs=SR,output='sos'),noise)
            noise*=np.exp(-np.arange(len(noise))/SR*100)
            put(music,noise,at+beat*.5,.012,(-1)**i*.55)

    for at in [7.5,11.4,25.6,34.6,37.7,40.3,42.6,45.1,50.5]:
        put(fx,whoosh(.64),at-.49,.65 if at in [7.5,25.6,50.5] else .38)
        t=np.arange(round(.65*SR))/SR
        put(fx,np.sin(2*np.pi*(45*t+25*(1-np.exp(-t*16))/16))*np.exp(-t*9)*(1-np.exp(-t*180)),at,.075)
    # The corrected request and closing brand share the same three-note signature.
    for at in [20.32,50.58,55.22]:
        for delay,note,gain,pan in [(0,77,.048,-.3),(.135,84,.038,.3),(.29,80,.036,0.)]:
            put(fx,glass(note,3.),at+delay,gain,pan)
    t=np.arange(N)/SR
    duck=np.ones(N)
    for e in edits:
        a=e['start'];b=e['end']
        env=np.minimum(np.clip((t-a+.15)/.2,0,1),np.clip((b+.27-t)/.3,0,1))
        duck=np.minimum(duck,1.-env*.38)
    cut=np.ones(N)
    a=round(17.90*SR);b=round(20.28*SR)
    cut[a:b]=.028
    cut[a-960:a]=np.linspace(1,.028,960)
    cut[b:b+round(.38*SR)]=np.linspace(.028,1,round(.38*SR))
    music*=duck[:,None]*cut[:,None]
    # Match the cut on the tail of earlier scene effects as well.
    fx[a:round(18.1*SR)]*=.18
    fadein=np.clip(t/.7,0,1)
    fadeout=np.clip((58.-t)/1.2,0,1)**1.4
    for a in [voice,music,fx]:a*=fadein[:,None]*fadeout[:,None]
    for name,a in [('voice-stem',voice),('music-stem',music),('effects-stem',fx),('mix-premaster',voice+music+fx)]:
        write(ROOT/'audio'/f'{name}.wav',a)
    (ROOT/'audio/edit.json').write_text(json.dumps({'sample_rate':SR,'duration':DURATION,'cues':edits,'score':'Original procedural composition, F minor / Db / Ab / Eb, 96 BPM','synthetic_voices':True},indent=2),encoding='utf-8')
    srt=[]
    for i,e in enumerate(edits,1):
        srt.append(f"{i}\n{stamp(e['start'])} --> {stamp(e['end'])}\n{e['text']}\n")
    (ROOT/'output/THREAD-Keep-the-thread.srt').write_text('\n'.join(srt),encoding='utf-8')
    print(json.dumps(edits,indent=2))
    print('Premaster peak',20*np.log10(np.max(np.abs(voice+music+fx))), 'dBFS')

if __name__=='__main__':build()
