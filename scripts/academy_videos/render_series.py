"""Native 4K capsules using the recovered, approved Missions et limites style."""
from pathlib import Path
from functools import lru_cache
import hashlib, json, math, os, subprocess, sys, time
from PIL import Image, ImageDraw
import approved_style as style
from approved_style import (W,H,S,FPS,DARK,PANEL,GOLD,IVORY,MUTED,INK,px,ease,mix,
    font,txt,enter,rect,line,circle,brand,label,background,subtitle,outro)
from diagram_icons import icon
ROOT=Path(__file__).resolve().parent
WORK=Path(os.environ['ACADEMY_WORK'])
OUT=ROOT.parents[1]/'elearning_native'/'media'
SETTINGS=json.loads((ROOT/'reference_settings.json').read_text())


@lru_cache(maxsize=512)
def wrap(text,size,width,weight=800):
    rows=[]
    for paragraph in text.split('\n'):
        row=''
        for word in paragraph.split():
            test=(row+' '+word).strip()
            if font(size,weight).getlength(test)>px(width) and row:
                rows.append(row);row=word
            else:row=test
        if row:rows.append(row)
    return rows


@lru_cache(maxsize=256)
def fitted(text,size,width,rows,weight=800):
    while size>=24:
        lines=wrap(text,size,width,weight)
        if len(lines)<=rows:return lines,size
        size-=2
    raise ValueError('Text does not fit: '+text)


def headline(im,text,x,y,lt,size,width=960,maxrows=3,gold_last=True):
    rows,size=fitted(text,size,width,maxrows)
    for i,row in enumerate(rows):
        enter(im,row,x,y+i*size*1.23,lt,.1+i*.17,size,800,GOLD if gold_last and i==len(rows)-1 else IVORY)
    return rows,size


def emblem(im,v,lt,cx=1465,cy=497):
    # Same architectural rings and movement as the approved graphic introduction.
    d=ImageDraw.Draw(im)
    for radius,speed,offset in [(325,13,-72),(390,-8,116)]:
        a=offset+speed*lt
        d.arc((px(cx-radius),px(cy-radius),px(cx+radius),px(cy+radius)),a,a+30,fill='#A88844',width=px(2))
        angle=math.radians(a+30)
        circle(im,cx+radius*math.cos(angle),cy+radius*math.sin(angle),4,fill=GOLD)
    q=ease((lt-.3)/1.0)
    # Native vector-like diagram for this sequence, with the model's gold palette.
    icon(d,v['icon'],cx,cy+24*(1-q),1.2,GOLD)


def hero(im,v,s,lt,t):
    emblem(im,v,lt)
    label(im,s['label'])
    rows,size=headline(im,s['headline'],76,280,lt,106,930,3)
    q=ease((lt-.55)/.9)
    line(im,[(80,698),(80+166*q,698)],GOLD,6)
    titles,fs=fitted(v['title'],29,930,2,550)
    for i,row in enumerate(titles):enter(im,row,76,746+i*38,lt,.6,fs,550)
    enter(im,'COMPRENDRE  /  VÉRIFIER  /  AGIR',76,835,lt,.78,18,750,MUTED)
    for i,(word,x) in enumerate([('Comprendre',1168),('Vérifier',1465),('Agir',1762)]):
        q=ease((lt-.9-i*.35)/.6)
        circle(im,x,823,4,fill=mix('#344548',GOLD,q))
        enter(im,word,x,851,lt,.9+i*.35,25,650,IVORY,align='center')


def rules(im,v,s,lt,t):
    label(im,s['label'])
    enter(im,'Trois repères.',76,266,lt,0,83,800)
    enter(im,'Pour agir avec méthode.',76,372,lt,.13,66,800,GOLD)
    enter(im,'Le cadre guide chaque décision.',78,482,lt,.25,29,550,MUTED)
    starts=[s['cues'][0]['start']+(s['end']-s['cues'][0]['start']-.8)*i/3 for i in range(3)]
    for i,item in enumerate(s['items']):
        x=76+i*604;y=568+26*(1-ease((lt-.4-i*.14)/.6))
        q=ease((t-starts[i])/.6)
        rect(im,(x,y,x+560,y+288),mix(PANEL,'#302B1D',q),outline=mix('#354044',GOLD,q),r=16)
        txt(im,f'0{i+1}',x+30,y+26,22,750,GOLD if q else MUTED)
        rows,size=fitted(item,44,500,3)
        for j,row in enumerate(rows):txt(im,row,x+30,y+95+j*size*1.22,size,800)
        if q:line(im,[(x+30,y+256),(x+30+500*q,y+256)],GOLD,3)


