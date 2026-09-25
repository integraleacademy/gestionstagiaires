"""Sharp native 4K diagrams, timed type, local narration, burned captions."""
from pathlib import Path
from functools import lru_cache
import json, math, os, subprocess, sys
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parent;ASSETS=ROOT/'assets'
WORK=Path(os.environ['ACADEMY_WORK']);OUT=ROOT.parents[1]/'elearning_native'/'media'
S=2;W=1920;H=1080
DARK='#101619';PANEL='#1A2327';GOLD='#F2C461';WHITE='#F4F1E9';MUTED='#ABB6B9';INK='#182024'
def box(d,b,fill,outline=None,r=0,width=1):
 b=tuple(round(x*S) for x in b)
 if r:d.rounded_rectangle(b,r*S,fill,outline,width*S)
 else:d.rectangle(b,fill,outline,width*S)
def line(d,pts,color=GOLD,width=3):d.line([(round(x*S),round(y*S)) for x,y in pts],fill=color,width=width*S,joint='curve')
def circle(d,x,y,r,fill=None,outline=None,width=2):d.ellipse(((x-r)*S,(y-r)*S,(x+r)*S,(y+r)*S),fill,outline,width*S)
@lru_cache(maxsize=40)
def font(size,weight=600):return ImageFont.truetype(str(ASSETS/f'Manrope-{weight}.ttf'),round(size*S))
def txt(d,t,x,y,size=24,color=WHITE,weight=600):d.text((x*S,y*S),t,font=font(size,weight),fill=color,anchor='lt')
def icon(d,kind,cx,cy,scale=1,color=GOLD):
 # Exact conceptual symbols rather than photo-like illustrations.
 def L(points,w=5):line(d,[(cx+x*scale,cy+y*scale) for x,y in points],color,w)
 def B(b,r=8,fill=None):box(d,tuple((cx if i%2==0 else cy)+v*scale for i,v in enumerate(b)),fill,color,r,4)
 def C(x,y,r):circle(d,cx+x*scale,cy+y*scale,r*scale,outline=color,width=4)
 if kind=='book':
  L([(-150,-120),(-15,-110),(0,-90),(15,-110),(150,-120),(150,120),(20,126),(0,143),(-20,126),(-150,120),(-150,-120)])
  L([(0,-90),(0,143)],3)
  for y in [-55,-5,45]:L([(-116,y),(-42,y+6)],3);L([(40,y+6),(118,y)],3)
 elif kind=='badge':
  B((-125,-160,125,175),18);B((-43,-182,43,-140),8)
  C(0,-60,34);L([(-65,40),(-60,9),(-35,-7),(35,-7),(60,9),(65,40)])
  L([(-80,85),(80,85)],3);L([(-50,118),(50,118)],3)
 elif kind=='balance':
  L([(0,-160),(0,155)]);L([(-160,-80),(160,-80)]);L([(-80,156),(80,156)])
  C(0,-95,15)
  for x in [-115,115]:
   L([(x,-80),(x-54,38),(x+54,38),(x,-80)],3)
   L([(x-54,38),(x-35,65),(x+35,65),(x+54,38)],4)
 elif kind=='building':
  B((-132,-157,132,161),5);L([(-175,162),(175,162)]);B((-28,72,28,160),2)
  for x in [-81,0,81]:
   for y in [-95,-28]:B((x-14,y-16,x+14,y+16),2)
 elif kind=='shield':
  L([(0,-181),(143,-112),(132,47),(89,113),(0,179),(-89,113),(-132,47),(-143,-112),(0,-181)])
  L([(-64,-4),(-10,49),(79,-57)],8)
 elif kind=='clipboard':
  B((-125,-148,125,178),14);B((-48,-175,48,-125),8)
  for y in [-67,6,79]:L([(-79,y),(-65,y+13),(-42,y-14)],4);L([(-13,y),(79,y)],3)
 elif kind=='phone':
  B((-102,-167,102,180),24);L([(-35,-130),(35,-130)],3);C(0,140,8)
  L([(-61,0),(61,0)],7);L([(0,-61),(0,61)],7)
 elif kind=='lock':
  B((-133,-28,133,173),20)
  L([(-77,-30),(-77,-111),(-54,-154),(0,-174),(54,-154),(77,-111),(77,-30)],8)
  C(0,48,20);L([(0,70),(0,112)],7)
 elif kind=='screen':
  B((-180,-132,180,88),12);L([(-180,51),(180,51)],3);L([(0,88),(0,155)]);L([(-74,157),(74,157)])
  L([(-60,-66),(-92,-36),(-60,-6)],5);L([(60,-66),(92,-36),(60,-6)],5);L([(13,-80),(-13,8)],5)
 elif kind=='court':
  L([(-180,-92),(0,-190),(180,-92),(-180,-92)])
  for x in [-120,-40,40,120]:L([(x,-66),(x,119)],10)
  L([(-167,133),(167,133)]);L([(-190,165),(190,165)])

