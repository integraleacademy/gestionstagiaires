"""Reproducible APS v2 capsules: approved Henri voice, timed burned-in captions.

Build dependencies: edge-tts, Pillow and ffmpeg (not runtime dependencies).
Only fictional pedagogical narration is sent to the speech service.
Existing v1 assets are immutable. Work files and completed speech are cached.
Usage: APS62_IMAGES=/path/to/recovered/images APS62_WORK=/tmp/aps62-henri python scripts/render_aps62_henri.py
"""
import asyncio, concurrent.futures, hashlib, json, os, subprocess, textwrap
from pathlib import Path
import edge_tts
import edge_tts.communicate as communication
from PIL import Image, ImageDraw, ImageFont, ImageOps
from aps62_editorial import MODULES, records

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'elearning_native/aps62'
ASSETS = OUT / 'assets/media/aps62/v2'
WORK = Path(os.environ.get('APS62_WORK', '/tmp/aps62-henri'))
SETTINGS = json.loads((ROOT / 'scripts/academy_videos/reference_settings.json').read_text())
NAMES = ['Briefing d’équipe', 'Sécurité devant', 'Observation et transmission',
         'Confidentialité', 'Accueil inclusif', 'Consigne remise', 'Dialogue calme dans',
         'Transmission radio', 'Dialogue calme et', 'Observation sécurisée',
         'Sécurisation d’une', 'Guidage serein', 'Compte rendu', 'Contrôle d’accès', 'Accueil sécurisé']
FONT = str(ROOT / 'scripts/academy_videos/assets/Manrope.ttf')
if not Path(FONT).exists(): FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
W, H = 1280, 720
ASSETS.mkdir(parents=True, exist_ok=True)
WORK.mkdir(parents=True, exist_ok=True)
communication._SSL_CTX.load_verify_locations(cafile='/etc/ssl/certs/ca-certificates.crt')

def run(args):
    result=subprocess.run(args, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors='replace'))
    return result

def duration(path):
    return float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',str(path)]))

def text(draw, words, x, y, width, size, color, max_lines=8):
    minimum = min(18,size)
    while size >= minimum:
        font = ImageFont.truetype(FONT, size)
        try: font.set_variation_by_axes([650 if size >= 30 else 500])
        except (OSError, AttributeError): pass
        lines, line = [], ''
        for word in words.split():
            candidate = (line + ' ' + word).strip()
            if font.getlength(candidate) > width and line: lines.append(line); line = word
            else: line = candidate
        if line: lines.append(line)
        if len(lines) <= max_lines: break
        size -= 1
    else: raise ValueError('Text overflow: ' + words)
    for line in lines:
        draw.text((x,y),line,font=font,fill=color); y += size * 1.4
    return y

def frame(row, label, body, image, code, index):
    im = Image.new('RGB',(W,H),'#f4f7fc'); d = ImageDraw.Draw(im)
    d.rectangle((0,0,W,9),fill='#2860e8')
    text(d,'INTÉGRALE ACADEMY  /  APS',48,28,800,18,'#172b4d')
    text(d,f'MODULE {code}  ·  {index+1:02d} / 04',975,28,270,15,'#566783')
    pic = ImageOps.fit(Image.open(image).convert('RGB'),(430,286))
    im.paste(pic,(802,92)); d = ImageDraw.Draw(im)
    text(d,label.upper(),48,92,730,19,'#2860e8')
    y = text(d,row['title'],48,132,706,34,'#172b4d',3) + 20
    d.rectangle((48,y,116,y+5),fill='#edbc48')
    text(d,body,48,y+23,706,25,'#223654',7)
    d.rounded_rectangle((802,402,1232,550),18,fill='#e3ecfc')
    text(d,['01  OBSERVER LES FAITS','02  COMPARER LES OPTIONS','03  EXPLIQUER SA DÉCISION','04  ORGANISER LE RELAIS'][index],823,427,388,17,'#2454a9',2)
    text(d,'Une décision se justifie par les faits, la règle et les limites de la mission.',823,469,388,17,'#172b4d',3)
    d.rectangle((0,590,W,H),fill='#101619')
    for j in range(4): d.rounded_rectangle((48+j*297,578,327+j*297,583),2,fill='#2860e8' if j<=index else '#d5e0f3')
    return im

