"""Master both cuts, then decode every exported frame and verify containers."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parent;OUT=ROOT/'output'
DURATION=43

def run(args):return subprocess.run(args,check=True,capture_output=True,text=True).stdout

def finish():
 master=OUT/'THREAD-Keep-going-soundtrack.wav'
 pre=ROOT/'audio/mix-premaster.wav'
 a=subprocess.run(['ffmpeg','-hide_banner','-i',str(pre),'-af','loudnorm=I=-16:TP=-1.2:LRA=8:print_format=json','-f','null','-'],capture_output=True,text=True,check=True)
 stats=json.loads(re.findall(r'\{[\s\S]*?\}',a.stderr)[-1])
 filt='loudnorm=I=-16:TP=-1.2:LRA=8:linear=true:'+':'.join(f'{dst}={stats[src]}' for dst,src in [('measured_I','input_i'),('measured_TP','input_tp'),('measured_LRA','input_lra'),('measured_thresh','input_thresh'),('offset','target_offset')])
 run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(pre),'-af',filt,'-ar','48000','-c:a','pcm_s24le',str(master)])
 (OUT/'loudness-input.json').write_text(json.dumps(stats,indent=2))
 manifest=[]
 for shape,w,h in [('landscape',2560,1440),('vertical',1080,1920)]:
  target=OUT/f'THREAD-Keep-going-{shape}.mp4'
  run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(OUT/f'{shape}-silent.mp4'),'-i',str(master),'-i',str(OUT/'THREAD-Keep-going.srt'),'-map','0:v:0','-map','1:a:0','-map','2:s:0','-c:v','copy','-c:a','aac','-b:a','320k','-ar','48000','-c:s','mov_text','-metadata:s:s:0','language=eng','-disposition:s:0','0','-metadata','title=THREAD — Keep going.','-metadata','comment=Cinematic feature film. Sample flights, dated public data. Directed synthetic voices; original music. M87 image: EHT Collaboration via ESO.','-t',str(DURATION),'-movflags','+faststart',str(target)])
  info=json.loads(run(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(target)]))
  v=next(s for s in info['streams'] if s['codec_type']=='video');au=next(s for s in info['streams'] if s['codec_type']=='audio')
  assert(v['width'],v['height'],v['r_frame_rate'],v['pix_fmt'])==(w,h,'60/1','yuv420p')
  assert abs(float(info['format']['duration'])-DURATION)<.05
  assert(au['sample_rate'],au['channels'])==('48000',2)
  assert int(v['nb_frames'])==DURATION*60
  run(['ffmpeg','-v','error','-i',str(target),'-f','null','-'])
  meter=subprocess.run(['ffmpeg','-hide_banner','-i',str(target),'-vn','-af','loudnorm=I=-16:TP=-1:LRA=8:print_format=json','-f','null','-'],capture_output=True,text=True,check=True)
  actual=json.loads(re.findall(r'\{[\s\S]*?\}',meter.stderr)[-1])
  manifest.append(dict(file=target.name,duration=DURATION,width=w,height=h,fps=60,frames=DURATION*60,full_decode='passed',audio_lufs=float(actual['input_i']),audio_true_peak_db=float(actual['input_tp']),bytes=target.stat().st_size,sha256=hashlib.sha256(target.read_bytes()).hexdigest()))
 (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2))
 print(json.dumps(manifest,indent=2))

if __name__=='__main__':finish()
