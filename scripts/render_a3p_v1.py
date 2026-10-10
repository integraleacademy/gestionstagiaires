"""Build eight Henri-narrated module syntheses from the supplied A3P manual.

Every spoken word is captioned. Durations come from decoded audio/video, never
from regulatory hours. The output remains administrator preparation material.
"""
import asyncio
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import edge_tts
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.aps62_v5.captions import make_cues, timestamp
RES=ROOT/'elearning_native/a3p_resources'
FONT=ROOT/'scripts/academy_videos/assets/Manrope-600.ttf'
BOLD=ROOT/'scripts/academy_videos/assets/Manrope-800.ttf'
ASSETS=RES/'assets/media/a3p/v1'
WORK=Path(os.environ.get('A3P_WORK','/tmp/a3p-media'))
VOICE='fr-FR-HenriNeural'
RATE='-2%'
TITLES={'02':'Cadre juridique et déontologie','03':'Gestion des conflits','04':'Consignes et transmissions','05':'Prévention du risque terroriste','06':'Protection physique des personnes','07':'Techniques professionnelles et capacités','08':'Gestion des risques et situations dégradées','09':'Secourisme tactique d’urgence'}


def run(args):
    r=subprocess.run(args,capture_output=True)
    if r.returncode:
        raise RuntimeError(r.stderr.decode(errors='replace'))
    return r


