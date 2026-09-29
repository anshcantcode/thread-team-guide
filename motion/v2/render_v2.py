"""THREAD / Keep going. Component animation, independent portrait composition.

Each result has its own choreography. Complementary 320 ms reveals share a
camera transform. Frames are evaluated at explicit times, without browser timing.
"""
import argparse
from functools import lru_cache
import json
import math
from pathlib import Path
import subprocess
import sys
import time

import moderngl
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent))
from render import Film, ease, smooth

INK=(8,13,20); PAPER=(242,246,252); WHITE=(245,248,255)
BLUE=(35,120,243); ICE=(169,199,245); MUTED=(141,158,183)
DARK=(22,37,62); GREY=(79,99,129); GREEN=(93,228,187)
DURATION=43.
CUTS=[0,8,11,14,17,21,24,27,29.5,32,36,39,43]

class Movie(Film):
 def __init__(self,w,h):
  super().__init__(w,h)
  self.transform=(0,0,1,1)
  self.base=self.ctx.program(vertex_shader='#version 330\nin vec2 pos;void main(){gl_Position=vec4(pos,0,1);}',fragment_shader=(ROOT/'backdrop.frag').read_text())
  self.basevao=self.ctx.simple_vertex_array(self.base,self.quad,'pos')
  self.base['resolution']=(w,h)
  self.images={}
  for name in ['mumbai','cat','kohli','indigo','airindia']:
   self.images[name]=Image.open(ROOT/'assets'/f'{name}.png').convert('RGBA')
  self.images['blackhole']=Image.open(ROOT/'assets/blackhole.jpg').convert('RGBA')
  self.weather=json.loads((ROOT/'assets/weather.json').read_text())['data']
  self.shots=[self.flights,self.weather_scene,self.itinerary,self.packing,self.sports,
              self.search,self.research,self.calculate,self.timer,self.clocks,self.recall,self.close]

 def spr(self,tex,x,y,w,h,alpha=1.,color=(255,255,255),angle=0.):
  dx,dy,z,a=self.transform
  super().spr(tex,(x-self.W/2)*z+self.W/2+dx,(y-self.H/2)*z+self.H/2+dy,w*z,h*z,alpha*a,color,angle)

 @lru_cache(maxsize=420)
 def text_texture(self,s,size,weight,tracking):
  ss=max(1.5,self.ratio);font=ImageFont.truetype(str(ROOT.parents[1]/'web/fonts/Manrope.ttf'),round(size*ss))
  font.set_variation_by_axes([weight]);pad=round(10*ss)
  # Whole-word shaping retains the font's kerning, unlike per-letter drawing.
  width=math.ceil(font.getlength(s)+2*pad);height=math.ceil(size*ss*1.6)+pad*2
  im=Image.new('RGBA',(max(width,1),height));dr=ImageDraw.Draw(im)
  dr.text((pad,pad+size*ss),s,font=font,fill='white',anchor='ls')
  return self.texture(im),width/ss,height/ss,pad/ss

 def txt(self,s,x,y,size=50,color=WHITE,weight=500,a=1.,align='left'):
  return self.text(str(s),x,y,size,weight,color,a,0,align)

 @lru_cache(maxsize=100)
 def rect_texture(self,w,h,r,fill,stroke=None):
  ss=2;im=Image.new('RGBA',(int(w*ss),int(h*ss)))
  dr=ImageDraw.Draw(im);dr.rounded_rectangle((1,1,w*ss-1,h*ss-1),radius=r*ss,fill=fill,outline=stroke,width=2 if stroke else 1)
  return self.texture(im)

 def rect(self,x,y,w,h,r=24,fill=DARK,a=1.,stroke=None):
  self.spr(self.rect_texture(round(w),round(h),r,fill,stroke),x,y,w,h,a)

 @lru_cache(maxsize=32)
 def photo_texture(self,name,w,h,r):
  im=ImageOps.fit(self.images[name],(w,h),method=Image.Resampling.LANCZOS)
  if r:
   mask=Image.new('L',im.size);ImageDraw.Draw(mask).rounded_rectangle((0,0,w,h),radius=r,fill=255);im.putalpha(mask)
  return self.texture(im)

 def photo(self,name,x,y,w,h,a=1.,r=0):
  self.spr(self.photo_texture(name,round(w),round(h),r),x,y,w,h,a)

 @lru_cache(maxsize=12)
 def icon_texture(self,name):
  im=Image.new('RGBA',(160,160));d=ImageDraw.Draw(im)
  if name=='plane':
   d.polygon([(8,70),(64,65),(75,13),(91,13),(96,64),(146,75),(150,84),(96,87),(91,144),(75,144),(64,89),(8,91),(22,81)],fill='white')
  elif name=='check':d.line([(26,82),(63,118),(136,40)],fill='white',width=13,joint='curve')
  elif name=='bookmark':d.line([(45,138),(45,23),(115,23),(115,138),(80,112),(45,138)],fill='white',width=8,joint='curve')
  elif name=='play':d.polygon([(57,36),(121,80),(57,124)],fill='white')
  elif name=='cloud':
   d.ellipse((40,26,112,103),fill='white');d.ellipse((12,65,84,125),fill='white');d.ellipse((85,54,151,125),fill='white');d.rectangle((41,81,119,125),fill='white')
  elif name=='arrow':d.line([(26,80),(130,80),(91,41),(130,80),(91,119)],fill='white',width=9,joint='curve')
  elif name=='plus':d.line([(80,32),(80,128)],fill='white',width=9);d.line([(32,80),(128,80)],fill='white',width=9)
  elif name=='pause':d.rounded_rectangle((48,39,67,121),7,fill='white');d.rounded_rectangle((94,39,113,121),7,fill='white')
  return self.texture(im)

 def icon(self,name,x,y,s=48,color=WHITE,a=1.,angle=0):
  self.spr(self.icon_texture(name),x,y,s,s,a,color,angle)

 def segment(self,x1,y1,x2,y2,color=BLUE,width=4,a=1.):
  length=math.hypot(x2-x1,y2-y1)
  if length<.01:return
  self.spr(self.blank,(x1+x2)/2-length/2,(y1+y2)/2-width/2,length,width,a,color,-math.atan2(y2-y1,x2-x1))

 def arc(self,x,y,r,start,end,color=BLUE,width=6,a=1.):
  if end<=start:return
  pts=np.linspace(start,end,max(2,round((end-start)*r/8)))
  for p,q in zip(pts,pts[1:]):self.segment(x+r*math.cos(p),y+r*math.sin(p),x+r*math.cos(q),y+r*math.sin(q),color,width,a)

 def brand(self,t):
  self.spr(self.textures['sphere'],62 if self.vertical else 75,70 if self.vertical else 36,52,52)
  self.txt('THREAD',128 if self.vertical else 141,77 if self.vertical else 39,27,ICE,650)
  # A short voice waveform gives the conversation a continuous visual presence.
  x=self.W-165;y=101 if self.vertical else 63
  for i in range(7):
   h=5+19*abs(math.sin(t*8+i*.9))*abs(math.sin(t*1.6+.4))
   self.rect(x+i*9,y-h/2,4,h,2,ICE,.75)

 def command(self,lines,u):
  if isinstance(lines,str):lines=[lines]
  x=70 if self.vertical else 104;y=220 if self.vertical else 125
  for i,s in enumerate(lines):
   k=ease((u-i*.07+.1)/.42)
   self.txt(s,x,y+i*(79 if self.vertical else 65)+(1-k)*30,64 if self.vertical else 53,WHITE,500,k)

 def rolling(self,old,new,k,x,y,size,color=DARK,align='left'):
  if k<=0:self.txt(old,x,y,size,color,600,align=align);return
  if k>=1:self.txt(new,x,y,size,color,600,align=align);return
  tw=max(self.text_texture(s,size,600,0)[1] for s in [old,new])+24
  xx=x-tw if align=='right' else x-tw/2 if align=='center' else x-12
  dx,dy,z,a=self.transform
  left=(xx-self.W/2)*z+self.W/2+dx;top=(y+size*.12-self.H/2)*z+self.H/2+dy
  prior=self.ctx.scissor
  self.ctx.scissor=(round(left*self.ratio),round((self.H-top-size*1.1*z)*self.ratio),round(tw*z*self.ratio),round(size*1.1*z*self.ratio))
  self.txt(old,x,y-size*1.22*k,size,color,600,align=align)
  self.txt(new,x,y+size*1.22*(1-k),size,color,600,align=align)
  self.ctx.scissor=prior

 def flights(self,u):
  V=self.vertical;change=smooth((u-4.32)/.60)
  if u<4:self.command(['Chennai to Delhi.','Tomorrow, after nine.'] if V else 'Chennai to Delhi. Tomorrow, after nine.',u)
  else:self.command('Actually, Mumbai.',u-4)
  x=70 if V else 170;y=(510 if V else 275)+(1-ease((u+.2)/.65))*90
  w=940 if V else 1580;h=845 if V else 554
  # Pale ticket stock with a perforated tear line. No decorative empty panel.
  self.rect(x+7,y+17,w,h,36,(2,5,10),.5)
  self.rect(x,y,w,h,32,PAPER)
  self.photo('indigo',x+44,y+32,70,70)
  self.txt('IndiGo',x+130,y+36,40 if V else 32,DARK,650)
  self.txt('Economy · Nonstop',x+44,y+130 if V else y+105,31 if V else 24,GREY)
  self.txt('15 Sep',x+w-45,y+45,32 if V else 27,GREY,500,align='right')
  ay=y+(235 if V else 162);sx=x+44;ex=x+w-44
  self.txt('MAA',sx,ay,125 if V else 112,DARK,650)
  self.rolling('DEL','BOM',change,ex,ay,125 if V else 112,DARK,'right')
  self.txt('Chennai',sx,ay+151 if V else ay+132,38 if V else 29,GREY)
  self.rolling('Delhi','Mumbai',change,ex,ay+151 if V else ay+132,38 if V else 29,GREY,'right')
  px0=x+(338 if V else 430);px1=x+w-(330 if V else 431);py=ay+98
  self.segment(px0,py,px1,py,(171,192,223),2)
  fly=(u*.28)%1
  self.icon('plane',px0+(px1-px0)*fly-24,py-24,48,BLUE)
  if not V:self.rolling('2h 10m','2h 05m',change,(px0+px1)/2,py+26,25,GREY,'center')
  ty=y+(466 if V else 346)
  self.txt('21:40',sx,ty,68 if V else 58,DARK,600)
  self.rolling('23:50','23:45',change,ex,ty,68 if V else 58,DARK,'right')
  if V:self.rolling('2h 10m','2h 05m',change,x+w/2,ty+26,28,GREY,'center')
  divider=y+(615 if V else 444)
  for dx in range(32,int(w-30),19):self.line(x+dx,divider,8,.5,(129,155,190),2)
  self.dot(x,divider,14,color=INK);self.dot(x+w,divider,14,color=INK)
  self.rolling('₹5,300','₹5,450',change,sx,divider+(41 if V else 19),68 if V else 44,DARK)
  self.txt('per person',sx+(0 if V else 202),divider+(125 if V else 34),29 if V else 22,GREY)
  self.rect(ex-(234 if V else 226),divider+(59 if V else 23),234 if V else 226,68 if V else 55,34,BLUE)
  self.txt('View flight',ex-(117 if V else 113),divider+(69 if V else 31),29 if V else 24,WHITE,600,align='center')
  # Second option appears during the first request and shares the destination.
  a=ease((u-.42)/.55);sy=y+h+(28 if V else 27)+(1-a)*24
  self.photo('airindia',x+4,sy+3,58,58,a)
  self.txt('Air India',x+80,sy+8,34 if V else 28,WHITE,600,a)
  if V:
   self.txt('22:15  →  00:20 +1',x+80,sy+68,32,ICE,500,a)
   self.txt('₹6,100',ex,sy+12,38,WHITE,600,a,'right')
  else:
   self.txt('22:15  →  00:20 +1',x+350,sy+10,28,ICE,500,a)
   self.txt('Nonstop',x+850,sy+10,27,ICE,500,a)
   self.txt('₹6,100',ex,sy+4,35,WHITE,600,a,'right')
  self.txt('Sample fares',x,sy+(153 if V else 90),28 if V else 24,MUTED,500,a)
  if u>5.25:
   k=ease((u-5.25)/.35)
   self.txt('Same date. Same time.',ex,sy+(152 if V else 90),29 if V else 27,GREEN,500,k,'right')

 def city_photo(self,u,a=1.):
  V=self.vertical
  z=1.035+.004*u;w=self.W*z;h=self.H*z
  self.spr(self.photo_texture('mumbai',self.W,self.H,0),(self.W-w)/2,(self.H-h)/2,w,h,a)
  self.spr(self.blank,0,0,self.W,self.H,.42*a,INK)
  # Gradient keeps text readable without dim rectangular panels.
  if 'shade' not in self.textures:
   ar=np.zeros((512,8,4),dtype=np.uint8);ar[:,:,:3]=INK
   yy=np.linspace(0,1,512);ar[:,:,3]=(185*np.maximum(np.exp(-yy*4),np.clip((yy-.58)*2.5,0,1)))[:,None]
   self.textures['shade']=self.texture(Image.fromarray(ar))
  self.spr(self.textures['shade'],0,0,self.W,self.H,a)

 def weather_scene(self,u):
  V=self.vertical;self.city_photo(u)
  if 'left-shade' not in self.textures:
   ar=np.zeros((8,512,4),dtype=np.uint8);ar[:,:,:3]=INK
   ar[:,:,3]=(155*np.clip(1-np.linspace(0,1,512)/.8,0,1))[None,:]
   self.textures['left-shade']=self.texture(Image.fromarray(ar))
  self.spr(self.textures['left-shade'],0,0,self.W,self.H)
  self.command('Weather there?',u)
  x=74 if V else 105;y=480 if V else 285
  self.txt('Mumbai',x,y,88 if V else 78,WHITE,500)
  self.txt(f"{round(self.weather['current']['temperature_2m'])}°",x-10,y+114,258 if V else 230,WHITE,400)
  self.icon('cloud',x+(545 if V else 500),y+175,150,WHITE)
  for i in range(5):
   py=y+310+((u*62+i*17)%80)
   cx=x+(567 if V else 522)+i*24
   self.segment(cx,py,cx-7,py+19,ICE,4,.7)
  self.txt('Drizzle',x,y+(420 if V else 366),47 if V else 37,WHITE)
  daily=self.weather['daily'];hi=round(daily['temperature_2m_max'][0]);lo=round(daily['temperature_2m_min'][0])
  self.txt(f'High {hi}°  ·  Low {lo}°',x,y+(495 if V else 427),35 if V else 30,ICE)
  fy=1424 if V else 785
  for i,(day,temp,rain) in enumerate(zip(['Today','Tomorrow','Wed'],daily['temperature_2m_max'],daily['precipitation_probability_max'])):
   k=ease((u-.3-i*.08)/.5);xx=x+i*(308 if V else 300)
   self.txt(day,xx,fy+(1-k)*25,31 if V else 25,ICE,a=k)
   self.txt(f'{round(temp)}°',xx,fy+50,65 if V else 54,WHITE,550,k)
   self.txt(f'{rain}% rain',xx,fy+154 if V else fy+146,29 if V else 24,ICE,a=k)
  self.txt('Open-Meteo · 14 Sep',self.W-x,1770 if V else 981,26 if V else 23,ICE,500,align='right')

 def itinerary(self,u):
  V=self.vertical;self.city_photo(u+3);self.spr(self.blank,0,0,self.W,self.H,.22,INK)
  self.command('Plan my morning.',u)
  self.txt('A morning in Mumbai.',75 if V else 104,428 if V else 280,65 if V else 65,WHITE,500)
  items=[('08:00','Gateway of India','Start by the water.'),('09:15','Kala Ghoda','Art. Coffee. A little wandering.'),('10:30','Marine Drive','Walk the curve of the bay.')]
  for i,(at,name,detail) in enumerate(items):
   k=ease((u-.22-i*.22)/.6);x=116 if V else 130+i*565;y=695+i*283 if V else 615
   if i<2:
    self.segment(x,y+6,x if V else x+565,y+(283 if V else 6),ICE,3,.42*k)
   self.dot(x,y+6,11*k,color=WHITE)
   self.txt(at,x+(44 if V else 0),y+(0 if V else -93),39 if V else 33,ICE,500,k)
   self.txt(name,x+(44 if V else 0),y+(72 if V else 57)+(1-k)*30,49 if V else 41,WHITE,600,k)
   self.txt(detail,x+(44 if V else 0),y+(145 if V else 128),30 if V else 27,WHITE,400,k)
  self.txt('Your pace. Three stops.',75 if V else 104,1718 if V else 939,34 if V else 29,ICE)

 def packing(self,u):
  V=self.vertical;self.command(['Make a packing list.','Save it.'] if V else 'Make a packing list. Save it.',u)
  x=92 if V else 104;y=517 if V else 310
  self.txt('Mumbai, packed.',x,y,79 if V else 79,WHITE,500)
  items=['Photo ID + flight details','Umbrella','Phone charger','Comfortable shoes']
  for i,item in enumerate(items):
   k=ease((u-.18-i*.09)/.5);yy=y+(197 if V else 164)+i*(145 if V else 107)+(1-k)*24
   tick=smooth((u-.95-i*.17)/.23)
   self.rect(x,yy+6,49 if V else 42,49 if V else 42,13,BLUE if tick>.5 else DARK,k,BLUE)
   self.icon('check',x+2,yy+8,45 if V else 38,WHITE,k*tick)
   self.txt(item,x+(79 if V else 72),yy,42 if V else 38,WHITE,500,k)
  if not V:
   self.photo('mumbai',1200,350,610,425,1,28)
   self.txt('Tomorrow',1217,804,30,ICE)
  k=ease((u-1.92)/.45);sx=x;sy=1530 if V else 901
  self.icon('bookmark',sx,sy,52,GREEN,k)
  self.txt('Saved to your Library',sx+72,sy+4,38 if V else 32,GREEN,600,k)

 def sports(self,u):
  V=self.vertical;self.command("Kohli’s form. Just T20.",u)
  k=smooth((u-1.18)/.36)
  x=76 if V else 104;y=437 if V else 281
  self.txt('Virat',x,y,91 if V else 88,WHITE,500)
  self.txt('Kohli',x,y+113,107 if V else 106,WHITE,550)
  # The photograph is anchored in the composition, never in a generic card.
  self.photo('kohli',325 if V else 1160,430 if V else 249,755 if V else 775,549 if V else 563)
  fy=y+274
  for i,name in enumerate(['ODI','T20']):
   active=(i==1 and k>.5) or (i==0 and k<=.5)
   xx=x+i*(142 if V else 127)
   self.rect(xx,fy,122 if V else 112,63 if V else 55,29,BLUE if active else DARK)
   self.txt(name,xx+(61 if V else 56),fy+10,29 if V else 25,WHITE,600,align='center')
  my=970 if V else 668
  for i,(a,b,lab) in enumerate([('268','296','Runs'),('67.0','98.7','Average'),('111.7','169.1','Strike rate')]):
   xx=x+i*(308 if V else 316)
   self.rolling(a,b,k,xx,my,87 if V else 75,WHITE)
   self.txt(lab,xx,my+113 if V else my+95,31 if V else 25,ICE)
  gx=x;gy=1365 if V else 853;gw=908 if V else 924;gh=226 if V else 118
  self.line(gx,gy+gh,gw,.3,ICE,2)
  old=[124,5,65,74];new=[105,58,15,43,75]
  # Morph four historical ODI points into five T20 points without clearing the
  # plot. The fifth point grows from the fourth while labels switch formats.
  old_x=[0,1/3,2/3,1,1];old_y=old+[old[-1]]
  values=new if k>.5 else old
  pts=[(gx+gw*(old_x[i]*(1-k)+i/4*k),gy+gh-(old_y[i]*(1-k)+new[i]*k)/125*gh) for i in range(5)]
  n=5;progress=ease((u-.22)/.85)
  for i in range(n-1):
   q=max(0,min(1,progress*(n-1)-i));p1,p2=pts[i],pts[i+1]
   self.segment(*p1,p1[0]+(p2[0]-p1[0])*q,p1[1]+(p2[1]-p1[1])*q,BLUE,5)
  for i,(xx,yy) in enumerate(pts):
   a=smooth((progress*(n-1)-i+.22)/.22)
   if i>=len(values):continue
   self.dot(xx,yy,7,a,ICE);self.txt(str(values[i]),xx,yy-43,25 if V else 20,ICE,550,a,'center')
   opponent=(['KKR','PBKS','SRH','GT','GT'] if k>.5 else ['NZ','ENG','ENG','ENG'])[i]
   self.txt(opponent,xx,gy+gh+25 if V else gy+gh+10,26 if V else 20,MUTED,500,a,'center')
  self.txt('May 2026 · 5 innings · Cricbuzz' if k>.5 else 'Latest returned ODI innings · Cricbuzz',x,1732 if V else 1022,26 if V else 22,MUTED)

 def search(self,u):
  V=self.vertical;self.command(['Google cat images.','Videos instead.'] if V else 'Google cat images. Videos instead.',u)
  x=75 if V else 104;y=525 if V else 292
  self.txt('Google',x,y,64 if V else 59,WHITE,550)
  self.rect(x+(0 if V else 300),y+(116 if V else 0),930 if V else 1020,81,40,DARK)
  self.txt('cat',x+(37 if V else 337),y+(132 if V else 16),36,WHITE)
  ty=y+(239 if V else 123);active=smooth((u-1.51)/.3)
  for i,s in enumerate(['All','Images','Videos']):self.txt(s,x+i*177,ty,34 if V else 30,WHITE if (i==2 if active>.5 else i==1) else MUTED,550)
  self.rect(x+177+177*active,ty+57,108,4,2,BLUE)
  py=ty+104;w=930 if V else 1210;h=550 if V else 440
  self.photo('cat',x,py,w,h,1,25)
  self.dot(x+w/2,py+h/2,51,active*.86,INK)
  self.icon('play',x+w/2-37,py+h/2-37,74,WHITE,active)
  if not V:
   self.txt('Same search.',1400,519,38,ICE)
   self.txt('New direction.',1400,577,38,WHITE,550)
  self.txt('Cat videos',x,py+h+27,41 if V else 32,WHITE,600,active)
  self.icon('arrow',x,py+h+(118 if V else 98),40,ICE)
  self.txt('Open in Google',x+60,py+h+(116 if V else 96),31 if V else 26,ICE)

 def research(self,u):
  V=self.vertical;self.command('Find sources on black holes.',u)
  x=74 if V else 104;y=423 if V else 274
  self.txt('Go deeper.',x,y,103 if V else 101,WHITE,500)
  self.photo('blackhole',590 if V else 1310,575 if V else 427,400 if V else 500,233 if V else 350,1,18)
  self.txt('M87* · EHT Collaboration',990 if V else 1810,794 if V else 800,23 if V else 24,MUTED,450,align='right')
  rows=[('Wikipedia','Black hole','An accessible starting point.'),
        ('The Astrophysical Journal Letters · 2019','First M87 Event Horizon Telescope Results','The shadow of the supermassive black hole.'),
        ('Stephen Hawking · Bantam','A Brief History of Time','A book-length route into the big questions.')]
  for i,(pub,title,sub) in enumerate(rows):
   k=ease((u-.15-i*.12)/.44);yy=(830+i*270 if V else 470+i*159)+(1-k)*32
   self.line(x,yy-22,925 if V else 1180,.24,ICE)
   self.txt(pub,x,yy,29 if V else 25,ICE,550,k)
   if V and i==1:
    self.txt('First M87 Event Horizon',x,yy+51,39,WHITE,550,k)
    self.txt('Telescope Results',x,yy+103,39,WHITE,550,k)
    self.txt('The black hole’s shadow.',x,yy+166,28,MUTED,400,k)
   else:
    self.txt(title,x,yy+50,45 if V else 36,WHITE,550,k)
    self.txt(sub,x,yy+121 if V else yy+103,28 if V else 23,MUTED,400,k)

 def calculate(self,u):
  V=self.vertical;self.command('Split twelve hundred by four.',u)
  y=600 if V else 294;k=ease((u-.45)/.62)
  self.txt('₹1,200 ÷ 4',self.W/2,y,75 if V else 72,ICE,450,align='center')
  self.txt('₹300',self.W/2,y+(180 if V else 139)+(1-k)*70,258 if V else 246,WHITE,500,k,'center')
  self.txt('per person',self.W/2,y+(515 if V else 450),55 if V else 45,ICE,450,k,'center')
  for i in range(4):
   xx=self.W/2+(i-1.5)*(144 if V else 125);yy=y+(715 if V else 594)
   self.dot(xx,yy,16,k,BLUE);self.arc(xx,yy+53,25,-math.pi,0,ICE,7,k)

 def timer(self,u):
  V=self.vertical;self.command('Twenty-minute timer.',u)
  cx=self.W/2;cy=1050 if V else 620;r=360 if V else 306
  k=ease((u+.13)/.7)
  for i in range(60):
   a=i*math.tau/60-math.pi/2
   self.segment(cx+math.cos(a)*(r-15),cy+math.sin(a)*(r-15),cx+math.cos(a)*r,cy+math.sin(a)*r,ICE,4 if i%5==0 else 2,.68 if i%5==0 else .25)
  self.arc(cx,cy,r+25,-math.pi/2,-math.pi/2+math.tau*k,BLUE,9)
  self.txt('20:00' if u<1.35 else '19:59',cx,cy-147,155 if V else 140,WHITE,450,align='center')
  self.txt('Running',cx,cy+58,39 if V else 32,ICE,500,align='center')
  self.dot(cx,cy+203,42,color=DARK);self.icon('pause',cx-24,cy+178,48)

 def clock_face(self,x,y,r,hour,minute,second=0,a=1.):
  self.dot(x,y,r,a,(20,37,64))
  for i in range(12):
   ang=i*math.tau/12;self.dot(x+math.sin(ang)*r*.82,y-math.cos(ang)*r*.82,2.3,a,ICE)
  for n,length,width,col in [((hour+minute/60)/12,r*.44,6,WHITE),((minute+second/60)/60,r*.68,4,WHITE),(second/60,r*.72,2,BLUE)]:
   ang=n*math.tau;self.segment(x,y,x+math.sin(ang)*length,y-math.cos(ang)*length,col,width,a)
  self.dot(x,y,5,a,ICE)

 def clocks(self,u):
  V=self.vertical;self.command(['London and Mumbai.','Make it a widget.'] if V else 'London and Mumbai. Make it a widget.',u)
  pin=smooth((u-1.65)/.65)
  # The result contracts into a recognisable Android home-screen widget.
  if V:final=(130,675,820,570);initial=(78,635,924,700)
  else:final=(1170,357,554,386);initial=(286,346,1348,570)
  x,y,w,h=[a+(b-a)*pin for a,b in zip(initial,final)]
  if pin>0:
   px=94 if V else 1125;py=488 if V else 237;pw=892 if V else 644;ph=1095 if V else 770
   # The frame grows around the contracting widget, rather than appearing at
   # full size in one frame. Its lower edge follows the same easing curve.
   frame_h=ph*(.83+.17*pin);frame_y=py+(ph-frame_h)/2
   self.rect(px-9,frame_y-9,pw+18,frame_h+18,63,(75,95,121),pin)
   self.rect(px,frame_y,pw,frame_h,56,(10,20,37),pin)
   self.spr(self.textures['sphere'],px+pw*.39,py+ph-pw*.62-55,pw*.53,pw*.53,pin*.65)
   self.rect(px+pw/2-46,py+21,92,12,6,(2,4,8),pin)
   self.line(px+pw*.36,py+ph-25,pw*.28,pin*.8,WHITE,5)
   if not V:
    self.txt('Keep it close.',104,426,89,WHITE,500,pin)
    self.txt('Your world. At a glance.',108,560,36,ICE,450,pin)
  self.rect(x,y,w,h,36,DARK)
  for i,(city,digital,hour,minute) in enumerate([('London','19:15',19,15),('Mumbai','23:45',23,45)]):
   xx=x+w*(.25+i*.5);radius=w*.119
   self.clock_face(xx,y+h*.35,radius,hour,minute,u*2)
   self.txt(city,xx,y+h*.63,(42 if V else 43)*(1-.27*pin),WHITE,550,align='center')
   self.txt(digital,xx,y+h*.78,(43 if V else 44)*(1-.27*pin),ICE,450,align='center')
  k=smooth((u-2.47)/.2);done=smooth((u-3.03)/.2)
  bx=380 if V else 1306;by=1415 if V else 884;bw=320 if V else 288
  self.rect(bx,by,bw,76,38,BLUE,k)
  self.txt('Add widget' if done<.5 else 'Added',bx+bw/2,by+15,32,WHITE,600,k,'center')
  if .01<done<1:self.arc(bx+bw/2,by+38,60+done*50,0,math.tau,ICE,3,(1-done)*.7)
  self.txt('14 Sep · captured times',76 if V else 106,1728 if V else 980,26 if V else 23,MUTED)

 def recall(self,u):
  V=self.vertical;self.command('Back to my trip.',u)
  x=75 if V else 104;y=436 if V else 277
  self.txt('Your Mumbai trip.',x,y,81 if V else 83,WHITE,500)
  if V:
   self.photo('mumbai',x,y+149,930,440,1,26)
   ry=y+648
  else:
   self.photo('mumbai',1030,293,783,617,1,29);ry=y+180
  rows=[('MAA → BOM','Tomorrow · 21:40 · Sample fare'),('Your morning','Gateway → Kala Ghoda → Marine Drive'),('Packing list','4 essentials · Saved in Library')]
  for i,(title,detail) in enumerate(rows):
   k=ease((u-.1-i*.14)/.45);yy=ry+i*(203 if V else 167)+(1-k)*20
   if i==0:self.photo('indigo',x,yy,52,52,k)
   else:self.icon('bookmark' if i==1 else 'check',x,yy+7,46,ICE,k)
   self.txt(title,x+80,yy,44 if V else 40,WHITE,550,k)
   self.txt(detail,x+80,yy+70,29 if V else 26,ICE,450,k)
  self.txt('Right where you left it.',x,1740 if V else 953,35 if V else 30,GREEN,500,ease((u-1.25)/.4))

 def close(self,u):
  V=self.vertical;W,H=self.W,self.H
  # Rapid kinetic typography lands on the identity; no slow introductory hold.
  for text,start,end in [('Ask.',0,.50),('Interrupt.',.50,1.26),('Keep going.',1.26,1.96)]:
   if start<=u<end:
    k=ease((u-start)/.19);a=1.
    self.txt(text,W/2,H/2-110+(1-k)*55,127 if V else 174,WHITE,550,a,'center')
  a=smooth((u-1.96)/.23)
  if a>0:
   size=480 if V else 430;yy=582 if V else 147
   self.spr(self.textures['sphere'],(W-size)/2,yy-35*(1-a),size,size,a)
   self.txt('THREAD',W/2,1170 if V else 668,136 if V else 131,WHITE,450,a,'center')
   self.txt('Ask. Interrupt. Keep going.',W/2,1390 if V else 865,38 if V else 35,ICE,450,a,'center')

 def frame(self,t):
  self.fbo.use();self.transform=(0,0,1,1)
  self.basevao.render(moderngl.TRIANGLE_STRIP)
  for i,fn in enumerate(self.shots):
   start,end=CUTS[i:i+2]
   if start-.20<=t<end+.20:
    inc=smooth((t-start+.16)/.32) if i else 1.
    out=smooth((t-end+.16)/.32) if i<len(self.shots)-1 else 0.
    # Complementary scissors give each shot an exclusive part of the frame.
    # Text never double-exposes across shots; the shared camera settles gently.
    if inc<1:
     if i==2:self.ctx.scissor=(0,round(self.h*(1-inc)),self.w,round(self.h*inc))
     else:self.ctx.scissor=(0,0,round(self.w*inc),self.h)
    elif out>0:
     if i+1==2:self.ctx.scissor=(0,0,self.w,round(self.h*(1-out)))
     else:self.ctx.scissor=(round(self.w*out),0,self.w-round(self.w*out),self.h)
    else:self.ctx.scissor=None
    self.transform=(-(1-inc)*18+out*12,(1-inc)*10-out*8,1,1)
    fn(max(0.,t-start))
    self.ctx.scissor=None
  self.transform=(0,0,1,1)
  if t<39.05:self.brand(t)
  return self.fbo.read(components=3,alignment=1)

