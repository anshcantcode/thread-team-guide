"""One brisk performance for the character, with accurately separated takes."""
import json
import sys
from pathlib import Path
import wave
import numpy as np

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent))
import voice

LINES=[
 ('request',.10,3.75,'Thread. Chennai to Delhi. Tomorrow, after nine.'),
 ('change',4.02,1.48,'Actually, Mumbai.'),
 ('weather',8.04,1.4,'Weather there?'),
 ('plan',11.04,1.7,'Plan my morning.'),
 ('packing',14.02,2.45,'Make a packing list. Save it.'),
 ('sports',17.04,3.0,"Kohli's form. Just T20."),
 ('search',21.03,2.72,'Google cat images. Videos instead.'),
 ('research',24.04,2.6,'Find sources on black holes.'),
 ('split',27.02,2.2,'Split twelve hundred by four.'),
 ('timer',29.52,1.85,'Twenty-minute timer.'),
 ('clocks',32.04,3.65,'London and Mumbai. Make it a widget.'),
 ('recall',36.08,1.85,'Back to my trip.'),
]

def split():
 with wave.open(str(ROOT/'audio/user_performance.wav'),'rb') as w:
  sr=w.getframerate();pcm=np.frombuffer(w.readframes(w.getnframes()),'<i2')
 block=round(sr*.01)
 rms=np.sqrt(np.mean(pcm[:len(pcm)//block*block].astype(float).reshape(-1,block)**2,axis=1))
 quiet=rms<max(60.,rms.max()*.010)
 runs=[];start=None
 for i,q in enumerate(np.r_[quiet,False]):
  if q and start is None:start=i
  if not q and start is not None:
   a,b=start*.01,i*.01
   if a>.5 and b<len(pcm)/sr-.5 and b-a>.4:runs.append((a,b))
   start=None
 gaps=sorted(sorted(runs,key=lambda ab:ab[1]-ab[0],reverse=True)[:len(LINES)-1])
 if len(gaps)!=len(LINES)-1:raise RuntimeError(f'Expected {len(LINES)-1} separations; found {len(gaps)}. Inspect the performance.')
 bounds=[0]+[round((a+b)/2*sr) for a,b in gaps]+[len(pcm)]
 meta=[]
 for row,lo,hi in zip(LINES,bounds,bounds[1:]):
  name,at,budget,text=row
  a=pcm[lo:hi]
  with wave.open(str(ROOT/'audio'/f'{name}.wav'),'wb') as w:
   w.setparams((1,2,sr,0,'NONE',''));w.writeframes(a.tobytes())
  meta.append(dict(name=name,start=at,budget=budget,text=text,source_start=lo/sr,source_end=hi/sr))
 (ROOT/'audio/cues.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
 print(json.dumps(meta,indent=2))

if __name__=='__main__':
 voice.ROOT=ROOT
 voice.TAKES=[
  ('reply_take2','Charon','Here are the best options, starting with',
   'Bright responsive assistant. Speak briskly in one connected phrase, without a pause after options. This will be interrupted. Say only the transcript. Natural close studio delivery.'),
  ('reply','Charon','Flights to Delhi. Your first option leaves at',
   'Bright responsive assistant, quick conversational delivery. This sentence will be cut off by an interruption. Speak the exact transcript; no added ending. Clear dry recording, brisk pacing.'),
  ('user_performance','Aoede',' [long pause] '.join(row[3] for row in LINES),
   'A single confident young adult woman, consistent medium-high register and natural lightly Indian English accent throughout. Brisk, engaged and nimble, around 210 words per minute; conversational, never breathy or cinematic slow. These are separate command lines for a fast product film. IMPORTANT: leave TWO FULL SECONDS OF SILENCE at every [long pause] marker so the editor can separate them. Do not speak the marker. Within each line keep the phrasing quick and connected, even when there is punctuation. End each line clearly. Exact transcript only, no introduction, no added words.'),
  ('confirm','Charon','Mumbai. Same date. Same time.',
   'Crisp friendly assistant, brisk and responsive. Approximately two seconds. No long dramatic pauses. Bright, present, clear voice.'),
  ('close','Charon','Ask. Interrupt. Keep going. Thread.',
   'A confident energetic product-film signature. Clear and rhythmically crisp, around 2.7 seconds total. No drawn-out words, no breathy trailer delivery. Thread is one syllable.'),
 ]
 voice.generate(sys.argv[1:], config_path=ROOT.parents[1]/'.env', model='gemini-2.5-flash-preview-tts')
 if not sys.argv[1:] or 'user_performance' in sys.argv[1:]:split()
