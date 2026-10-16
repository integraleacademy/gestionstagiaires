"""Narrate only the eight VTC scripts explicitly approved by the user.

Usage: python scripts/vtc/render_narrated_videos.py --approved-texts /path/to/approved.txt
Only the checked script text reaches Microsoft Edge's speech service. Artwork
stays local. The original silent media and courses are preserved unchanged.
"""
import argparse, asyncio, concurrent.futures, hashlib, json, subprocess, textwrap
from pathlib import Path
import edge_tts
import edge_tts.communicate as communication
from render_videos import frame

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'elearning_native/vtc'
MEDIA=OUT/'assets/media/vtc/v2'
WORK=ROOT.parent/'vtc-voice-work'
VOICE='fr-FR-HenriNeural'
RATE='-2%'
communication._SSL_CTX.load_verify_locations(cafile='/etc/ssl/certs/ca-certificates.crt')

def run(args):
    result=subprocess.run(args,capture_output=True)
    if result.returncode:raise RuntimeError(result.stderr.decode(errors='replace'))

def duration(path):
    return float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',str(path)]))

def timestamp(seconds,separator='.'):
    ms=round(seconds*1000)
    return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02}{separator}{ms%1000:03}'

def make_cues(words):
    groups=[];current=[]
    for word in words:
        if current and (len(' '.join(w['text'] for w in current))+len(word['text'])>88 or len(current)>=14):
            groups.append(current);current=[]
        current.append(word)
    if current:groups.append(current)
    return [{'start':c[0]['offset']/1e7,'end':(c[-1]['offset']+c[-1]['duration'])/1e7,'text':' '.join(w['text'] for w in c)} for c in groups]

async def speech(spoken,folder,slots,approved_parts):
    assert spoken in approved_parts, 'Narration not in the explicitly approved scripts'
    signature=hashlib.sha256((VOICE+RATE+spoken).encode()).hexdigest()[:20]
    audio=folder/(signature+'.mp3');timing=audio.with_suffix('.json')
    if audio.exists() and audio.stat().st_size>1000 and timing.exists():return audio,json.loads(timing.read_text())
    async with slots:
        for attempt in range(3):
            try:
                words=[]
                async def collect():
                    with audio.with_suffix('.partial').open('wb') as output:
                        async for chunk in edge_tts.Communicate(spoken,voice=VOICE,rate=RATE,pitch='+0Hz',volume='+0%',boundary='WordBoundary').stream():
                            if chunk['type']=='audio':output.write(chunk['data'])
                            elif chunk['type']=='WordBoundary':words.append(chunk)
                await asyncio.wait_for(collect(),timeout=55)
                if not words:raise ValueError('Missing word timestamps')
                audio.with_suffix('.partial').replace(audio)
                cues=make_cues(words);timing.write_text(json.dumps(cues,ensure_ascii=False))
                return audio,cues
            except Exception:
                if attempt==2:raise
                await asyncio.sleep(2*(attempt+1))