def timestamp(seconds, separator='.'):
    ms = round(seconds*1000)
    return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02}{separator}{ms%1000:03}'

def cues_from_words(words):
    cues=[]; current=[]
    for word in words:
        if current and (len(' '.join(w['text'] for w in current))+len(word['text'])>88 or len(current)>=14):
            cues.append(current); current=[]
        current.append(word)
    if current: cues.append(current)
    return [{'start':c[0]['offset']/1e7,'end':(c[-1]['offset']+c[-1]['duration'])/1e7,
             'text':' '.join(w['text'] for w in c)} for c in cues]

async def speech(spoken, folder, n, semaphore):
    signature=hashlib.sha256((SETTINGS['voice']+SETTINGS['rate']+spoken).encode()).hexdigest()[:16]
    audio=folder/f'{n}-{signature}.mp3'; timing=audio.with_suffix('.json')
    if audio.exists() and timing.exists(): return audio,json.loads(timing.read_text())
    async with semaphore:
        for attempt in range(3):
            try:
                words=[]
                async def collect():
                    with audio.with_suffix('.partial').open('wb') as output:
                        async for chunk in edge_tts.Communicate(spoken,voice=SETTINGS['voice'],rate=SETTINGS['rate'],pitch=SETTINGS['pitch'],volume=SETTINGS['volume'],boundary='WordBoundary').stream():
                            if chunk['type']=='audio': output.write(chunk['data'])
                            elif chunk['type']=='WordBoundary': words.append(chunk)
                await asyncio.wait_for(collect(),timeout=90)
                if not words: raise ValueError('Missing caption timing')
                audio.with_suffix('.partial').replace(audio)
                cues=cues_from_words(words); timing.write_text(json.dumps(cues,ensure_ascii=False))
                return audio,cues
            except Exception:
                if attempt==2: raise
                await asyncio.sleep(2*(attempt+1))

def render(code,n,row,chunks,voices,image):
    sid=f'aps62-{code}-{n:02d}'; folder=WORK/sid; offset=0; allcues=[]; parts=[]
    for i,((label,body),(audio,cues)) in enumerate(zip(chunks,voices)):
        seconds=duration(audio)+.5
        picture=frame(row,label,body,image,code,i); picture.save(folder/f'{i}.png')
        if i==0: picture.save(ASSETS/f'{sid}.jpg',quality=86)
        srt=''.join(f"{j+1}\n{timestamp(c['start'],',')} --> {timestamp(c['end'],',')}\n{textwrap.fill(c['text'],width=58)}\n\n" for j,c in enumerate(cues))
        (folder/f'{i}.srt').write_text(srt)
        part=folder/f'{i}.mp4'; temporary=folder/f'{i}.partial.mp4'; parts.append(part)
        vf=f"subtitles={folder}/{i}.srt:fontsdir={Path(FONT).parent}:force_style='FontName=Manrope,FontSize=15,PrimaryColour=&H00FFFFFF,Outline=0,Shadow=0,MarginV=20,Alignment=2',format=yuv420p"
        run(['ffmpeg','-nostdin','-v','error','-y','-loop','1','-framerate','12','-i',str(folder/f'{i}.png'),'-i',str(audio),'-t',str(seconds),'-vf',vf,'-c:v','libx264','-preset','veryfast','-crf','28','-tune','stillimage','-threads','2','-c:a','aac','-b:a','80k','-ar','48000','-af','apad','-movflags','+faststart',str(temporary)])
        assert abs(duration(temporary)-seconds)<.2, f'Truncated scene: {sid}/{i}'
        temporary.replace(part)
        # Stream-copy joins use the encoded frame duration, not the unrounded audio time.
        encoded=duration(part)
        allcues.extend(dict(c,start=c['start']+offset,end=c['end']+offset) for c in cues)
        offset+=encoded
    (folder/'concat.txt').write_text(''.join(f"file '{p}'\n" for p in parts))
    destination=ASSETS/f'{sid}.mp4'; temporary=ASSETS/f'{sid}.partial.mp4'
    run(['ffmpeg','-nostdin','-v','error','-xerror','-y','-f','concat','-safe','0','-i',str(folder/'concat.txt'),'-c:v','copy','-c:a','aac','-b:a','80k','-af','aresample=async=1:first_pts=0','-movflags','+faststart',str(temporary)])
    assert abs(duration(temporary)-offset)<.3, f'Truncated capsule: {sid}'
    assert duration(temporary)>allcues[-1]['end'], f'Incomplete narration: {sid}'
    temporary.replace(destination)
    (ASSETS/f'{sid}.vtt').write_text(('WEBVTT\n\n'+''.join(f"{timestamp(c['start'])} --> {timestamp(c['end'])}\n{c['text']}\n\n" for c in allcues)).rstrip()+'\n')
    result={'src':f'media/aps62/v2/{sid}.mp4','poster':f'media/aps62/v2/{sid}.jpg','captions':f'media/aps62/v2/{sid}.vtt','duration_seconds':duration(destination),'transcript':'\n\n'.join(label+' : '+body for label,body in chunks),'voice':SETTINGS['voice'],'rate':SETTINGS['rate'],'burned_captions':True,'render_revision':2}
    (folder/'result.json').write_text(json.dumps(result,ensure_ascii=False))
    print(sid,round(result['duration_seconds'],1),'seconds',destination.stat().st_size,flush=True)
    return result