def base(v,sc):
 light=sc['kind']=='recap'; bg=WHITE if light else DARK; fg=INK if light else WHITE; c='#A27C29' if light else GOLD
 im=Image.new('RGB',(W*S,H*S),bg);d=ImageDraw.Draw(im)
 lg=Image.open(ASSETS/'logo-integrale.png').convert('RGBA');lg.thumbnail((176,176),Image.Resampling.LANCZOS);im.paste(lg,(152,96),lg)
 txt(d,'INTÉGRALE ACADEMY',185,64,23,fg,800);txt(d,'FORMATION APS',185,101,18,'#7B8588' if light else MUTED)
 txt(d,f'MODULE {v["module"]}  /  SÉQUENCE {v["sequence"]:02}',1510,81,18,'#7B8588' if light else MUTED)
 line(d,[(76,1031),(1844,1031)],'#D3D8D5' if light else '#344147',2)
 txt(d,'CADRE LÉGAL' if v['module']==1 else 'CADRE PÉNAL',76,1052,13,'#728084' if light else MUTED)
 txt(d,'INTÉGRALE ACADEMY',1655,1052,13,'#728084' if light else MUTED)
 kind=sc['kind']
 if kind in ['hero','answer','recap']:
  for r in [235,290,350]:circle(d,1465,545,r,outline='#D8D9CE' if light else '#283A3F',width=1)
  circle(d,1465,545,232,fill='#EEEADF' if light else PANEL)
  icon(d,v['icon'],1465,535,1,c)
  for angle in [15,130,250]:
   a=math.radians(angle);circle(d,1465+290*math.cos(a),545+290*math.sin(a),5,fill=c)
  line(d,[(1055,237),(1055,850)],'#D8D9CE' if light else '#2C3B40',1)
 if kind=='rules':
  for i in range(3):
   x=76+i*604;box(d,(x,521,x+560,839),PANEL,'#3C4747',18)
   txt(d,f'0{i+1}',x+30,551,23,GOLD,800)
   line(d,[(x+30,802),(x+529,802)],'#4A4E40',2)
 elif kind=='case':
  for i in range(2):
   x=76+i*910;box(d,(x,556,x+858,786),PANEL,'#5D5B42',18)
  txt(d,'RÉFLEXION PERSONNELLE · LA CORRECTION ARRIVE ENSUITE',76,834,19,MUTED)
 elif kind=='answer':
  for i in range(3):
   y=566+i*103;circle(d,103,y+17,26,fill=GOLD)
   txt(d,f'0{i+1}',87,y+5,18,INK,800);line(d,[(151,y+67),(980,y+67)],'#334247',1)
 return im

def esc(t):return t.replace('\\','\\\\').replace('{','(').replace('}',')').replace('\n','\\N')
def wrap(t,size,width,maxlines=9):
 result=[]
 for par in t.split('\n'):
  row=''
  for word in par.split():
   test=(row+' '+word).strip()
   if font(size,800).getlength(test)>width*S and row:result.append(row);row=word
   else:row=test
  if row:result.append(row)
 if len(result)>maxlines:raise ValueError(f'Text overflow {len(result)}: {t}')
 return '\n'.join(result)
def ts(t):
 n=round(t*100);h,n=divmod(n,360000);m,n=divmod(n,6000);s,n=divmod(n,100)
 return f'{h}:{m:02}:{s:02}.{n:02}'
