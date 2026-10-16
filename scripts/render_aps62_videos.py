"""Illustrated, narrated APS decision capsules. Build-time dependencies only.

Piper / SIWIS French synthesis (dataset CC-BY 4.0, attribution in media credits).
Run with a Python environment containing piper-tts, Pillow and system ffmpeg.
"""
import json, os, re, subprocess, sys, wave
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps
from piper import PiperVoice, SynthesisConfig
from aps62_editorial import MODULES, records

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'elearning_native/aps62'
ASSETS=OUT/'assets/media/aps62'
WORK=Path('/tmp/aps62-video');WORK.mkdir(exist_ok=True)
NAVY='#172b4d';BLUE='#2860e8';YELLOW='#ffd56a';MUTED='#566783'
FONT='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
BOLD='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
W,H=1280,720

def font(size,bold=False):return ImageFont.truetype(BOLD if bold else FONT,size)
def wrap(text,size,width,bold=False):
    f=font(size,bold); lines=[];line=''
    for word in text.split():
        candidate=(line+' '+word).strip()
        if f.getlength(candidate)>width and line:lines.append(line);line=word
        else:line=candidate
    if line:lines.append(line)
    return lines
def fit(text,size,width,max_lines,bold=False):
    while size>18:
        lines=wrap(text,size,width,bold)
        if len(lines)<=max_lines:return lines,size
        size-=1
    raise ValueError('Overflow: '+text)
def draw_text(draw,text,xy,size,width,max_lines,color=NAVY,bold=False):
    lines,size=fit(text,size,width,max_lines,bold)
    for i,line in enumerate(lines):draw.text((xy[0],xy[1]+i*(size+12)),line,font=font(size,bold),fill=color)
    return xy[1]+len(lines)*(size+12)
def slide(title,label,text,image_path,index):
    im=Image.new('RGB',(W,H),'#f6f8fc');d=ImageDraw.Draw(im)
    d.rectangle((0,0,W,8),fill=BLUE)
    d.text((48,30),'INTÉGRALE ACADEMY  /  APS',font=font(18,True),fill=NAVY)
    d.text((48,93),label.upper(),font=font(20,True),fill=BLUE)
    d.rounded_rectangle((848,88,1234,622),radius=20,fill='#e2eafa')
    pic=ImageOps.fit(Image.open(image_path).convert('RGB'),(386,420))
    im.paste(pic,(848,88))
    d=ImageDraw.Draw(im)
    d.text((875,535),'OBSERVER',font=font(22,True),fill=NAVY)
    d.text((875,573),'COMPRENDRE · AGIR',font=font(18,True),fill=BLUE)
    y=draw_text(d,title,(48,143),38,745,3,bold=True)+24
    d.rectangle((48,y,122,y+5),fill=YELLOW)
    draw_text(d,text,(48,y+25),28,745,8,color=NAVY)
    for j in range(4):d.rounded_rectangle((48+j*196,658,228+j*196,665),radius=3,fill=BLUE if j<=index else '#dce4f2')
    d.text((48,681),'CAPSULE DE DÉCISION  ·  VOIX DE SYNTHÈSE',font=font(13),fill=MUTED)
    return im

def stamp(seconds):
    ms=round(seconds*1000);return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02}.{ms%1000:03}'

def main():
    model=sys.argv[1]; voice=PiperVoice.load(model)
    # Keep synthesis bounded on large shared hosts.
    cfg=SynthesisConfig(length_scale=1.02)
    manifest=json.loads((OUT/'video_manifest.json').read_text()) if (OUT/'video_manifest.json').exists() else {}
    all_rows=records()
    for code,_,_,scene,_ in MODULES:
        for n,row in enumerate(all_rows[code],1):
            sid=f'aps62-{code}-{n:02d}'
            if sid in manifest and (ASSETS/(sid+'.mp4')).exists():continue
            work=WORK/sid;work.mkdir(exist_ok=True)
            scene_path=ASSETS/f'scene-{scene}.webp'
            chunks=[('La situation',row['case']),
                    ('À vous de décider',row['good']+' Ou bien : '+row['bad']+' Mettez la vidéo en pause pour justifier votre choix.'),
                    ('Le raisonnement',row['reason']),
                    ('Le bon relais',row['model'])]
            segments=[];offset=0;vtt='WEBVTT\n\n';transcript=[]
            for i,(label,body) in enumerate(chunks):
                spoken=(row['title']+'. ' if i==0 else '')+label+'. '+body
                audio=work/f'{i}.wav'
                with wave.open(str(audio),'wb') as w:voice.synthesize_wav(spoken,w,cfg)
                with wave.open(str(audio),'rb') as w:duration=w.getnframes()/w.getframerate()+.5
                frame=slide(row['title'],label,body,scene_path,i);frame.save(work/f'{i}.png')
                if i==0:frame.save(ASSETS/(sid+'.jpg'),quality=82)
                # Gentle fade and a growing progress line; all instructional text remains static and readable.
                vf=f"fade=t=in:st=0:d=0.35,drawbox=x=48:y=642:w='min(782,782*t/{duration})':h=4:color=0x2860e8:t=fill,format=yuv420p"
                part=work/f'{i}.mp4'
                subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-loop','1','-framerate','12','-i',str(work/f'{i}.png'),'-i',str(audio),'-t',str(duration),'-vf',vf,'-c:v','libx264','-preset','veryfast','-crf','31','-tune','stillimage','-threads','2','-c:a','aac','-b:a','48k','-af','apad','-movflags','+faststart',str(part)],check=True)
                segments.append(part); transcript.append(label+' : '+body)
                sentences=re.split(r'(?<=[.!?])\s+',spoken); weight=sum(len(s) for s in sentences)
                cursor=offset
                for s in sentences:
                    end=cursor+duration*len(s)/weight
                    vtt+=f'{stamp(cursor)} --> {stamp(end)}\n{s}\n\n';cursor=end
                offset+=duration
            (work/'concat.txt').write_text(''.join(f"file '{p}'\n" for p in segments))
            destination=ASSETS/(sid+'.mp4')
            subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','concat','-safe','0','-i',str(work/'concat.txt'),'-c','copy','-movflags','+faststart',str(destination)],check=True)
            metadata=json.loads(subprocess.check_output(['ffprobe','-v','quiet','-show_format','-show_streams','-of','json',str(destination)]))
            duration=float(metadata['format']['duration'])
            assert any(s['codec_type']=='audio' for s in metadata['streams'])
            (ASSETS/(sid+'.vtt')).write_text(vtt.rstrip()+'\n')
            manifest[sid]={'src':f'media/aps62/{sid}.mp4','poster':f'media/aps62/{sid}.jpg',
                'captions':f'media/aps62/{sid}.vtt','duration_seconds':duration,'transcript':'\n\n'.join(transcript)}
            (OUT/'video_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
            print(sid,round(duration,1),'seconds',destination.stat().st_size,flush=True)
    print('DONE',len(manifest),'capsules',round(sum(v['duration_seconds'] for v in manifest.values())/60,1),'minutes',flush=True)

if __name__=='__main__':main()
