"""A 120 BPM original score and a tightly timed, interruptible conversation."""
import json
import math
from pathlib import Path
import subprocess
import sys

import numpy as np
from scipy import signal

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent))
from sound import read,write,trim,put,glass,soft_pad,whoosh,stamp,freq,SR
from voices import LINES

DURATION=43.;N=round(SR*DURATION)
RNG=np.random.default_rng(2704)

def env(seconds,attack,decay):
 t=np.arange(round(seconds*SR))/SR
 return t,(1-np.exp(-t/attack))*np.exp(-t/decay)*np.clip((seconds-t)/.02,0,1)

def kick():
 t,e=env(.35,.0008,.074)
 return np.tanh(1.3*np.sin(2*np.pi*(47*t+49*(1-np.exp(-t*45))/45)))*e

def snare():
 t,e=env(.22,.0004,.043)
 noise=signal.sosfilt(signal.butter(2,[1100,7600],btype='bandpass',fs=SR,output='sos'),RNG.normal(0,1,len(t)))
 return (noise*.58+np.sin(2*np.pi*181*t)*np.exp(-t*35)*.35)*e

def hat(opened=False):
 t,e=env(.18 if opened else .055,.0003,.047 if opened else .012)
 noise=signal.sosfilt(signal.butter(2,7800,btype='highpass',fs=SR,output='sos'),RNG.normal(0,1,len(t)))
 return noise*e

def bass(note,seconds=.25):
 t,e=env(seconds,.007,.14);f=freq(note)
 osc=np.sin(math.tau*f*t)+.20*np.sin(math.tau*f*2*t)+.07*np.sin(math.tau*f*3*t)
 return np.tanh(osc)*e

def pluck(note):
 t,e=env(.7,.002,.15);f=freq(note)
 return (np.sin(math.tau*f*t)+.23*np.sin(math.tau*f*2.003*t)+.055*np.sin(math.tau*f*4.002*t))*e

