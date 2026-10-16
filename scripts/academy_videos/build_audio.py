"""Narration using the exact voice and timing of the approved reference.
Only the authored, published narration is sent to the original speech service.
Never substitute another voice when synthesis fails. Cache each completed take.
"""
from pathlib import Path
import asyncio, hashlib, json, os, subprocess, sys, wave
import edge_tts
import edge_tts.communicate as communicate_module
import numpy as np
ROOT=Path(__file__).resolve().parent
WORK=Path(os.environ['ACADEMY_WORK'])
SETTINGS=json.loads((ROOT/'reference_settings.json').read_text())
RATE=SETTINGS['sample_rate']
if Path('/etc/ssl/certs/ca-certificates.crt').exists():
    communicate_module._SSL_CTX.load_verify_locations(cafile='/etc/ssl/certs/ca-certificates.crt')

async def prepare_takes(videos):
    semaphore=asyncio.Semaphore(4)
    async def one(video,si,li,words):
        folder=WORK/video['id'];folder.mkdir(parents=True,exist_ok=True)
        take_hash=hashlib.sha256((SETTINGS['voice']+SETTINGS['rate']+words).encode()).hexdigest()[:16]
        mp3=folder/f'voice_{si:02}_{li:02}_{take_hash}.mp3'
        if mp3.exists() and mp3.stat().st_size>=1000:return
        async with semaphore:
            temporary=mp3.with_suffix('.partial.mp3')
            speech=edge_tts.Communicate(words,voice=SETTINGS['voice'],rate=SETTINGS['rate'],pitch=SETTINGS['pitch'],volume=SETTINGS['volume'])
            await asyncio.wait_for(speech.save(str(temporary)),timeout=50)
            temporary.replace(mp3)
            print(video['id'],f'take {si}:{li} cached',flush=True)
    # Finish each capsule before proceeding, while independent takes run together.
    for video in videos:
        await asyncio.gather(*(one(video,si,li,words) for si,s in enumerate(video['scenes']) for li,words in enumerate(s['lines'])))
        await build(video)

async def build(video):
    assert video['voice']==SETTINGS['voice']=='fr-FR-HenriNeural'
    folder=WORK/video['id'];folder.mkdir(parents=True,exist_ok=True)
    signature=hashlib.sha256(json.dumps([video,SETTINGS],sort_keys=True).encode()).hexdigest()
    if (folder/'timeline.json').exists() and (folder/'narration.wav').exists():
        if json.loads((folder/'timeline.json').read_text()).get('source_sha256')==signature:
            print(video['id'],'reference audio cached',flush=True);return
    parts,scenes=[],[];cursor=0.0
    def silence(seconds):
        nonlocal cursor
        samples=np.zeros(round(seconds*RATE),dtype=np.float32)
        parts.append(samples);cursor+=len(samples)/RATE
    for si,scene in enumerate(video['scenes']):
        start,cues=cursor,[]
        silence(SETTINGS['scene_head'] if si else SETTINGS['first_scene_head'])
        for li,words in enumerate(scene['lines']):
            take_hash=hashlib.sha256((SETTINGS['voice']+SETTINGS['rate']+words).encode()).hexdigest()[:16]
            mp3=folder/f'voice_{si:02}_{li:02}_{take_hash}.mp3'
            if not mp3.exists() or mp3.stat().st_size<1000:
                temporary=mp3.with_suffix('.partial.mp3')
                speech=edge_tts.Communicate(words,voice=SETTINGS['voice'],rate=SETTINGS['rate'],pitch=SETTINGS['pitch'],volume=SETTINGS['volume'])
                await asyncio.wait_for(speech.save(str(temporary)),timeout=50)
                temporary.replace(mp3)
            decoded=subprocess.check_output(['ffmpeg','-nostdin','-v','error','-threads','1','-i',str(mp3),'-ar',str(RATE),'-ac','1','-f','s16le','pipe:1'])
            samples=np.frombuffer(decoded,dtype='<i2').astype(np.float32)/32768
            voiced=np.flatnonzero(abs(samples)>.007)
            if not len(voiced):raise ValueError(f'Empty narration: {video["id"]}:{si}:{li}')
            samples=samples[max(0,voiced[0]-round(.09*RATE)):min(len(samples),voiced[-1]+round(.16*RATE))]
            ramp=min(250,len(samples)//4)
            samples[:ramp]*=np.linspace(0,1,ramp);samples[-ramp:]*=np.linspace(1,0,ramp)
            end=cursor+len(samples)/RATE
            cues.append(dict(start=cursor,end=end,text=words));parts.append(samples);cursor=end
            silence(SETTINGS['line_pause'])
            print(video['id'],f'voice {si}:{li}',round(len(samples)/RATE,2),'s',flush=True)
        if scene.get('pause'):
            cues.append(dict(start=cursor,end=cursor+scene['pause'],text='',pause=True));silence(scene['pause'])
        silence(SETTINGS['scene_tail'])
        scenes.append(dict(**scene,start=start,end=cursor,cues=cues))
    temporary=folder/'narration.partial.wav';data=np.concatenate(parts)
    with wave.open(str(temporary),'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(RATE)
        wav.writeframes((np.clip(data,-1,1)*32767).astype('<i2').tobytes())
    temporary.replace(folder/'narration.wav')
    timeline=dict(id=video['id'],voice=SETTINGS['voice'],rate=SETTINGS['rate'],reference_style=video['reference_style'],source_sha256=signature,duration=cursor,scenes=scenes)
    (folder/'timeline.json').write_text(json.dumps(timeline,ensure_ascii=False,indent=2)+'\n')
    print(video['id'],f'{cursor:.2f}s REFERENCE AUDIO READY',flush=True)

async def main():
    # This full source was verified public through GitHub on 2026-09-25:
    # integraleacademy/gestionstagiaires, commit 806432ea1af278eb493c2c2b2f6ada71f70f0fe0.
    # Refuse any outgoing narration that is not present in that published blob.
    published=(ROOT/'reference_public_texts.json').read_bytes()
    blob_hash=hashlib.sha1(b'blob '+str(len(published)).encode()+b'\0'+published).hexdigest()
    assert blob_hash=='0379e5f0d46df6be01062de152476eabfb79a263'
    source={(v['module'],v['sequence']):v for v in json.loads(published)}
    videos=json.loads((ROOT/'series.json').read_text())
    for video in videos:
        reference=source[(video['module'],video['sequence'])]
        for i,scene in enumerate(video['scenes']):
            for phrase in scene['lines']:
                assert any(phrase in line for line in reference['scenes'][i]['lines']), 'Unverified narration'
    selected=[v for v in videos if len(sys.argv)==1 or v['id'] in sys.argv[1:]]
    await prepare_takes(selected)
if __name__=='__main__':asyncio.run(main())
