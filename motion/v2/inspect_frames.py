"""Contact sheets from actual encoded frames, including sub-second transitions."""
import argparse
from pathlib import Path
import subprocess
from PIL import Image,ImageDraw

ROOT=Path(__file__).resolve().parent
p=argparse.ArgumentParser();p.add_argument('--vertical',action='store_true');args=p.parse_args()
shape='vertical' if args.vertical else 'landscape'
source=ROOT/'output'/f'THREAD-Keep-going-{shape}.mp4'
times=[1.4,3.8,4.48,4.65,4.85,6.6,7.86,7.94,8.,8.06,8.14,9.6,12.6,16.4,19.3,22.9,25.6,28.5,31.2,33.1,35.3,37.7,39.3,39.8,40.2,40.55,41.2,42.85]
indices=sorted(set(round(t*60) for t in times));fps='60'
select='+'.join(f'eq(n,{n})' for n in indices)
subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(source),'-vf',f"select='{select}'",'-fps_mode','vfr',str(ROOT/'stills'/f'{shape}-encoded-%03d.jpg')],check=True)
tw,th,cols=(270,480,7) if args.vertical else (480,270,4)
rows=(len(indices)+cols-1)//cols
im=Image.new('RGB',(cols*tw,rows*(th+26)),(24,30,40));d=ImageDraw.Draw(im)
for i,n in enumerate(indices):
 x=(i%cols)*tw;y=(i//cols)*(th+26)
 a=Image.open(ROOT/'stills'/f'{shape}-encoded-{i+1:03d}.jpg').resize((tw,th))
 im.paste(a,(x,y));d.text((x+9,y+th+4),f'{n/60:.3f}s',fill='white')
im.save(ROOT/'stills'/f'{shape}-encoded-contact.jpg',quality=94)
print(ROOT/'stills'/f'{shape}-encoded-contact.jpg')