def duration(path):
    return float(run(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',str(path)]).stdout)


def scenes(uv):
    manual=json.loads((RES/'manual.json').read_text())
    case=json.loads((RES/'cases.json').read_text())[uv]
    result=[{'title':TITLES[uv], 'label':'Synthèse de l’unité', 'idea':'Comprendre les repères, les appliquer à une situation et connaître ses limites.',
             'text':'Bienvenue dans cette synthèse A3P : '+TITLES[uv]+'. Cette vidéo reprend les repères des leçons du manuel Intégrale Academy. Elle accompagne la lecture et les exercices. Elle ne délivre aucune heure certifiante et ne valide aucun geste pratique. Les situations réelles, déplacements, matériels et gestes professionnels nécessitent une formation encadrée. Nous allons parcourir les idées essentielles puis analyser une situation professionnelle.'}]
    for lesson in manual['lessons']:
        if not lesson['ref'].startswith(uv+'.'): continue
        paragraphs=[c['text'] for p in lesson['pages'] for c in p['components'] if c['kind']=='paragraph' and len(c['text'])>180]
        assert paragraphs,lesson['ref']
        # Complete authored paragraphs; never truncate a sentence to meet a clock.
        explanation=' '.join(paragraphs[:2])
        result.append({'title':lesson['title'],'label':'Leçon '+lesson['ref'],
                       'idea':lesson['objective'], 'ref':lesson['ref'],
                       'page':lesson['source_pages'][0],
                       'text':lesson['title']+'. '+lesson['objective']+' '+explanation})
    result.append({'title':case['title'],'label':'Situation professionnelle','idea':case['situation'],'text':'Analysons maintenant une situation fictive. '+case['situation']})
    for index,step in enumerate(case['steps']):
        correct=step['options'][step['answer']]
        result.append({'title':step['prompt'],'label':'Analyser la décision '+str(index+1),'idea':correct,
                       'text':step['prompt']+' La décision adaptée est la suivante. '+correct+'. '+step['feedback']})
    result.append({'title':'Faire le point et poursuivre','label':'À retenir','idea':case['criteria'][0]+'. '+case['criteria'][-1]+'.',
                   'text':case['example']+' '+case['debrief']+' Vous pouvez maintenant reprendre les leçons, tester les questions et réaliser l’étude de cas interactive. L’examen blanc est un entraînement pédagogique : il ne remplace pas l’évaluation officielle.'})
    return result


def draw_text(d,text,x,y,width,size,lines,bold=False):
    font=ImageFont.truetype(str(BOLD if bold else FONT),size)
    out=[];line=''
    for word in text.split():
        trial=(line+' '+word).strip()
        if line and font.getlength(trial)>width:
            out.append(line);line=word
        else:line=trial
    if line:out.append(line)
    if len(out)>lines:
        if size>20:return draw_text(d,text,x,y,width,size-2,lines,bold)
        raise ValueError('A3P slide overflow: '+text)
    for line in out:
        d.text((x,y),line,font=font,fill='#203d30')
        y+=size*1.36
    return y


def frame(uv,scene,index,total):
    im=Image.new('RGB',(1280,720),'#f2f6ef');d=ImageDraw.Draw(im)
    d.rectangle((0,0,1280,10),fill='#135846')
    draw_text(d,'INTÉGRALE ACADEMY / A3P',(42),28,820,18,1,True)
    draw_text(d,f'UV {uv} · {index+1} / {total}',1000,28,242,18,1)
    draw_text(d,scene['label'].upper(),48,94,1178,20,1,True)
    end=draw_text(d,scene['title'],48,133,1174,38,3,True)
    d.rounded_rectangle((48,end+16,120,end+21),radius=3,fill='#a88b34')
    top=max(end+45,265)
    d.rounded_rectangle((48,top,1232,555),radius=18,fill='#e0ecdd')
    draw_text(d,scene['idea'],76,top+22,1128,30,6)
    if scene.get('ref'):
        draw_text(d,f"Repère du manuel · page {scene['page']} · lecture et exercices à poursuivre dans la leçon",48,572,1160,16,1)
    else:
        draw_text(d,'Préparation pédagogique · les compétences pratiques se travaillent avec un formateur',48,572,1160,16,1)
    d.rectangle((0,610,1280,720),fill='#101f19')
    return im


async def speak(text,folder,index,slots):
    signature=hashlib.sha256((VOICE+RATE+text).encode()).hexdigest()[:16]
    path=folder/f'{index}-{signature}.mp3'
    async with slots:
        for attempt in range(4):
            try:
                boundaries=[]
                async def collect():
                    with path.with_suffix('.partial').open('wb') as out:
                        async for item in edge_tts.Communicate(text,voice=VOICE,rate=RATE,boundary='WordBoundary').stream():
                            if item['type']=='audio':out.write(item['data'])
                            elif item['type']=='WordBoundary':boundaries.append(item)
                await asyncio.wait_for(collect(),timeout=120)
                cues=make_cues(text,boundaries)
                path.with_suffix('.partial').replace(path)
                seconds=duration(path)
                # The audio must include the final spoken word; caption tail is cosmetic.
                assert seconds >= (boundaries[-1]['offset']+boundaries[-1]['duration'])/1e7-.08
                run(['ffmpeg','-nostdin','-v','error','-xerror','-i',str(path),'-f','null','-'])
                return path,cues
            except Exception:
                if attempt==3:raise
                await asyncio.sleep(2*(attempt+1))


def encode(uv,items,voices,folder):
    captions=[];chapters=[];parts=[];offset=0;audio_total=0
    for index,(scene,(audio,cues)) in enumerate(zip(items,voices)):
        png=folder/f'{index}.png'
        picture=frame(uv,scene,index,len(items));picture.save(png)
        if index==0:picture.save(ASSETS/f'uv-{uv}.jpg',quality=85)
        ass=folder/f'{index}.ass'
        header='[Script Info]\nScriptType: v4.00+\nPlayResX: 1280\nPlayResY: 720\nWrapStyle: 2\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,Manrope,36,&H00FFFFFF,&H00FFFFFF,&H00101F19,&H00101F19,0,0,0,0,100,100,0,0,1,0,0,2,55,55,20,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
        events=['Dialogue: 0,'+timestamp(c['start'])[:-1]+','+timestamp(c['end'])[:-1]+',Default,,0,0,0,,'+c['text'].replace('\n',r'\N')+'\n' for c in cues]
        ass.write_text(header+''.join(events))
        actual_audio=duration(audio);audio_total+=actual_audio
        target=max(actual_audio+.25,cues[-1]['end']+.1)
        part=folder/f'{index}.mp4'
        run(['ffmpeg','-nostdin','-v','error','-y','-loop','1','-framerate','8','-i',str(png),'-i',str(audio),
             '-t',str(target),'-vf',f'ass={ass}:fontsdir={FONT.parent},format=yuv420p',
             '-c:v','libx264','-preset','ultrafast','-crf','29','-threads','2','-c:a','aac','-b:a','64k','-ar','48000','-af','apad',str(part)])
        actual=duration(part)
        assert abs(actual-target)<.3
        chapters.append({'title':scene['label']+' · '+scene['title'],'start_seconds':round(offset,3),'end_seconds':round(offset+actual,3)})
        captions.extend(dict(c,start=c['start']+offset,end=c['end']+offset) for c in cues)
        parts.append(part);offset+=actual
    concat=folder/'concat.txt';concat.write_text(''.join(f"file '{p}'\n" for p in parts))
    out=ASSETS/f'uv-{uv}.mp4'
    run(['ffmpeg','-nostdin','-v','error','-y','-f','concat','-safe','0','-i',str(concat),'-c:v','copy','-c:a','aac','-b:a','64k','-af','aresample=async=1:first_pts=0','-movflags','+faststart',str(out)])
    actual=duration(out)
    assert abs(actual-offset)<.5 and actual>=captions[-1]['end']
    assert out.stat().st_size<95*1024*1024
    run(['ffmpeg','-nostdin','-v','error','-xerror','-i',str(out),'-f','null','-'])
    (ASSETS/f'uv-{uv}.vtt').write_text('WEBVTT\n\n'+''.join(f"{timestamp(c['start'])} --> {timestamp(c['end'])}\n{c['text']}\n\n" for c in captions).rstrip()+'\n')
    transcript='\n\n'.join(s['text'] for s in items)
    meta={'id':'a3p-uv-'+uv+'-video','title':'Synthèse vidéo · '+TITLES[uv],'src':f'media/a3p/v1/uv-{uv}.mp4',
          'poster':f'media/a3p/v1/uv-{uv}.jpg','captions':f'media/a3p/v1/uv-{uv}.vtt','duration_seconds':actual,
          'narration_seconds':audio_total,'voice':VOICE,'rate':RATE,'burned_captions':True,'required':False,
          'transcript':transcript,'chapters':chapters,'source_sha256':hashlib.sha256((RES/'manual.json').read_bytes()+(RES/'cases.json').read_bytes()).hexdigest(),
          'video_sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'words':len(transcript.split())}
    (ASSETS/f'uv-{uv}.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n')
    print(f'UV {uv}: {len(items)} chapitres, {meta["words"]} mots, {actual:.2f} secondes, {out.stat().st_size} octets',flush=True)


async def main():
    uv=os.environ['A3P_UV'];assert uv in TITLES
    ASSETS.mkdir(parents=True,exist_ok=True);folder=WORK/uv;folder.mkdir(parents=True,exist_ok=True)
    items=scenes(uv)
    # Visual overflow is checked before contacting the speech service.
    for i,s in enumerate(items):frame(uv,s,i,len(items))
    slots=asyncio.Semaphore(2)
    voices=await asyncio.gather(*(speak(s['text'],folder,i,slots) for i,s in enumerate(items)))
    encode(uv,items,voices,folder)

if __name__=='__main__':asyncio.run(main())