async def main():
    assert SETTINGS['voice']=='fr-FR-HenriNeural' and SETTINGS['rate']=='-2%'
    source=Path(os.environ['APS62_IMAGES']); files=list(source.glob('*.png'))
    for i,prefix in enumerate(NAMES,1):
        image=next(p for p in files if p.name.startswith(prefix))
        target=ASSETS/f'module-{i:02}.webp'
        if not target.exists() or target.stat().st_size < 1000:
            Image.open(image).convert('RGB').save(target,format='WEBP',quality=88)
    # A web cover with the same artwork as the first dossier.
    Image.open(ASSETS/'module-01.webp').save(ROOT/'static/images/aps62-cover.webp',quality=87)
    pool=concurrent.futures.ThreadPoolExecutor(max_workers=3)
    speech_slots=asyncio.Semaphore(6); video_slots=asyncio.Semaphore(3)
    manifest={}; rows=records()
    async def one(code,n,row):
        sid=f'aps62-{code}-{n:02d}'; folder=WORK/sid; folder.mkdir(exist_ok=True)
        async with video_slots:
            cached=json.loads((folder/'result.json').read_text()) if (folder/'result.json').exists() else {}
            if cached.get('render_revision')==2 and (ASSETS/f'{sid}.mp4').exists(): result=cached
            else:
                chunks=[('La situation',row['case']),('À vous de décider',row['good']+' Ou bien : '+row['bad']+' Mettez la vidéo en pause pour justifier votre choix.'),('Le raisonnement',row['reason']),('Le bon relais',row['model'])]
                voices=await asyncio.gather(*(speech((row['title']+'. ' if i==0 else '')+label+'. '+body,folder,i,speech_slots) for i,(label,body) in enumerate(chunks)))
                result=await asyncio.get_running_loop().run_in_executor(pool,render,code,n,row,chunks,voices,ASSETS/f'module-{code}.webp')
            manifest[sid]=result
            (OUT/'video_manifest_v2.json').write_text(json.dumps(dict(sorted(manifest.items())),ensure_ascii=False,indent=2)+'\n')
    await asyncio.gather(*(one(code,n,row) for code,*_ in MODULES for n,row in enumerate(rows[code],1)))
    print('DONE',len(manifest),'Henri capsules',round(sum(v['duration_seconds'] for v in manifest.values())/60,1),'minutes',flush=True)

if __name__=='__main__': asyncio.run(main())
