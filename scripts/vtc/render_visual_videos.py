"""Render eight continuous VTC lessons with punctuated captions and motion graphics.

Henri narrates the existing, user-authorized course text. Only these course texts
are sent to the same speech service used by the previous edition. No learner
data are read. Media are immutable; resumable scratch caches are content hashed.
"""
import asyncio
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import edge_tts.communicate as communication
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.aps62_v5.captions import canonical, timestamp
from scripts.render_aps62_v5 import speech, duration, run, FONT, TITLE_FONT, draw_text, SETTINGS
from scripts.vtc.build_visual_scripts import build

OUT = ROOT / 'elearning_native/vtc'
ASSETS = OUT / 'assets/media/vtc/v4'
WORK = Path(os.environ.get('VTC_RENDER_WORK', '/tmp/vtc-v4'))
PURPLE = '#7045bd'
INK = '#281c3a'


def wrapped(text, size, width, limit):
    font = ImageFont.truetype(str(FONT), size)
    lines, current = [], ''
    for word in text.split():
        trial = (current + ' ' + word).strip()
        if current and font.getlength(trial) > width:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    assert len(lines) <= limit, (text, lines)
    return r'\N'.join(lines)


def icon(d, x, y, kind):
    """Purpose-made vector pictograms for sequence, document, route and checking."""
    color = PURPLE
    if kind == 0:
        d.rounded_rectangle((x, y, x+52, y+66), 6, outline=color, width=3)
        for j, w in enumerate((30, 34, 24)):
            d.line((x+9, y+20+j*12, x+9+w, y+20+j*12), fill=color, width=3)
    elif kind == 1:
        d.line((x+7,y+52,x+7,y+20,x+45,y+20,x+45,y+54),fill=color,width=4)
        d.ellipse((x-1,y+44,x+15,y+60),fill=color)
        d.ellipse((x+37,y+46,x+53,y+62),outline=color,width=4)
        d.polygon([(x+18,y+13),(x+29,y+20),(x+18,y+27)], fill=color)
    else:
        d.ellipse((x-3,y+5,x+60,y+68),outline=color,width=3)
        d.line((x+12,y+37,x+24,y+49,x+46,y+25),fill=color,width=5)