def render(module,chunks,voices):
    letter=module['letter'];folder=WORK/letter;parts=[];allcues=[];offset=0
    for i,q in enumerate(chunks):
        for phase in range(2):
            audio,cues=voices[i*2+phase]
            seconds=duration(audio)+(1.2 if phase==0 else .5)
            stem=f'{i}-{phase}'
            picture=frame(module,i,q,'',phase==1);picture.save(folder/(stem+'.png'))
            if i==0 and phase==0:picture.save(MEDIA/f'capsule-{letter.lower()}.jpg',quality=88)
            srt=''.join(f"{n+1}\n{timestamp(c['start'],',')} --> {timestamp(c['end'],',')}\n{textwrap.fill(c['text'],width=66)}\n\n" for n,c in enumerate(cues))
            (folder/(stem+'.srt')).write_text(srt)
            part=folder/(stem+'.mp4');temporary=folder/(stem+'.partial.mp4');parts.append(part)
            vf=f"subtitles={folder}/{stem}.srt:force_style='FontName=DejaVu Sans,FontSize=11,PrimaryColour=&H00FFFFFF,Outline=0,Shadow=0,MarginV=17,Alignment=2',format=yuv420p"
            run(['ffmpeg','-nostdin','-v','error','-y','-loop','1','-framerate','12','-i',str(folder/(stem+'.png')),'-i',str(audio),'-t',str(seconds),'-vf',vf,'-c:v','libx264','-preset','veryfast','-crf','27','-tune','stillimage','-threads','2','-c:a','aac','-b:a','96k','-ar','48000','-af','apad','-movflags','+faststart',str(temporary)])
            assert abs(duration(temporary)-seconds)<.2
            temporary.replace(part)
            allcues.extend(dict(c,start=c['start']+offset,end=c['end']+offset) for c in cues)
            offset+=duration(part)
    (folder/'concat.txt').write_text(''.join(f"file '{p}'\n" for p in parts))
    target=MEDIA/f'capsule-{letter.lower()}.mp4';temporary=target.with_suffix('.partial.mp4')
    run(['ffmpeg','-nostdin','-v','error','-xerror','-y','-f','concat','-safe','0','-i',str(folder/'concat.txt'),'-c:v','copy','-c:a','aac','-b:a','96k','-af','aresample=async=1:first_pts=0','-movflags','+faststart',str(temporary)])
    assert abs(duration(temporary)-offset)<.3
    assert duration(temporary)>allcues[-1]['end']
    temporary.replace(target)
    (MEDIA/f'capsule-{letter.lower()}.vtt').write_text(('WEBVTT\n\n'+''.join(f"{timestamp(c['start'])} --> {timestamp(c['end'])}\n{c['text']}\n\n" for c in allcues)).rstrip()+'\n')
    result={'src':f'media/vtc/v2/capsule-{letter.lower()}.mp4','poster':f'media/vtc/v2/capsule-{letter.lower()}.jpg','captions':f'media/vtc/v2/capsule-{letter.lower()}.vtt','duration_seconds':duration(target),'transcript':'\n\n'.join(q['spoken'] for q in chunks),'voice':VOICE,'rate':RATE,'audio':True,'burned_captions':True}
    (folder/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print('READY',letter,round(result['duration_seconds'],1),'seconds, Henri + captions',flush=True)
    return result

async def main(approved_file):
    approved=Path(approved_file).read_text()
    original=json.loads((OUT/'video_manifest.json').read_text())
    bank=json.loads((OUT/'manual_bank.json').read_text())
    questions=[]
    for row in (ROOT/'scripts/vtc/questions.txt').read_text().splitlines():
        if not row or row.startswith('#'):continue
        ref,prompt,answer,_,_,reason=row.split('|')
        questions.append({'ref':ref,'prompt':prompt,'answer_text':answer,'reason':reason,'spoken':prompt+' '+answer+'. '+reason})
    module_chunks={};approved_parts=set()
    for m in bank['modules']:
        letter=m['letter'];chunks=[next(q for q in questions if q['ref']==letter+f'.{n:02}') for n in [1,4,8,12]]
        transcript='\n\n'.join(q['spoken'] for q in chunks)
        assert transcript==original[letter]['transcript'] and transcript in approved, 'Script differs from the approved text'
        module_chunks[letter]=chunks
        for q in chunks:approved_parts.update([q['prompt'],q['answer_text']+'. '+q['reason']])
    print('VERIFIED: all 32 situations match the eight scripts approved by the user; text-only speech requests.',flush=True)
    MEDIA.mkdir(parents=True,exist_ok=True);WORK.mkdir(exist_ok=True)
    speech_slots=asyncio.Semaphore(4);video_slots=asyncio.Semaphore(2)
    pool=concurrent.futures.ThreadPoolExecutor(max_workers=2);manifest={}
    async def one(module):
        letter=module['letter'];folder=WORK/letter;folder.mkdir(exist_ok=True)
        chunks=module_chunks[letter]
        parts=[text for q in chunks for text in (q['prompt'],q['answer_text']+'. '+q['reason'])]
        voices=await asyncio.gather(*(speech(t,folder,speech_slots,approved_parts) for t in parts))
        print('VOICE',letter,'ready',flush=True)
        async with video_slots:
            result=await asyncio.get_running_loop().run_in_executor(pool,render,module,chunks,voices)
        manifest[letter]=result
    await asyncio.gather(*(one(m) for m in bank['modules']))
    (OUT/'video_manifest_v2.json').write_text(json.dumps(dict(sorted(manifest.items())),ensure_ascii=False,indent=2)+'\n')
    print('COMPLETE',len(manifest),'narrated capsules',flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--approved-texts',required=True)
    args=parser.parse_args();asyncio.run(main(args.approved_texts))