def quiz(im,v,s,lt,t):
    label(im,s['label'])
    headline(im,s['headline'],76,260,lt,80,1768,2)
    pause=next(c for c in s['cues'] if c.get('pause'))
    for i,item in enumerate(s['items']):
        y=526+i*148
        rect(im,(76,y,1710,y+122),PANEL,outline='#39464B',width=2,r=13)
        circle(im,125,y+61,27,fill='#303D42')
        txt(im,'AB'[i],125,y+47,23,800,IVORY,align='center')
        rows,size=fitted(item.split(' · ',1)[-1],31,1430,2,550)
        for j,row in enumerate(rows):txt(im,row,186,y+(122-len(rows)*40)/2+j*40,size,550)
    if pause['start']<=t<pause['end']:
        remaining=max(1,math.ceil(pause['end']-t));cx=1788;cy=587;r=49
        circle(im,cx,cy,r,outline='#39464B',width=5)
        ImageDraw.Draw(im).arc((px(cx-r),px(cy-r),px(cx+r),px(cy+r)),-90,-90+360*(pause['end']-t)/5,fill=GOLD,width=px(5))
        txt(im,str(remaining),cx,cy-23,38,800,GOLD,align='center')
        txt(im,'Prenez le temps de choisir.',78,853,22,600,MUTED)
    else:txt(im,'Choisissez A ou B.',78,853,22,600,MUTED)


def answer(im,v,s,lt,t):
    # The approved split composition: diagram on the left, action panel on the right.
    cx=548;cy=480
    for r in [195,252,308]:circle(im,cx,cy,r,outline='#304044',width=1)
    icon(ImageDraw.Draw(im),v['icon'],cx,cy,1.0,GOLD)
    txt(im,s['label'],1110,206,20,750,GOLD)
    rows,size=headline(im,s['headline'],1110,282,lt,72,735,3)
    # Three progressively lit steps, matching the reference access-control example.
    cue_start=s['cues'][min(1,len(s['cues'])-1)]['start']
    starts=[cue_start+i*1.6 for i in range(3)]
    for i,item in enumerate(s['items']):
        y=573+i*96;q=ease((t-starts[i])/.45)
        circle(im,1133,y+20,24,fill=mix(PANEL,GOLD,q))
        txt(im,f'0{i+1}',1133,y+8,17,800,INK if q>.5 else MUTED,align='center')
        lines,size=fitted(item,28,650,2,650)
        for j,row in enumerate(lines):txt(im,row,1185,y+1+j*34,size,650,mix('#69787E',IVORY,q))
        line(im,[(1110,y+80),(1840,y+80)],'#354044',1)
    txt(im,'AGIR AVEC MÉTHODE',76,803,18,750,IVORY)
    enter(im,'La règle guide votre décision.',76,843,lt,.45,30,700,IVORY)


def recap(im,v,s,lt,t):
    # Ivory chapter from the model, with the same ink/gold contrast and Manrope weights.
    label(im,s['label'],True)
    words=s['headline'].split('\n')
    count=len(words)
    for i,word in enumerate(words):
        delay=.15+i*.45;q=ease((lt-delay)/.65)
        yy=284+i*175
        txt(im,f'0{i+1}',76,yy+14,26,750,'#9B7522',q)
        rows,size=fitted(word,80,1620,1)
        enter(im,rows[0],169,yy,lt,delay,size,800,INK if i<count-1 else '#9B7522')
        line(im,[(169,yy+115),(169+1530*q,yy+115)],'#D4D7D2',2)
    txt(im,'LE CADRE LÉGAL GUIDE CHAQUE DÉCISION.',78,862,21,750,'#748082')


def frame(v,tl,t):
    scenes=tl['scenes'];idx=next((i for i,s in enumerate(scenes) if s['start']<=t<s['end']),len(scenes)-1)
    s=scenes[idx];lt=t-s['start'];kind=s['kind']
    bg={'hero':'intro','answer':'badge','recap':'limits'}.get(kind,kind)
    im=background(bg).copy()
    if kind!='outro':brand(im,kind=='recap')
    if kind=='outro':outro(im,s,lt,t)
    else:{'hero':hero,'rules':rules,'case':quiz,'answer':answer,'recap':recap}[kind](im,v,s,lt,t)
    if idx and lt<.38:
        edge=W*ease(lt/.38);rect(im,(edge,0,W,H),DARK);rect(im,(max(0,edge-5),0,edge,H),GOLD)
    subtitle(im,s,t)
    style.footer(im,t,kind=='recap')
    return im