def main():
 p=argparse.ArgumentParser();p.add_argument('--vertical',action='store_true');p.add_argument('--stills',action='store_true')
 p.add_argument('--width',type=int);p.add_argument('--start',type=float,default=0);p.add_argument('--end',type=float,default=DURATION);p.add_argument('--fps',type=int,default=60)
 args=p.parse_args();w=args.width or (1080 if args.vertical else 2560);h=round(w*(16/9 if args.vertical else 9/16));h+=h%2
 movie=Movie(w,h);shape='vertical' if args.vertical else 'landscape'
 if args.stills:
  for t in [1.4,3.3,4.65,6.6,9.6,12.6,15.8,19.3,22.9,25.6,28.5,31.2,33.1,35.3,37.7,40.2,41.65]:
   im=Image.frombytes('RGB',(w,h),movie.frame(t)).transpose(Image.Transpose.FLIP_TOP_BOTTOM)
   im.save(ROOT/'stills'/f'{shape}-{t:05.2f}.jpg',quality=94)
  print('Saved 17 review frames.',flush=True);return
 target=ROOT/'output'/f'{shape}-silent.mp4'
 cmd=['ffmpeg','-hide_banner','-loglevel','warning','-y','-f','rawvideo','-pixel_format','rgb24','-video_size',f'{w}x{h}','-framerate',str(args.fps),'-i','pipe:0','-vf','vflip,scale=in_range=pc:out_range=tv:out_color_matrix=bt709','-c:v','h264_nvenc','-preset','p6','-tune','hq','-rc','vbr','-cq','17','-b:v','0','-pix_fmt','yuv420p','-color_range','tv','-color_primaries','bt709','-color_trc','bt709','-colorspace','bt709','-movflags','+faststart',str(target)]
 start=time.monotonic();proc=subprocess.Popen(cmd,stdin=subprocess.PIPE);n=round((args.end-args.start)*args.fps)
 try:
  for i in range(n):
   proc.stdin.write(movie.frame(args.start+i/args.fps))
   if i%240==0:print(f'{i}/{n} frames · {time.monotonic()-start:.1f}s',flush=True)
  proc.stdin.close()
  if proc.wait():raise RuntimeError('Video encoder failed')
 finally:
  if proc.poll() is None:proc.terminate()
 print(target,flush=True)

if __name__=='__main__':main()