def build():
 (ROOT/'output').mkdir(parents=True,exist_ok=True)
 voice=np.zeros((N,2));music=np.zeros_like(voice);fx=np.zeros_like(voice)
 cues=list(LINES)+[('reply_take2',3.14,1.02,'Here are the best—'),('confirm',5.10,2.85,'Mumbai. Same date. Same time.'),('close',39.03,2.93,'Ask. Interrupt. Keep going. Thread.')]
 edits=[]
 for name,start,budget,words in sorted(cues,key=lambda row:row[1]):
  a=trim(read(ROOT/'audio'/f'{name}.wav'));original=len(a)/SR;speed=1.
  if name=='reply_take2':
   a=a[:round(budget*SR)];a[-round(.080*SR):]*=np.linspace(1,0,round(.080*SR))
  elif original>budget:
   speed=original/budget
   if speed>1.18:raise ValueError(f'{name}: delivery does not fit naturally ({speed:.2f}x)')
   write(ROOT/'audio/fit-input.wav',a)
   subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(ROOT/'audio/fit-input.wav'),'-af',f'atempo={speed}','-ar',str(SR),str(ROOT/'audio/fit-output.wav')],check=True)
   a=read(ROOT/'audio/fit-output.wav')
  a=signal.sosfilt(signal.butter(2,85,btype='highpass',fs=SR,output='sos'),a)
  level=np.sqrt(signal.lfilter(np.ones(960)/960,[1],a*a)+1e-10)
  a*=np.minimum(1.,(.14/np.maximum(level,.001))**.35)
  active=a[np.abs(a)>.01];a*=.15/max(.01,np.sqrt(np.mean(active*active)))
  a=np.tanh(a*.8)/.8
  k=min(300,len(a)//2);a[:k]*=np.linspace(0,1,k);a[-k:]*=np.linspace(1,0,k)
  put(voice,a,start,1.18)
  # Close, dark reflections only on the assistant. User stays clear and dry.
  if name in ['confirm','close']:
   low=signal.sosfilt(signal.butter(1,3100,fs=SR,output='sos'),a)
   for delay,gain,pan in [(.045,.025,-.5),(.078,.018,.5)]:put(fx,low,start+delay,gain,pan)
  edits.append(dict(take=name,start=start,end=start+len(a)/SR,source_seconds=original,tempo_factor=speed,text=words))

 # F minor 9 / Db major 9 / Ab major 9 / Eb suspended. 120 BPM; 84 beats.
 roots=[41,37,44,39]
 chords=[[53,56,60,67],[49,53,56,63],[56,60,63,70],[51,56,58,65]]
 for bar in range(21):
  at=bar*2.;c=chords[(bar//2)%4]
  put(music,soft_pad(c,3.8),at-.35,.052)
 for i,at in enumerate(np.arange(0,39.5,.5)):
  put(music,kick(),at,.13 if at>=8 else .10)
  if i%2:put(music,snare(),at,.086,-.08)
  root=roots[(i//8)%4]
  for offset,note,gain in [(.0,root,.075),(.25,root+12,.043),(.375,root+7,.028)]:
   put(music,bass(note),at+offset,gain)
  for j in range(4):
   put(music,hat(j==2 and i%2==1),at+j*.125,.026 if j%2==0 else .013,(-1)**j*.5)
  # Syncopated upper motif; restrained under speech, opens in the result holds.
  note=chords[(i//8)%4][[0,2,1,3,2,1,3,2][i%8]]+12
  if i%4!=0:
   p=pluck(note);put(music,p,at+.125,.034,(-1)**i*.42)
   put(music,p,at+.3125,.010,(-1)**(i+1)*.5)
 for at in [0,8,11,14,17,21,24,27,29.5,32,36]:
  put(fx,whoosh(.3),at-.19,.58)
  put(fx,glass(77 if at!=17 else 80,.65),at+.025,.020)
 # The interruption is carried by the voices and the short rhythmic notch.
 for at in [4.79,8.45,11.55,12.1,12.65,15.,15.17,15.34,15.51,15.96,18.18,22.51,27.53,30.86,35.03,36.42]:
  put(fx,pluck(84 if at!=4.79 else 89),at,.042,.12)
 # The final spoken words each get a precise musical accent.
 for at,note in [(39.03,77),(39.53,80),(40.29,84),(40.99,89)]:
  put(fx,glass(note,2.4),at,.073,0.)
 put(music,soft_pad([53,56,60,67],3.1),39.9,.10)
 put(music,bass(41,1.2),40.99,.095)
 timeline=np.arange(N)/SR;duck=np.ones(N)
 for e in edits:
  depth=.68 if e['take']=='reply_take2' else .58
  d=np.minimum(np.clip((timeline-e['start']+.08)/.10,0,1),np.clip((e['end']+.18-timeline)/.22,0,1))
  duck=np.minimum(duck,1-depth*d)
 notch=1-.87*np.minimum(np.clip((timeline-4.015)/.014,0,1),np.clip((4.24-timeline)/.12,0,1))
 music*=duck[:,None]*notch[:,None]
 music[timeline<38.5]*=10**(-1.5/20)
 fx*=.84*(.72+.28*duck)[:,None]
 fade=np.clip(timeline/.025,0,1)*np.clip((DURATION-timeline)/.45,0,1)**1.3
 for a in [voice,music,fx]:a*=fade[:,None]
 for name,a in [('voice-stem',voice),('music-stem',music),('effects-stem',fx),('mix-premaster',voice+music+fx)]:write(ROOT/'audio'/f'{name}.wav',a)
 (ROOT/'audio/edit.json').write_text(json.dumps({'duration':DURATION,'sample_rate':SR,'cues':edits,'score':'Original composition. F minor / Db / Ab / Eb, 120 BPM.','synthetic_voices':True},indent=2),encoding='utf-8')
 (ROOT/'output/THREAD-Keep-going.srt').write_text('\n'.join(f"{i}\n{stamp(e['start'])} --> {stamp(e['end'])}\n{e['text']}\n" for i,e in enumerate(edits,1)),encoding='utf-8')
 print(json.dumps(edits,indent=2));print('Premaster peak:',round(20*np.log10(np.max(np.abs(voice+music+fx))),2),'dBFS')

if __name__=='__main__':build()