def configure(v,tl):
    if tl['voice']!=SETTINGS['voice'] or tl['rate']!=SETTINGS['rate']:
        raise ValueError('Narration does not match the approved reference')
    style.DURATION=tl['duration'];style.CHAPTER='CADRE LÉGAL' if v['module']==1 else 'CADRE PÉNAL'
    for scene in tl['scenes']:
        for cue in scene['cues']:
            if len(style.split_caption(cue['text']))>2:raise ValueError('Caption exceeds two lines: '+cue['text'])


def stamp(t):
    ms=round(t*1000);h,ms=divmod(ms,3600000);m,ms=divmod(ms,60000);s,ms=divmod(ms,1000)
    return f'{h:02}:{m:02}:{s:02},{ms:03}'


def previews(v):
    folder=WORK/v['id'];tl=json.loads((folder/'timeline.json').read_text());configure(v,tl)
    times=[min(s['end']-.2,s['start']+3.2) for s in tl['scenes']]
    sheet=Image.new('RGB',(1920,1080),'#101619')
    for i,t in enumerate(times):
        im=frame(v,tl,t);im.save(folder/f'preview-{i}.jpg',quality=95)
        im.thumbnail((640,360),Image.Resampling.LANCZOS);sheet.paste(im,((i%3)*640,(i//3)*360))
    sheet.save(folder/'contact-sheet.jpg',quality=95)
    print(v['id'],'PREVIEW READY',flush=True)


def render(v):
    folder=WORK/v['id'];tl=json.loads((folder/'timeline.json').read_text());configure(v,tl)
    duration=tl['duration'];out=OUT/(v['id']+'.mp4');OUT.mkdir(exist_ok=True)
    render_hash=hashlib.sha256((Path(__file__).read_bytes()+(ROOT/'approved_style.py').read_bytes()+(folder/'timeline.json').read_bytes())).hexdigest()
    if out.exists() and (folder/'render.json').exists():
        if json.loads((folder/'render.json').read_text()).get('render_sha256')==render_hash:
            print(v['id'],'reference video cached',flush=True);return
    temp=out.with_suffix('.partial.mp4')
    command=['ffmpeg','-y','-v','warning','-f','rawvideo','-pix_fmt','rgb24','-s','3840x2160','-r','25','-i','pipe:0',
        '-i',str(folder/'narration.wav'),'-map','0:v:0','-map','1:a:0','-c:v','libx264','-preset','fast','-crf','17','-threads','4',
        '-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-af','loudnorm=I=-16:TP=-1.5:LRA=11','-ar','48000','-movflags','+faststart','-t',str(duration),str(temp)]
    frames=math.ceil(duration*FPS);began=time.monotonic()
    with (folder/'ffmpeg.log').open('w') as log:
        process=subprocess.Popen(command,stdin=subprocess.PIPE,stderr=log)
        try:
            for i in range(frames):
                process.stdin.write(frame(v,tl,i/FPS).tobytes())
                if i%(FPS*10)==0:print(v['id'],f'{i/FPS:.0f}/{duration:.0f}s',f'{time.monotonic()-began:.1f}s elapsed',flush=True)
        finally:process.stdin.close()
        if process.wait():raise RuntimeError('Video encoder failed')
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(temp)]))
    video=next(s for s in probe['streams'] if s['codec_type']=='video');audio=next(s for s in probe['streams'] if s['codec_type']=='audio')
    assert (video['width'],video['height'])==(3840,2160) and abs(float(probe['format']['duration'])-duration)<.1
    assert audio['sample_rate']=='48000'
    temp.replace(out)
    poster=frame(v,tl,3);poster.thumbnail((1280,720),Image.Resampling.LANCZOS);poster.save(OUT/(v['id']+'.jpg'),quality=94)
    cues=[c for s in tl['scenes'] for c in s['cues'] if not c.get('pause')]
    (folder/'subtitles.srt').write_text('\n\n'.join(f'{i+1}\n{stamp(c["start"])} --> {stamp(c["end"])}\n{c["text"]}' for i,c in enumerate(cues))+'\n')
    result=dict(id=v['id'],duration_seconds=float(probe['format']['duration']),bytes=out.stat().st_size,width=video['width'],height=video['height'],
        voice=tl['voice'],rate=tl['rate'],reference_style=tl['reference_style'],render_sha256=render_hash)
    (folder/'render.json').write_text(json.dumps(result,indent=2)+'\n')
    print(v['id'],duration,out.stat().st_size,'REFERENCE VIDEO READY',flush=True)

if __name__=='__main__':
    selection=[a for a in sys.argv[1:] if not a.startswith('--')]
    for v in json.loads((ROOT/'series.json').read_text()):
        if selection and v['id'] not in selection:continue
        (previews if '--preview' in sys.argv else render)(v)