def background(letter, scene, index, count):
    im = Image.new('RGB', (1280,720), '#f8f5fd')
    d = ImageDraw.Draw(im)
    d.rectangle((0,0,1280,8),fill=PURPLE)
    draw_text(d,'INTÉGRALE ACADEMY  /  CHAUFFEUR VTC',(46,28),900,18,PURPLE,1,True)
    draw_text(d,f'MODULE {letter}  ·  LEÇON {scene["ref"]}',(988,28),246,17,PURPLE,1)
    draw_text(d,scene['label'].upper(),(46,82),1140,18,PURPLE,1,True)
    bottom=draw_text(d,scene['title'],(46,117),1190,37,INK,2,True)
    assert bottom < 224
    if scene['kind'] == 'concept':
        # Preserve the complete manual illustration instead of cropping it.
        pic=ImageOps.contain(Image.open(OUT/'assets'/scene['image']).convert('RGB'),(348,320))
        im.paste(pic,(48+(348-pic.width)//2,235+(320-pic.height)//2))
        d=ImageDraw.Draw(im)
        for j in range(3):
            y=235+j*108
            d.rounded_rectangle((425,y,1233,y+96),16,fill='#eee6f8')
            d.ellipse((443,y+22,490,y+69),fill=PURPLE)
            draw_text(d,str(j+1),(459,y+32),30,19,'white',1,True)
    else:
        for j in range(3):
            x=46+j*407
            d.rounded_rectangle((x,238,x+374,557),18,fill='#eee6f8')
            icon(d,x+26,256,j)
            if j < 2:
                d.line((x+379,399,x+398,399),fill=PURPLE,width=4)
                d.polygon([(x+394,392),(x+403,399),(x+394,406)],fill=PURPLE)
    for j in range(count):
        x=46+j*1188/count
        d.rounded_rectangle((x,578,x+1188/count-3,583),2,fill=PURPLE if j<=index else '#ddd1ed')
    d.rectangle((0,600,1280,720),fill='#1d1429')
    return im


def render(letter,row,voices,signature):
    folder=WORK/letter
    # Each paragraph is synthesized separately for robust timings and recovery.
    # The end-to-end narration duration is checked, never padded to five minutes.
    audio_seconds=sum(duration(a) for a,_ in voices)
    assert audio_seconds>=300,(letter,audio_seconds)
    events=[];frames=[];parts=[];cues_all=[];chapters=[];offset=0
    def event(start,end,text,style='Visual',layer=1):
        events.append(f'Dialogue: {layer},{timestamp(start)[:-1]},{timestamp(end)[:-1]},{style},,0,0,0,,{text}\n')
    for i,(scene,(audio,cues)) in enumerate(zip(row['scenes'],voices)):
        seconds=duration(audio)
        # Captions stop at the speech segment boundary; no overlap at a cut.
        end=offset+seconds
        picture=background(letter,scene,i,len(row['scenes']))
        png=folder/f'scene-{i:02}.png';picture.save(png)
        frames.extend([f"file '{png}'",f'duration {seconds:.6f}'])
        parts.append(audio)
        chapters.append(dict(ref=scene['ref'],title=scene['title'],kind=scene['kind'],start_seconds=round(offset,3),end_seconds=round(end,3)))
        for j,point in enumerate(scene['points']):
            reveal=offset+(.15+j*min(6.0,seconds/4))
            if scene['kind']=='concept':
                x,y=510,247+j*108
                title=point['label'];content=point['text']
                title_size,body_size,width=21,25,694
                title_lines,body_lines=1,2
            else:
                x,y=72+j*407,349
                title=point['title'];content=point['text']
                title_size,body_size,width=25,26,318
                title_lines,body_lines=2,4
            value=r'{\an7\move('+str(x+20)+','+str(y)+','+str(x)+','+str(y)+r',0,550)\fad(260,100)\fs'+str(title_size)+r'\b1\c&HBD4570&}'+wrapped(title,title_size,width,title_lines)
            value+=r'\N{\fs'+str(body_size)+r'\b0\c&H3A1C28&}'+wrapped(content,body_size,width,body_lines)
            event(reveal,end,value)
            # An animated rule grows under each new idea and leads the eye.
            if scene['kind']=='method':
                px=72+j*407
                event(reveal,end,r'{\an7\pos('+str(px)+r',543)\p1\c&HBD4570&\fscx0\t(0,1000,\fscx100)}m 0 0 l 318 0 318 4 0 4',layer=0)
        for c in cues:
            adjusted=dict(text=c['text'],start=round(c['start']+offset,3),end=round(min(c['end']+offset,end-.01),3))
            assert adjusted['end']>adjusted['start']
            cues_all.append(adjusted)
            event(adjusted['start'],adjusted['end'],c['text'].replace('\n',r'\N'),'Caption',2)
        if i==0:
            poster=picture.copy();dd=ImageDraw.Draw(poster)
            for j,p in enumerate(scene['points']):
                draw_text(dd,p['label'],(510,247+j*108),694,21,PURPLE,1,True)
                draw_text(dd,p['text'],(510,277+j*108),694,24,INK,2)
            poster.save(ASSETS/f'lesson-{letter.lower()}.jpg',quality=88)
        offset=end
    frames.append(f"file '{png}'")
    (folder/'frames.txt').write_text('\n'.join(frames)+'\n')
    (folder/'audio.txt').write_text(''.join(f"file '{p}'\n" for p in parts))
    merged=folder/'narration.wav'
    run(['ffmpeg','-nostdin','-v','error','-y','-f','concat','-safe','0','-i',str(folder/'audio.txt'),'-c:a','pcm_s16le',str(merged)])
    header='[Script Info]\nScriptType: v4.00+\nPlayResX: 1280\nPlayResY: 720\nWrapStyle: 2\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Caption,Manrope,36,&H00FFFFFF,&H00FFFFFF,&H0029141D,&H0029141D,0,0,0,0,100,100,0,0,1,0,0,2,55,55,21,1\nStyle: Visual,Manrope,26,&H003A1C28,&H003A1C28,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
    ass=folder/'lesson.ass';ass.write_text(header+''.join(events))
    target=ASSETS/f'lesson-{letter.lower()}.mp4';temporary=folder/'complete.mp4'
    run(['ffmpeg','-nostdin','-v','error','-y','-f','concat','-safe','0','-i',str(folder/'frames.txt'),'-i',str(merged),
        '-t',str(offset),'-vf',f'fps=20,ass={ass}:fontsdir={FONT.parent},format=yuv420p',
        '-c:v','libx264','-preset','veryfast','-crf','27','-threads','2','-c:a','aac','-b:a','80k','-ar','48000','-movflags','+faststart',str(temporary)])
    actual=duration(temporary)
    assert actual>=300 and abs(actual-offset)<.4
    temporary.replace(target)
    vtt='WEBVTT\n\n'+''.join(f"{timestamp(c['start'])} --> {timestamp(c['end'])}\n{c['text']}\n\n" for c in cues_all)
    (ASSETS/f'lesson-{letter.lower()}.vtt').write_text(vtt.rstrip()+'\n')
    result=dict(src=f'media/vtc/v4/lesson-{letter.lower()}.mp4',poster=f'media/vtc/v4/lesson-{letter.lower()}.jpg',
        captions=f'media/vtc/v4/lesson-{letter.lower()}.vtt',duration_seconds=actual,narration_seconds=audio_seconds,
        transcript=row['transcript'],voice=SETTINGS['voice'],rate=SETTINGS['rate'],audio=True,burned_captions=True,
        course_only=True,animated=True,chapters=chapters,content_sha256=signature,render_revision=4)
    (folder/'result.json').write_text(json.dumps(result,ensure_ascii=False))
    print('READY',letter,round(actual,1),'seconds',target.stat().st_size,'bytes',flush=True)
    return result


async def main():
    communication._SSL_CTX.load_verify_locations(cafile='/etc/ssl/certs/ca-certificates.crt')
    ASSETS.mkdir(parents=True,exist_ok=True);WORK.mkdir(parents=True,exist_ok=True)
    rows=build();only=os.environ.get('VTC_ONLY')
    path=OUT/'video_manifest_v4.json'
    manifest=json.loads(path.read_text()) if path.exists() else {}
    speech_slots=asyncio.Semaphore(4);render_slots=asyncio.Semaphore(2)
    pool=concurrent.futures.ThreadPoolExecutor(max_workers=2)
    async def one(letter,row):
        folder=WORK/letter;folder.mkdir(exist_ok=True)
        signature=hashlib.sha256(json.dumps(row,sort_keys=True,ensure_ascii=False).encode()+Path(__file__).read_bytes()).hexdigest()
        cached=json.loads((folder/'result.json').read_text()) if (folder/'result.json').exists() else {}
        if cached.get('content_sha256')==signature and (ASSETS/f'lesson-{letter.lower()}.mp4').exists():
            result=cached
        else:
            voices=await asyncio.gather(*(speech(s['text'],folder,i,speech_slots) for i,s in enumerate(row['scenes'])))
            print('NARRATION',letter,round(sum(duration(a) for a,_ in voices),1),'seconds',flush=True)
            async with render_slots:
                result=await asyncio.get_running_loop().run_in_executor(pool,render,letter,row,voices,signature)
        manifest[letter]=result
        path.write_text(json.dumps(dict(sorted(manifest.items())),ensure_ascii=False,indent=2)+'\n')
    await asyncio.gather(*(one(letter,row) for letter,row in rows.items() if not only or letter==only))


if __name__=='__main__':
    asyncio.run(main())
