"""Render real Henri narration and synchronized captions for authored lessons.

Uses the same speech service and voice as the existing public APS/A3P builds.
Only fictional educational scripts are sent; no user records or secrets.
"""
from __future__ import annotations
import argparse
import asyncio
import concurrent.futures
import hashlib
import json
import math
import os
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from scripts.aps62_v5.captions import make_cues, timestamp
from .compile import ROOT, RES, all_cards, narration, signature

FONT = ROOT/'scripts/academy_videos/assets/Manrope-600.ttf'
BOLD = ROOT/'scripts/academy_videos/assets/Manrope-800.ttf'
DEST = RES/'assets/media/a3p/v4'
WORK = Path(os.environ.get('A3P_MEDIA_WORK', '/tmp/a3p157-media'))
VOICE, RATE = 'fr-FR-HenriNeural', '-2%'


def run(args):
    result = subprocess.run(args, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors='replace')[-3000:])
    return result.stdout


def duration(path):
    return float(run(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',str(path)]))


def text(draw, value, x, y, width, size=30, max_lines=5, bold=False, color='#183c30'):
    for points in range(size, 13, -1):
        font = ImageFont.truetype(str(BOLD if bold else FONT), points)
        lines, line = [], ''
        for word in value.split():
            trial = (line + ' ' + word).strip()
            if line and font.getlength(trial) > width:
                lines.append(line); line = word
            else:
                line = trial
        if line:
            lines.append(line)
        if len(lines) <= max_lines:
            for line in lines:
                draw.text((x,y),line,font=font,fill=color); y += points*1.35
            return y
    raise ValueError('Text overflow: '+value)


def frame(row, scene, number, total):
    canvas = Image.new('RGB',(1280,720),'#f3f6ef')
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0,0,1280,10),fill='#135846')
    text(draw,'INTÉGRALE ACADEMY · A3P',42,29,850,19,1,True)
    text(draw,f"UV {row['uv']} · {number+1:02}/{total:02}",1010,29,230,17,1)
    text(draw,scene['label'].upper(),48,91,1170,20,2,True,color='#65794a')
    text(draw,scene['title'],48,133,1184,36,3,True)
    cards = scene['cards'][:4]
    cols = 2 if len(cards)>1 else 1
    rows = math.ceil(len(cards)/cols)
    width = (1184-(cols-1)*24)/cols
    height = min(248, (304-(rows-1)*18)/rows)
    for i, value in enumerate(cards):
        x = 48 + (i%cols)*(width+24)
        y = 271 + (i//cols)*(height+18)
        draw.rounded_rectangle((x,y,x+width,y+height),radius=17,fill='#e1ecdf',outline='#b9ceb9',width=2)
        draw.ellipse((x+17,y+17,x+51,y+51),fill='#135846')
        text(draw,str(i+1),x+28,y+21,23,18,1,True,color='white')
        text(draw,value,x+69,y+22,width-91,27,max(2,round(height/34)-1))
    text(draw,'Observer les informations · comprendre la règle · expliquer le choix',48,589,1184,17,1)
    draw.rectangle((0,620,1280,720),fill='#11291f')
    return canvas


async def speech(value, semaphore):
    import edge_tts
    key = hashlib.sha256((VOICE+RATE+value).encode()).hexdigest()
    folder = WORK/'speech'; folder.mkdir(parents=True,exist_ok=True)
    audio, timings = folder/(key+'.mp3'), folder/(key+'.json')
    if audio.is_file() and timings.is_file():
        return audio, json.loads(timings.read_text())
    async with semaphore:
        for attempt in range(4):
            try:
                boundaries = []
                async def collect():
                    with audio.with_suffix('.partial').open('wb') as out:
                        async for item in edge_tts.Communicate(value,voice=VOICE,rate=RATE,boundary='WordBoundary').stream():
                            if item['type']=='audio': out.write(item['data'])
                            elif item['type']=='WordBoundary': boundaries.append(item)
                await asyncio.wait_for(collect(),timeout=120)
                cues = make_cues(value,boundaries)
                audio.with_suffix('.partial').replace(audio)
                assert duration(audio) >= (boundaries[-1]['offset']+boundaries[-1]['duration'])/1e7-.08
                timings.write_text(json.dumps(cues,ensure_ascii=False))
                return audio,cues
            except Exception:
                if attempt==3: raise
                await asyncio.sleep(2*(attempt+1))


def encode(row, scenes, voices):
    folder=WORK/row['id']; folder.mkdir(parents=True,exist_ok=True)
    parts,captions,chapters=[],[],[]
    offset=0; audio_seconds=0
    for index,(scene,(audio,cues)) in enumerate(zip(scenes,voices)):
        picture=frame(row,scene,index,len(scenes)); png=folder/f'{index}.png'; picture.save(png)
        if index==0: picture.save(DEST/(row['id']+'.jpg'),quality=87)
        srt=folder/f'{index}.srt'
        srt.write_text(''.join(f"{n+1}\n{timestamp(c['start'],',')} --> {timestamp(c['end'],',')}\n{c['text']}\n\n" for n,c in enumerate(cues)))
        real_audio=duration(audio); audio_seconds+=real_audio
        seconds=max(real_audio+.25,cues[-1]['end']+.1)
        part=folder/f'{index}.mp4'
        filt=f"subtitles={srt}:fontsdir={FONT.parent}:force_style='FontName=Manrope,FontSize=16,Outline=0,Shadow=0,MarginV=14,Alignment=2',format=yuv420p"
        run(['ffmpeg','-nostdin','-v','error','-y','-loop','1','-framerate','6','-i',str(png),'-i',str(audio),'-t',str(seconds),'-vf',filt,
             '-c:v','libx264','-preset','veryfast','-crf','30','-tune','stillimage','-threads','2',
             '-c:a','aac','-b:a','56k','-ar','48000','-af','apad',str(part)])
        actual=duration(part)
        assert abs(actual-seconds)<.3
        chapters.append(dict(title=scene['title'],start_seconds=round(offset,3),end_seconds=round(offset+actual,3)))
        captions.extend(dict(c,start=c['start']+offset,end=c['end']+offset) for c in cues)
        parts.append(part); offset+=actual
    concat=folder/'concat.txt'; concat.write_text(''.join(f"file '{p}'\n" for p in parts))
    target=DEST/(row['id']+'.mp4')
    run(['ffmpeg','-nostdin','-v','error','-y','-f','concat','-safe','0','-i',str(concat),'-c:v','copy','-c:a','aac','-b:a','56k',
         '-af','aresample=async=1:first_pts=0','-movflags','+faststart',str(target)])
    measured=duration(target)
    assert measured>=300 and audio_seconds>=295, (row['id'],measured,audio_seconds)
    assert measured>captions[-1]['end'] and abs(measured-offset)<.5
    assert target.stat().st_size<95*1024*1024
    run(['ffmpeg','-nostdin','-v','error','-xerror','-i',str(target),'-f','null','-'])
    DEST.joinpath(row['id']+'.vtt').write_text('WEBVTT\n\n'+''.join(f"{timestamp(c['start'])} --> {timestamp(c['end'])}\n{c['text']}\n\n" for c in captions))
    metadata=dict(id=row['id']+'-video',title=row['title'],duration_seconds=measured,narration_seconds=audio_seconds,
        voice=VOICE,rate=RATE,required=True,burned_captions=True,chapters=chapters,
        transcript='\n\n'.join(s['text'] for s in scenes),source_sha256=signature(row,scenes),
        video_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
        **{k:'media/a3p/v4/'+row['id']+'.'+ext for k,ext in [('src','mp4'),('poster','jpg'),('captions','vtt')]})
    DEST.joinpath(row['id']+'.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n')
    print('RENDERED',row['id'],round(measured,2),'seconds',target.stat().st_size,'bytes',flush=True)
    return metadata


async def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--shard',type=int,default=0);parser.add_argument('--shards',type=int,default=1)
    parser.add_argument('--limit',type=int);parser.add_argument('--plan-only',action='store_true')
    args=parser.parse_args()
    rows=all_cards()[args.shard::args.shards]
    if args.limit: rows=rows[:args.limit]
    records=[(row,narration(row)) for row in rows]
    for row,scenes in records:
        for i,scene in enumerate(scenes): frame(row,scene,i,len(scenes))
    print('VALIDATED',len(records),'scripts',sum(len(s['text'].split()) for _,scenes in records for s in scenes),'words',flush=True)
    if args.plan_only:return
    DEST.mkdir(parents=True,exist_ok=True)
    speech_slots,render_slots=asyncio.Semaphore(4),asyncio.Semaphore(2)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        async def one(row,scenes):
            result=DEST/(row['id']+'.json')
            if result.is_file() and json.loads(result.read_text())['source_sha256']==signature(row,scenes):
                print('CACHED',row['id'],flush=True);return
            voices=await asyncio.gather(*(speech(scene['text'],speech_slots) for scene in scenes))
            async with render_slots:
                await asyncio.get_running_loop().run_in_executor(pool,encode,row,scenes,voices)
        await asyncio.gather(*(one(row,scenes) for row,scenes in records))


if __name__=='__main__':asyncio.run(main())
