"""Master, export, and inspect deliverable containers after rendering."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'output'

def run(args):
    return subprocess.run(args,check=True,capture_output=True,text=True).stdout

def stamp(seconds):
    ms=round(seconds*1000);h,ms=divmod(ms,3600000);m,ms=divmod(ms,60000);s,ms=divmod(ms,1000)
    return f'{h:02}:{m:02}:{s:02},{ms:03}'

def finish():
    master=OUT/'THREAD-soundtrack.wav'
    if not master.exists():
        # Two-pass loudness normalization, derived from the current soundtrack.
        a=subprocess.run(['ffmpeg','-hide_banner','-i',str(ROOT/'audio/mix-premaster.wav'),'-af','loudnorm=I=-16:TP=-1.2:LRA=9:print_format=json','-f','null','-'],capture_output=True,text=True,check=True)
        stats=json.loads(re.findall(r'\{[\s\S]*?\}',a.stderr)[-1])
        filt='loudnorm=I=-16:TP=-1.2:LRA=9:linear=false:'+':'.join(f'{dst}={stats[src]}' for dst,src in [('measured_I','input_i'),('measured_TP','input_tp'),('measured_LRA','input_lra'),('measured_thresh','input_thresh'),('offset','target_offset')])
        run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(ROOT/'audio/mix-premaster.wav'),'-af',filt,'-ar','48000','-c:a','pcm_s24le',str(master)])
    vertical_audio=OUT/'THREAD-vertical-soundtrack.wav'
    run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(master),'-filter_complex','[0:a]atrim=0:25.6,asetpts=PTS-STARTPTS,afade=t=out:st=25.57:d=0.03[a];[0:a]atrim=34.6:58,asetpts=PTS-STARTPTS,afade=t=in:st=0:d=0.03[b];[a][b]concat=n=2:v=0:a=1[out]','-map','[out]','-ar','48000','-c:a','pcm_s24le',str(vertical_audio)])
    cues=json.loads((ROOT/'audio/edit.json').read_text())['cues']
    vc=[]
    for e in cues:
        if e['take']=='07_core':continue
        shift=9. if e['start']>=34.6 else 0.
        vc.append(dict(e,start=e['start']-shift,end=e['end']-shift))
    (OUT/'THREAD-Keep-the-thread-vertical.srt').write_text('\n'.join(f"{i}\n{stamp(e['start'])} --> {stamp(e['end'])}\n{e['text']}\n" for i,e in enumerate(vc,1)),encoding='utf-8')
    manifest=[]
    for shape,duration,audio,subtitle in [('landscape',58.,master,OUT/'THREAD-Keep-the-thread.srt'),('vertical',49.,vertical_audio,OUT/'THREAD-Keep-the-thread-vertical.srt')]:
        target=OUT/f'THREAD-Keep-the-thread-{shape}.mp4'
        run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(OUT/f'{shape}-silent.mp4'),'-i',str(audio),'-i',str(subtitle),'-map','0:v:0','-map','1:a:0','-map','2:s:0','-c:v','copy','-c:a','aac','-b:a','320k','-ar','48000','-c:s','mov_text','-metadata:s:s:0','language=eng','-disposition:s:0','0','-metadata','title=THREAD — Keep the thread.','-metadata','comment=Directed synthetic narration; original score and motion design. Illustrated flight interaction uses demo data. Actual app screens recorded on Galaxy S24.','-t',str(duration),'-movflags','+faststart',str(target)])
        info=json.loads(run(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(target)]))
        video=next(s for s in info['streams'] if s['codec_type']=='video')
        aud=next(s for s in info['streams'] if s['codec_type']=='audio')
        assert video['r_frame_rate']=='60/1'
        assert abs(float(info['format']['duration'])-duration)<.05
        assert video['pix_fmt']=='yuv420p' and aud['sample_rate']=='48000' and aud['channels']==2
        assert video['width']==(2560 if shape=='landscape' else 1080)
        assert video['height']==(1440 if shape=='landscape' else 1920)
        run(['ffmpeg','-v','error','-i',str(target),'-f','null','-'])
        manifest.append({'file':target.name,'duration':duration,'width':video['width'],'height':video['height'],'fps':60,'video_codec':video['codec_name'],'audio_codec':aud['codec_name'],'audio_sample_rate':48000,'audio_channels':2,'size_bytes':target.stat().st_size,'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'full_decode':'passed','soft_captions':True})
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps(manifest,indent=2))

if __name__=='__main__':finish()