def color(c):return '&H'+''.join([c[5:7],c[3:5],c[1:3]])+'&'
def build_ass(v,tl,path):
 events=[]
 def text(start,end,t,x,y,size=36,col=WHITE,bold=True,animate=True,center=False,caption=False):
  if end<=start:return
  align=8 if center else 7; face='AcademyManrope800' if bold else 'AcademyManrope600'
  tags=f'\\an{align}\\fn{face}\\fs{size*S}\\c{color(col)}\\bord0\\shad0'
  if caption:tags+=f'\\bord16\\3c{color(DARK)}\\shad0'
  if animate:tags+=f'\\move({x*S},{(y+20)*S},{x*S},{y*S},0,400)\\fad(240,100)'
  else:tags+=f'\\pos({x*S},{y*S})'
  events.append(f'Dialogue: 1,{ts(start)},{ts(end)},Default,,0,0,0,,{{{tags}}}{esc(t)}')
 for sc in tl['scenes']:
  st=sc['start'];end=sc['end'];kind=sc['kind'];light=kind=='recap';fg=INK if light else WHITE;gc='#A27C29' if light else GOLD
  text(st+.1,end,sc['label'],76,190,21,gc)
  if kind=='hero':
   text(st+.25,end,wrap(sc['headline'],91,960,4),76,300,91,fg)
   text(st+.6,end,wrap(v['title'],28,900,2),78,750,28,MUTED,False)
  elif kind=='rules':
   text(st+.2,end,sc['headline'],76,279,84)
   text(st+.5,end,'Des repères pour agir avec méthode.',78,414,28,MUTED,False)
   for i,item in enumerate(sc['items']):text(st+.8+i*.5,end,wrap(item,38,490,4),106+604*i,621,38)
  elif kind=='case':
   text(st+.2,end,wrap(sc['headline'],64,1768,3),76,278,64)
   for i,item in enumerate(sc['items']):text(st+.6+i*.3,end,wrap(item,32,780,4),111+910*i,607,32)
   # Quiet countdown only during the reflection period.
   p=end-4
   for i in range(4):text(p+i,p+i+1,str(4-i),1770,826,30,GOLD,True,False)
  elif kind=='answer':
   text(st+.2,end,wrap(sc['headline'],65,910,3),76,275,65,GOLD)
   for i,item in enumerate(sc['items']):text(st+.7+i*.4,end,wrap(item,30,800,2),151,563+i*103,30)
  elif kind=='recap':text(st+.25,end,wrap(sc['headline'],73,920,5),76,301,73,fg)
  for cue in sc['cues']:
   cap=wrap(cue['text'],28,1670,3)
   rows=len(cap.split('\n'));yy=944-(rows-1)*36
   text(cue['start'],cue['end'],cap,960,yy,28,WHITE,False,False,True,True)
 # Smooth gold progress line; native ASS vector clipping animates along its length.
 dur=tl['duration'];tags=f'\\an7\\pos(152,2060)\\bord0\\shad0\\c{color(GOLD)}\\clip(152,2060,152,2067)\\t(0,{round(dur*1000)},\\clip(152,2060,3688,2067))\\p1'
 events.append(f'Dialogue: 2,{ts(0)},{ts(dur)},Default,,0,0,0,,{{{tags}}}m 0 0 l 3536 0 l 3536 7 l 0 7')
 header='''[Script Info]\nScriptType: v4.00+\nPlayResX: 3840\nPlayResY: 2160\nWrapStyle: 2\nScaledBorderAndShadow: yes\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,AcademyManrope600,60,&H00FFFFFF,&H00FFFFFF,&H00101619,&H00101619,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'''
 path.write_text(header+'\n'.join(events)+'\n')

def render(v):
 folder=WORK/v['id'];tlpath=folder/'timeline.json'
 if not tlpath.exists():raise FileNotFoundError(tlpath)
 tl=json.loads(tlpath.read_text());dur=round(tl['duration'],2);out=OUT/(v['id']+'.mp4');OUT.mkdir(exist_ok=True)
 if out.exists() and (folder/'render.json').exists():
  print(v['id'],'video cached',flush=True);return
 concat=[]
 for i,sc in enumerate(tl['scenes']):
  im=base(v,sc);im.save(folder/f'scene-{i}.png')
  concat += [f"file '{folder}/scene-{i}.png'",f"duration {sc['end']-sc['start']:.6f}"]
 concat += [f"file '{folder}/scene-{len(tl['scenes'])-1}.png'"]
 (folder/'frames.txt').write_text('\n'.join(concat)+'\n');build_ass(v,tl,folder/'graphics.ass')
 filt=f"fps=25,subtitles={folder}/graphics.ass:fontsdir={ASSETS},format=yuv420p"
 tmp=OUT/(v['id']+'.partial.mp4')
 cmd=['ffmpeg','-nostdin','-hide_banner','-loglevel','info','-y','-threads','1','-f','concat','-safe','0','-i',str(folder/'frames.txt'),'-i',str(folder/'narration.wav'),'-vf',filt,'-filter_threads','1','-c:v','libx264','-preset','veryfast','-crf','20','-threads','4','-c:a','aac','-b:a','160k','-af','loudnorm=I=-16:TP=-1.5:LRA=11','-ar','48000','-movflags','+faststart','-t',str(dur),str(tmp)]
 print(v['id'], 'rendering', flush=True)
 with (folder/'ffmpeg.log').open('w') as log:
  subprocess.run(cmd,check=True,timeout=600,stdout=log,stderr=log)
 probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(tmp)]))
 vs=next(s for s in probe['streams'] if s['codec_type']=='video');a=next(s for s in probe['streams'] if s['codec_type']=='audio')
 assert(vs['width'],vs['height'])==(3840,2160) and abs(float(probe['format']['duration'])-dur)<.1
 tmp.replace(out)
 subprocess.run(['ffmpeg','-nostdin','-loglevel','error','-y','-threads','1','-ss','3','-i',str(out),'-frames:v','1','-vf','scale=1280:-1','-filter_threads','1','-threads','1',str(OUT/(v['id']+'.jpg'))],check=True,timeout=60)
 (folder/'render.json').write_text(json.dumps(dict(id=v['id'],duration_seconds=float(probe['format']['duration']),bytes=out.stat().st_size,width=vs['width'],height=vs['height']),indent=2))
 print(v['id'],dur,out.stat().st_size,'VIDEO READY',flush=True)
if __name__=='__main__':
 for v in json.loads((ROOT/'series.json').read_text()):
  if len(sys.argv)>1 and v['id'] not in sys.argv[1:]:continue
  render(v)
