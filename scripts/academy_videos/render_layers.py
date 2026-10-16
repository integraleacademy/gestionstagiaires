"""Efficient 4K export: original PIL artwork, animated as native FFmpeg layers.
Avoid transferring a complete 25 MB raster frame through Python on every tick.
"""
from pathlib import Path
import hashlib,json,math,subprocess,sys,time
from PIL import Image,ImageDraw
import render_series as r
import approved_style as st


def render_scene(v,tl,s,index,folder):
    start=round(s['start']*25)/25
    end=round(s['end']*25)/25
    duration=end-start
    path=folder/f'scene-{index:02}.mp4'
    layerdir=folder/f'layers-{index:02}';layerdir.mkdir(exist_ok=True)
    kind=s['kind'];light=kind=='recap';records=[]
    original_enter=r.enter;original_st_enter=st.enter;original_emblem=r.emblem
    def capture(im,text,x,y,t,delay=0,size=40,weight=600,color=st.IVORY,align='left'):
        records.append(dict(text=text,x=x,y=y,delay=delay,size=size,weight=weight,color=color,align=align))
    def static_emblem(im,video,lt,cx=1465,cy=497):
        r.icon(ImageDraw.Draw(im),video['icon'],cx,cy,1.2,st.GOLD)
    r.enter=st.enter=capture;r.emblem=static_emblem
    try:
        bg={'hero':'intro','answer':'badge','recap':'limits'}.get(kind,kind)
        im=st.background(bg).copy()
        if kind!='outro':st.brand(im,light)
        if kind=='outro':st.outro(im,s,999,start)
        else:{'hero':r.hero,'rules':r.rules,'case':r.quiz,'answer':r.answer,'recap':r.recap}[kind](im,v,s,999,start)
        st.footer(im,0,light)
    finally:r.enter=original_enter;st.enter=original_st_enter;r.emblem=original_emblem
    base=layerdir/'base.png';im.save(base)
    layers=[]
    def add(image,x,y,begin=0,finish=None,fade=0,slide=0,rotate=None):
        target=layerdir/f'{len(layers):03}.png';image.save(target)
        layers.append(dict(path=target,x=x,y=y,start=max(0,begin),end=duration if finish is None else min(duration,finish),fade=fade,slide=slide,rotate=rotate))
    for obj in records:
        picture=st.text_layer(obj['text'],obj['size'],obj['weight'],obj['color'])
        x=st.px(obj['x']);y=st.px(obj['y'])
        if obj['align']=='center':x-=picture.width/2
        elif obj['align']=='right':x-=picture.width
        add(picture,x,y,obj['delay'],fade=.65,slide=56)
    if kind=='hero':
        for radius,speed,offset in [(325,13,-72),(390,-8,116)]:
            side=st.px(radius*2+16);art=Image.new('RGBA',(side,side));d=ImageDraw.Draw(art)
            c=side/2;rr=st.px(radius);box=(c-rr,c-rr,c+rr,c+rr)
            d.arc(box,offset,offset+30,fill='#A88844',width=st.px(2))
            a=math.radians(offset+30);xx=c+rr*math.cos(a);yy=c+rr*math.sin(a)
            d.ellipse((xx-8,yy-8,xx+8,yy+8),fill=st.GOLD)
            add(art,st.px(1465)-side/2,st.px(497)-side/2,rotate=speed)
    if kind in ('rules','answer'):
        active=st.background('badge' if kind=='answer' else 'rules').copy()
        # Draw once with fully lit cards. Title layers are deliberately absent here.
        r.enter=lambda *a,**kw:None
        try:
            (r.rules if kind=='rules' else r.answer)(active,v,s,999,s['end'])
        finally:r.enter=original_enter
        for i in range(3):
            if kind=='rules':
                x=76+i*604;y=568;ww=560;hh=288
                at=s['cues'][0]['start']+(s['end']-s['cues'][0]['start']-.8)*i/3-start
            else:
                x=1110;y=573+i*96;ww=736;hh=82
                at=s['cues'][min(1,len(s['cues'])-1)]['start']+i*1.6-start
            crop=active.crop((st.px(x),st.px(y),st.px(x+ww+1),st.px(y+hh+1))).convert('RGBA')
            add(crop,st.px(x),st.px(y),at,fade=.6 if kind=='rules' else .45)
    if kind=='case':
        pause=next(c for c in s['cues'] if c.get('pause'))
        for remaining in range(5,0,-1):
            art=Image.new('RGBA',(216,216));d=ImageDraw.Draw(art)
            d.ellipse((10,10,206,206),outline='#39464B',width=10)
            d.arc((10,10,206,206),-90,-90+360*remaining/5,fill=st.GOLD,width=10)
            a=st.text_layer(str(remaining),38,800,st.GOLD);art.alpha_composite(a,(round((216-a.width)/2),62))
            at=pause['start']-start+(5-remaining)
            add(art,st.px(1788)-108,st.px(587)-108,at,at+1)
    # Original subtitle function provides the exact rounded panel and text pixels.
    for cue in s['cues']:
        if cue.get('pause'):continue
        canvas=Image.new('RGBA',(3840,2160));st.subtitle(canvas,{'cues':[cue]},(cue['start']+cue['end'])/2)
        box=canvas.getbbox();add(canvas.crop(box),box[0],box[1],cue['start']-start,cue['end']-start)
    command=['ffmpeg','-nostdin','-y','-v','warning','-threads','1','-loop','1','-framerate','25','-i',str(base)]
    for obj in layers:command+=['-threads','1','-loop','1','-framerate','25','-i',str(obj['path'])]
    filters=['[0:v]format=rgba[b0]'];current='b0'
    for i,obj in enumerate(layers):
        name=f'l{i}';next_name=f'b{i+1}'
        expr=f'[{i+1}:v]format=rgba'
        if obj['rotate'] is not None:expr+=f",rotate='{obj['rotate']}*PI/180*t':ow=iw:oh=ih:c=none"
        if obj['fade']:expr+=f",fade=t=in:st={obj['start']:.6f}:d={obj['fade']}:alpha=1"
        expr+=f'[{name}]';filters.append(expr)
        y=str(obj['y'])
        if obj['slide']:y+=f"+{obj['slide']}*pow(1-clip((t-{obj['start']:.6f})/0.65,0,1),3)"
        filters.append(f"[{current}][{name}]overlay=x={obj['x']}:y='{y}':enable='gte(t,{obj['start']:.6f})*lt(t,{obj['end']:.6f})':eof_action=repeat:shortest=1[{next_name}]")
        current=next_name
    # Gold progress line at the same coordinates, smoothly driven by global time.
    gold='#B28A2C' if light else st.GOLD
    filters.append(f'color=c={gold}:s=3536x6:r=25:d={duration}[progress]')
    filters.append(f"[{current}][progress]overlay=x='152-3536+3536*(t+{start})/{tl['duration']}':y=2062:shortest=1[p]")
    filters.append(f"[p]drawbox=x=0:y=2062:w=152:h=6:color={st.IVORY if light else st.DARK}:t=fill[q]")
    current='q'
    if index:
        filters.append(f'color=c={st.DARK}:s=3840x2160:r=25:d={duration}[cover]')
        filters.append(f"[{current}][cover]overlay=x='3840*(1-pow(1-min(t/0.38,1),3))':y=0:enable='lt(t,0.38)':shortest=1[w]")
        filters.append(f'color=c={st.GOLD}:s=10x2160:r=25:d={duration}[edge]')
        filters.append("[w][edge]overlay=x='3840*(1-pow(1-min(t/0.38,1),3))-10':y=0:enable='lt(t,0.38)':shortest=1[z]")
        current='z'
    filters.append(f'[{current}]format=yuv420p[out]')
    filterfile=layerdir/'composition.ffmpeg';filterfile.write_text(';\n'.join(filters))
    command+=['-filter_complex_threads','1','-filter_complex_script',str(filterfile),'-map','[out]','-an','-c:v','libx264','-preset','veryfast','-crf','17','-threads','2','-t',str(duration),str(path)]
    began=time.monotonic()
    with (layerdir/'ffmpeg.log').open('w') as log:subprocess.run(command,stdout=log,stderr=log,check=True,timeout=600)
    print(v['id'],f'scene {index+1}/6 exported in {time.monotonic()-began:.1f}s',flush=True)
    return path


