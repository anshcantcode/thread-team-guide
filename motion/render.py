"""Deterministic GPU motion design for THREAD. Render stills before the full film.

The edit is in seconds, composed at 1920x1080 or 1080x1920 logical pixels.
GPU rendering, not a screen recording; all output frames have explicit times.
"""
import argparse
from functools import lru_cache
import math
from pathlib import Path
import subprocess
import time as clock

import moderngl
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parent
REPO=ROOT.parent
DURATION=58.0
WHITE=(245,247,252)
BLUE=(169,199,245)
MUTED=(122,145,175)

def smooth(x):
    x=max(0.,min(1.,x));return x*x*(3.-2.*x)
def ease(x):
    return 1.-(1.-max(0.,min(1.,x)))**4
def window(t,a,b,r=.6):
    return smooth((t-a)/r)*smooth((b-t)/r)

class Film:
    def __init__(self,w,h):
        self.w,self.h=w,h
        self.vertical=h>w
        self.W,self.H=(1080,1920) if self.vertical else (1920,1080)
        self.ratio=w/self.W
        self.ctx=moderngl.create_standalone_context()
        self.ctx.enable(moderngl.BLEND)
        self.ctx.blend_func=moderngl.SRC_ALPHA,moderngl.ONE_MINUS_SRC_ALPHA
        self.fbo=self.ctx.simple_framebuffer((w,h),components=3)
        self.fbo.use()
        self.quad=self.ctx.buffer(np.array([-1,-1,1,-1,-1,1,1,1],dtype='f4').tobytes())
        self.bg=self.ctx.program(vertex_shader='''#version 330
            in vec2 pos; void main(){gl_Position=vec4(pos,0,1);}''',fragment_shader=(ROOT/'scene.frag').read_text())
        self.bgvao=self.ctx.simple_vertex_array(self.bg,self.quad,'pos')
        self.bg['resolution']=(w,h)
        self.sprite=self.ctx.program(vertex_shader='''#version 330
            in vec2 pos; uniform vec4 rect; uniform vec2 canvas; uniform float angle;
            out vec2 uv; void main(){uv=(pos+1.)*.5; vec2 q=pos*rect.zw*.5;
            q=mat2(cos(angle),sin(angle),-sin(angle),cos(angle))*q;
            vec2 px=rect.xy+rect.zw*.5+q;
            gl_Position=vec4(px/canvas*2.-1.,0,1);}''',fragment_shader='''#version 330
            in vec2 uv; uniform sampler2D tex; uniform vec4 tint; out vec4 color;
            void main(){color=texture(tex,uv)*tint;}''')
        self.spvao=self.ctx.simple_vertex_array(self.sprite,self.quad,'pos')
        self.sprite['canvas']=(self.W,self.H)
        self.sprite['tex']=4
        self.textures={}
        for name,path in {
            'macro':ROOT/'assets/optical-macro.png',
            'sphere':REPO/'web/images/thread-sphere.png',
            'home':ROOT/'assets/screens/home.png',
            'correction':ROOT/'assets/screens/correction.png',
            'sports':ROOT/'assets/screens/sports.png',
            'search':ROOT/'assets/screens/search.png',
            'widget':ROOT/'assets/screens/widget.png',
        }.items():self.textures[name]=self.texture(Image.open(path))
        self.textures['macro'].use(0);self.bg['macroTex']=0
        self.textures['sphere'].use(1);self.bg['sphereTex']=1
        self.bg['screenTex']=2
        self.blank=self.texture(Image.new('RGBA',(1,1),'white'))
        print('GPU:',self.ctx.info['GL_RENDERER'],flush=True)

    def texture(self,im):
        im=im.convert('RGBA').transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        tex=self.ctx.texture(im.size,4,im.tobytes())
        tex.filter=(moderngl.LINEAR,moderngl.LINEAR)
        tex.repeat_x=tex.repeat_y=False
        return tex

    @lru_cache(maxsize=300)
    def text_texture(self,s,size,weight,tracking):
        ss=max(1.5,self.ratio)
        font=ImageFont.truetype(str(REPO/'web/fonts/Manrope.ttf'),round(size*ss))
        font.set_variation_by_axes([weight])
        pad=round(10*ss)
        widths=[font.getlength(ch) for ch in s]
        width=math.ceil(sum(widths)+tracking*ss*max(0,len(s)-1)+2*pad)
        height=math.ceil(size*ss*1.52)+pad*2
        im=Image.new('RGBA',(max(width,1),height))
        dr=ImageDraw.Draw(im);x=pad
        # Fixed baseline preserves alignment between separately animated words.
        for ch,ww in zip(s,widths):
            dr.text((x,pad+size*ss),ch,font=font,fill='white',anchor='ls')
            x+=ww+tracking*ss
        return self.texture(im),width/ss,height/ss,pad/ss

    def spr(self,tex,x,y,w,h,alpha=1.,color=WHITE,angle=0.):
        if alpha<.002:return
        tex.use(4)
        self.sprite['rect']=(x,self.H-y-h,w,h)
        self.sprite['angle']=angle
        self.sprite['tint']=tuple(c/255 for c in color)+(alpha,)
        self.spvao.render(moderngl.TRIANGLE_STRIP)

    def text(self,s,x,y,size=80,weight=500,color=WHITE,alpha=1.,tracking=-2.,align='left',z=1.):
        if alpha<.002:return 0
        tex,w,h,pad=self.text_texture(s,size,weight,tracking)
        ww=(w-2*pad)*z
        if align=='center':x-=ww/2
        elif align=='right':x-=ww
        self.spr(tex,x-pad*z,y-pad*z,w*z,h*z,alpha,color)
        return ww

    def line(self,x,y,w,alpha=1.,color=BLUE,h=1.5):
        self.spr(self.blank,x,y,w,h,alpha,color)

    def dot(self,x,y,r=5,alpha=1.,color=BLUE):
        if 'dot' not in self.textures:
            im=Image.new('RGBA',(64,64));ImageDraw.Draw(im).ellipse((1,1,63,63),fill='white')
            self.textures['dot']=self.texture(im)
        self.spr(self.textures['dot'],x-r,y-r,r*2,r*2,alpha,color)

    def background(self,t,mode=2,intensity=0.,center=(0.,0.),scale=1.,angles=(0.,0.,0.),screen='home',opacity=1.):
        self.bg['time']=t
        self.bg['mode']=mode
        self.bg['intensity']=intensity
        self.bg['layerAlpha']=opacity
        self.bg['center']=center
        self.bg['scale']=scale
        self.bg['angles']=angles
        self.textures[screen].use(2)
        self.bgvao.render(moderngl.TRIANGLE_STRIP)

    def tag(self,s,x,y,alpha=1.,color=BLUE):
        self.text(s,x,y,17 if not self.vertical else 21,500,color,alpha,3.)

    def lines(self,words,x,y,size=100,delay=0.,local=1.,gap=1.14,alpha=1.,color=WHITE,weight=500,align='left'):
        for i,s in enumerate(words):
            k=ease((local-delay-i*.12)/.85)
            self.text(s,x,y+i*size*gap+(1-k)*36,size,weight,color,alpha*k,-size*.037,align)

    def frame(self,t):
        V=self.vertical;W,H=self.W,self.H
        # Full film in landscape. Vertical has its own spatial choreography.
        if t<7.5:
            a=window(t,0.,7.5,.7)
            self.background(t,0,.88)
            if t>7.:
                self.background(t,1,1.,(0.,.06 if V else .09),(.50 if V else .76)+.40,opacity=smooth(t-7.))
            self.spr(self.blank,0,0,W,H,1-smooth(t/.7),(0,0,0))
            self.tag('T H R E A D',82 if V else 104,105 if V else 74,a)
            self.tag('A NEW WAY TO KEEP UP',82 if V else 104,162 if V else 130,a*.62)
            if t<4.4:
                if V:
                    self.lines(['Life doesn’t','move in a','straight line.'],78,575,94,local=t-.9,alpha=window(t,.8,4.5,.5))
                else:
                    self.lines(['Life doesn’t move','in a straight line.'],106,362,105,local=t-.8,alpha=window(t,.7,4.5,.5))
            else:
                self.lines(['Neither','should your','assistant.'] if V else ['Neither should','your assistant.'],78 if V else 106,580 if V else 365,96 if V else 107,local=t-4.3,alpha=window(t,4.25,7.45,.45))
            self.line(82 if V else 108,1710 if V else 936,(W-164 if V else 1704)*smooth(t/7.5),a*.4)

        elif t<11.4:
            u=t-7.5;a=window(t,7.5,11.4,.45)
            scale=(.50 if V else .76)+(1-ease(u/1.2))*.40
            if t<8.:self.background(t,0,.88)
            self.background(t,1,smooth((11.4-t)/.45),(0.,.06 if V else .09),scale,opacity=smooth(t-7.))
            self.tag('MEET',W/2-38,350 if V else 98,window(t,7.8,11.3,.4))
            self.text('THREAD',W/2,1290 if V else 781,100 if V else 104,400,WHITE,a,15 if V else 20,'center')
            self.text('Your day, in conversation.',W/2,1460 if V else 948,30 if V else 26,400,BLUE,a,-.5,'center')

        elif t<25.6:
            self.background(t,2,.45 if t<17.85 else (.06 if t<19.8 else .65),center=(0.,-.12 if V else -.05),scale=.55)
            a=window(t,11.4,25.6,.5)
            self.tag('ONE CONVERSATION',74 if V else 106,105 if V else 74,a)
            self.tag('ILLUSTRATED INTERACTION',74 if V else 1454,165 if V else 74,a*.52)
            if t<17.9:
                u=t-11.4
                self.text('Find flights',74 if V else 108,330 if V else 235,68 if V else 61,400,BLUE,a*ease(u/.5),-1.5)
                if V:
                    self.lines(['Chennai','to Delhi.'],74,470,123,local=u-.6,alpha=a)
                else:
                    self.lines(['Chennai to Delhi.'],105,320,129,local=u-.6,alpha=a)
                self.text('Tomorrow. After 21:00.',74 if V else 110,860 if V else 503,42 if V else 38,400,BLUE,a*ease((u-1.9)/.6),-1.)
                # Explicitly show what the assistant is doing before the cut.
                self.tag('THREAD',74 if V else 110,1170 if V else 746,a*window(t,15.55,17.9,.25))
                self.text('“I found a few flights to Delhi…”',74 if V else 110,1230 if V else 798,36 if V else 35,400,MUTED,a*window(t,15.55,17.9,.25),-1.)
            elif t<20.3:
                u=t-17.9
                # The interruption arrests the old movement and takes the frame.
                k=ease(u/.35)
                self.text('Wait.',W/2,470 if V else 215,206 if V else 233,560,WHITE,a*k,-10.,'center',z=1+(1-k)*.09)
                self.text('Mumbai instead.',W/2,830 if V else 542,88 if V else 93,400,BLUE,a*ease((u-.37)/.5),-3.4,'center')
                self.line(W*.13,1170 if V else 755,W*.74*smooth((u-.1)/.45),.7,(105,172,255))
            else:
                u=t-20.3;k=ease(u/.7)
                self.tag('DESTINATION UPDATED',74 if V else 110,300 if V else 220,a*k)
                if V:self.lines(['Chennai','to Mumbai.'],74,445,117,local=u,alpha=a)
                else:self.lines(['Chennai to Mumbai.'],105,323,123,local=u,alpha=a)
                self.line(78 if V else 110,858 if V else 532,(W-156 if V else 1696)*k,a*.25)
                rows=[('ORIGIN','Chennai'),('DATE','Tomorrow'),('AFTER','21:00')]
                for i,(label,value) in enumerate(rows):
                    xx=78 if V else 112+i*450
                    yy=967+i*177 if V else 620
                    ka=ease((u-.35-i*.13)/.65)*a
                    self.tag(label,xx,yy,ka*.7)
                    self.text(value,xx,yy+39,52 if V else 43,400,WHITE,ka,-1.4)
                    self.text('kept',W-210 if V else xx+280,yy+50,27 if V else 22,400,BLUE,ka,-.3)
                self.dot(82 if V else 115,1570 if V else 856,4,a*k)
                self.text('Old request stopped. Context retained.',102 if V else 137,1544 if V else 830,28 if V else 24,400,BLUE,a*k,-.4)
            self.text('Illustrated interaction • Flight results use demo data',74 if V else 110,1770 if V else 998,20 if V else 17,400,MUTED,a,-.1)

        elif t<34.6:
            u=t-25.6;a=window(t,25.6,34.6,.5)
            self.background(t,2,.92,(0.,-.25 if V else -.22),1.25)
            self.tag('BUILT TO BE INTERRUPTED',76 if V else 106,111 if V else 79,a)
            if u<4.0:
                self.lines(['Change','your mind.'] if V else ['Change your mind.'],76 if V else 106,520 if V else 270,126 if V else 126,local=u,alpha=window(u,0.,4.3,.5))
                self.lines(['Keep','the details.'] if V else ['Keep the details.'],76 if V else 106,860 if V else 447,126 if V else 126,local=u-.95,alpha=window(u,0.,4.3,.5),color=BLUE)
            else:
                self.lines(['The right','task keeps','moving.'] if V else ['The right task','keeps moving.'],76 if V else 106,550 if V else 280,121 if V else 123,local=u-4.,alpha=window(u,3.9,9.,.5))
                if V:
                    self.text('Stop the old branch.',76,1165,28,400,BLUE,window(u,4.8,9.,.5),-.5)
                    self.text('Carry the context forward.',76,1220,28,400,BLUE,window(u,4.8,9.,.5),-.5)
                else:self.text('Stop the old branch. Carry the context forward.',111,638,29,400,BLUE,window(u,4.8,9.,.5),-.5)

        elif t<45.1:
            u=t-34.6;a=window(t,34.6,45.1,.5)
            section=0 if u<3.1 else (1 if u<5.7 else (2 if u<8.0 else 3))
            start=[0.,3.1,5.7,8.0][section];s=u-start
            screen=['search','sports','correction','widget'][section]
            titles=[['Find it.'],['See more.'],['Save it.'],['Keep it','close.']][section]
            sub=['Search, with the right next step.','Rich results worth exploring.','Your library. Your context.','Useful beyond the conversation.'][section]
            labels=['01 / SEARCH','02 / RICH RESULTS','03 / YOUR LIBRARY','04 / HOME-SCREEN WIDGETS']
            angle=(-.045+.035*math.sin(u*.22),(.32 if section%2==0 else -.25)+(-.06 if section%2==0 else .055)*s,(-.04 if section%2==0 else .032))
            if V:
                self.background(t,3,a,(.0,-.16),.665+(1-ease(s/1.))* .04,angle,screen)
                self.tag(labels[section],76,112,a)
                self.lines(titles,76,273,108,local=s,alpha=a)
                self.text(sub,76,577 if section==3 else 438,27,400,BLUE,a*ease(s/.5),-.5)
                self.text('Actual Galaxy S24 screen',W/2,1780,20,400,MUTED,a,-.1,'center')
            else:
                left=section==1
                self.background(t,3,a,(-.43 if left else .46,-.015),1.24+(1-ease(s/1.))* .08,angle,screen)
                xx=1070 if left else 107
                self.tag(labels[section],xx,82,a)
                self.lines(titles,xx,320,117,local=s,alpha=a)
                self.text(sub,xx+4,659 if section==3 else 507,28,400,BLUE,a*ease(s/.5),-.5)
                self.text('Actual Galaxy S24 screen',xx+4,958,19,400,MUTED,a,-.1)

        elif t<50.5:
            u=t-45.1;a=window(t,45.1,50.5,.6)
            if V:
                self.background(t,3,a,(0.,-.16),.665,(-.06,-.20+u*.035,.025),'home')
                self.lines(['On your phone.'],76,275,89,local=u,alpha=a)
                self.text('No laptop needed.',76,430,44,400,BLUE,a*ease((u-.5)/.7),-1.3)
            else:
                self.background(t,3,a,(.47,-.02),1.14,(-.06,-.20+u*.035,.025),'home')
                self.lines(['On your','phone.'],106,294,126,local=u,alpha=a)
                self.text('No laptop needed.',110,642,44,400,BLUE,a*ease((u-.5)/.7),-1.3)
            self.tag('THREAD FOR ANDROID',76 if V else 107,110 if V else 82,a)
            self.text('Cloud voice • Internet required',76 if V else 112,1780 if V else 958,20 if V else 19,400,MUTED,a,-.1)

        else:
            u=t-50.5;a=window(t,50.5,58.,.65)
            self.background(t,1,a,(0.,.075 if V else .035),.50 if V else .78)
            self.text('Go on.',W/2,334 if V else 165,60 if V else 45,400,BLUE,window(u,.05,3.3,.5),-1.8,'center')
            self.text('Keep the thread.',W/2,1310 if V else 818,83 if V else 94,450,WHITE,a*ease((u-.4)/1.),-3.,'center')
            self.text('THREAD',W/2,1510 if V else 980,28 if V else 23,500,BLUE,a,9.,'center')
            if u>6.65:self.spr(self.blank,0,0,W,H,smooth((u-6.65)/.85),(0,0,0))
        return self.fbo.read(components=3,alignment=1)

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--vertical',action='store_true')
    p.add_argument('--width',type=int)
    p.add_argument('--fps',type=int,default=60)
    p.add_argument('--stills',action='store_true')
    p.add_argument('--start',type=float,default=0.)
    p.add_argument('--end',type=float)
    p.add_argument('--output')
    args=p.parse_args()
    if args.end is None:args.end=49. if args.vertical else DURATION
    w=args.width or (1080 if args.vertical else 2560)
    h=round(w*(16/9 if args.vertical else 9/16));h+=h%2
    film=Film(w,h)
    if args.stills:
        for t in [2.8,5.9,9.5,14.8,18.85,22.8,28.4,31.9,36.6,39.8,43.4,47.7,54.5]:
            data=film.frame(t)
            im=Image.frombytes('RGB',(w,h),data).transpose(Image.Transpose.FLIP_TOP_BOTTOM)
            name=('vertical' if args.vertical else 'landscape')+f'-{t:04.1f}.jpg'
            im.save(ROOT/'stills'/name,quality=94)
        print('Saved 13 editorial keyframes.',flush=True)
        return
    target=Path(args.output) if args.output else ROOT/'output'/('vertical-silent.mp4' if args.vertical else 'landscape-silent.mp4')
    target.parent.mkdir(exist_ok=True,parents=True)
    cmd=['ffmpeg','-hide_banner','-loglevel','warning','-y','-f','rawvideo','-pixel_format','rgb24','-video_size',f'{w}x{h}','-framerate',str(args.fps),'-i','pipe:0','-vf','vflip,scale=in_range=pc:out_range=tv:out_color_matrix=bt709','-c:v','h264_nvenc','-preset','p6','-tune','hq','-rc','vbr','-cq','17','-b:v','0','-pix_fmt','yuv420p','-color_range','tv','-color_primaries','bt709','-color_trc','bt709','-colorspace','bt709','-movflags','+faststart',str(target)]
    start=clock.monotonic()
    proc=subprocess.Popen(cmd,stdin=subprocess.PIPE)
    count=round((args.end-args.start)*args.fps)
    try:
        for i in range(count):
            t=args.start+i/args.fps
            # Portrait retains the complete demo and product shots; removes the
            # nine-second explanatory beat already demonstrated by the correction.
            source_t=t+(9. if args.vertical and t>=25.6 else 0.)
            proc.stdin.write(film.frame(source_t))
            if i%120==0:print(f'{i}/{count} frames, {clock.monotonic()-start:.1f}s',flush=True)
        proc.stdin.close()
        code=proc.wait()
        if code:raise RuntimeError(f'FFmpeg failed with {code}')
    finally:
        if proc.poll() is None:proc.terminate()
    print('Rendered',target,round(clock.monotonic()-start,1),'seconds',flush=True)

if __name__=='__main__':main()
