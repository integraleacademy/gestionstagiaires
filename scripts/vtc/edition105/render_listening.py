"""Render only original fictional English dialogue text, never learner data.

Microsoft Edge TTS receives each generated dialogue line. Mixing and timing
remain local. No PDF, learner information, reservation record or credential is
read by this script. Existing approved Henri capsules are not modified.
"""
import asyncio, hashlib, json, subprocess
from pathlib import Path
import edge_tts
import edge_tts.communicate as communication
from .english import build
ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'elearning_native/vtc'
MEDIA=OUT/'assets/media/vtc/v3/audio'
WORK=ROOT.parent/'vtc105-audio-work'
communication._SSL_CTX.load_verify_locations(cafile='/etc/ssl/certs/ca-certificates.crt')
RATE='-6%'

def duration(p):
    return float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',str(p)]))

async def main():
    _,_,dialogues=build();MEDIA.mkdir(parents=True,exist_ok=True);WORK.mkdir(exist_ok=True)
    (OUT/'dialogues_v3.json').write_text(json.dumps(dialogues,ensure_ascii=False,indent=2)+'\n')
    unique={(t['voice'],t['text']) for d in dialogues for t in d['turns']};semaphore=asyncio.Semaphore(4)
    assert all(voice in {'en-GB-SoniaNeural','en-GB-RyanNeural'} and 10<len(text)<800 for voice,text in unique)
    def target(voice,text):return WORK/(hashlib.sha256((voice+RATE+text).encode()).hexdigest()+'.mp3')
    async def voice(item):
        speaker,text=item;p=target(speaker,text)
        if p.exists() and p.stat().st_size>500:return
        async with semaphore:
            for attempt in range(3):
                try:
                    await asyncio.wait_for(edge_tts.Communicate(text,voice=speaker,rate=RATE).save(str(p.with_suffix('.partial.mp3'))),timeout=50)
                    assert p.with_suffix('.partial.mp3').stat().st_size>500
                    p.with_suffix('.partial.mp3').replace(p)
                    print('VOICE',speaker,len(text),flush=True);return
                except Exception:
                    if attempt==2:raise
                    await asyncio.sleep(1+attempt)
    print('GENERATED TEXT ONLY:',len(dialogues),'fictional dialogues;',len(unique),'unique lines',flush=True)
    await asyncio.gather(*(voice(item) for item in unique))
    manifest={}
    for d in dialogues:
        parts=[target(t['voice'],t['text']) for t in d['turns']]
        listing=WORK/(d['id']+'.txt');listing.write_text(''.join(f"file '{p}'\n" for p in parts))
        output=MEDIA/(d['id']+'.mp3');temp=output.with_suffix('.partial.mp3')
        subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-f','concat','-safe','0','-i',str(listing),'-c:a','libmp3lame','-b:a','64k','-ar','24000',str(temp)],check=True)
        assert duration(temp)>5;temp.replace(output)
        manifest[d['id']]={'src':'media/vtc/v3/audio/'+output.name,'duration_seconds':duration(output),'voices':['en-GB-RyanNeural','en-GB-SoniaNeural'],'rate':RATE}
        print('READY',d['id'],round(manifest[d['id']]['duration_seconds'],1),'s',flush=True)
    (OUT/'listening_manifest_v3.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print('COMPLETE',len(manifest),'dialogues',sum(x['duration_seconds'] for x in manifest.values())/60,'minutes',flush=True)

if __name__=='__main__':asyncio.run(main())