def render(v):
    folder=r.WORK/v['id'];tl=json.loads((folder/'timeline.json').read_text());r.configure(v,tl)
    fingerprint=hashlib.sha256(Path(__file__).read_bytes()+(r.ROOT/'approved_style.py').read_bytes()+(r.ROOT/'render_series.py').read_bytes()+(folder/'timeline.json').read_bytes()).hexdigest()
    out=r.OUT/(v['id']+'.mp4')
    if out.exists() and (folder/'render.json').exists():
        if json.loads((folder/'render.json').read_text()).get('render_sha256')==fingerprint:
            print(v['id'],'reference video cached',flush=True);return
    scenes=[render_scene(v,tl,s,i,folder) for i,s in enumerate(tl['scenes'])]
    concat=folder/'scenes.txt';concat.write_text('\n'.join(f"file '{p}'" for p in scenes)+'\n')
    tmp=out.with_suffix('.layered.partial.mp4')
    subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-f','concat','-safe','0','-i',str(concat),'-i',str(folder/'narration.wav'),'-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-b:a','192k','-af','loudnorm=I=-16:TP=-1.5:LRA=11','-ar','48000','-movflags','+faststart','-t',str(tl['duration']),str(tmp)],check=True)
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(tmp)]))
    video=next(s for s in probe['streams'] if s['codec_type']=='video');audio=next(s for s in probe['streams'] if s['codec_type']=='audio')
    assert (video['width'],video['height'])==(3840,2160) and abs(float(probe['format']['duration'])-tl['duration'])<.1
    assert audio['sample_rate']=='48000'
    tmp.replace(out)
    subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-threads','1','-ss','3','-i',str(out),'-frames:v','1','-vf','scale=1280:-1','-filter_threads','1','-threads','1',str(out.with_suffix('.jpg'))],check=True)
    cues=[c for s in tl['scenes'] for c in s['cues'] if not c.get('pause')]
    (folder/'subtitles.srt').write_text('\n\n'.join(f'{i+1}\n{r.stamp(c["start"])} --> {r.stamp(c["end"])}\n{c["text"]}' for i,c in enumerate(cues))+'\n')
    result=dict(id=v['id'],duration_seconds=float(probe['format']['duration']),bytes=out.stat().st_size,width=video['width'],height=video['height'],voice=tl['voice'],rate=tl['rate'],reference_style=tl['reference_style'],render_sha256=fingerprint)
    (folder/'render.json').write_text(json.dumps(result,indent=2)+'\n')
    print(v['id'],f'{result["duration_seconds"]:.2f}s',out.stat().st_size,'REFERENCE VIDEO READY',flush=True)

if __name__=='__main__':
    for video in json.loads((r.ROOT/'series.json').read_text()):
        if len(sys.argv)>1 and video['id'] not in sys.argv[1:]:continue
        render(video)
