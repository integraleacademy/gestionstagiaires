"""Remove the Ms/Miss ambiguity from E-01-2 without overwriting v3 media."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.vtc.render_bilingual_english import duration, ffmpeg

OUT = ROOT / 'elearning_native/vtc'
WORK = Path(os.environ.get('VTC_GREEN_WORK', str(ROOT.parent/'vtc-green-dialogue-v8')))
RATE = '-6%'


async def main():
    import certifi
    import edge_tts
    import edge_tts.communicate as communication
    communication._SSL_CTX.load_verify_locations(cafile=certifi.where())
    WORK.mkdir(parents=True, exist_ok=True)
    source = next(d for d in json.loads((OUT/'dialogues_v3.json').read_text()) if d['id']=='e-01-2')
    turns = [dict(t) for t in source['turns']]
    assert turns[0]['text'].endswith('Are you Ms Green?')
    assert turns[1]['text'].startswith('Yes, I am.')
    turns[0]['text'] = 'Good evening. My name is Alex. I am your driver. Is your booking under the name Green?'
    turns[1]['text'] = turns[1]['text'].replace('Yes, I am.', 'Yes, it is.', 1)
    slots = asyncio.Semaphore(3)

    async def synthesize(turn):
        assert turn['voice'] in {'en-GB-RyanNeural', 'en-GB-SoniaNeural'}
        key = hashlib.sha256((turn['voice']+RATE+turn['text']).encode()).hexdigest()
        audio = WORK/(key+'.mp3')
        async with slots:
            if not audio.exists():
                for attempt in range(3):
                    try:
                        partial = audio.with_suffix('.partial.mp3')
                        await asyncio.wait_for(edge_tts.Communicate(turn['text'], voice=turn['voice'], rate=RATE).save(str(partial)), timeout=100)
                        assert duration(partial)>1
                        partial.replace(audio)
                        break
                    except Exception:
                        if attempt == 2:
                            raise
                        await asyncio.sleep(2*(attempt+1))
        return audio

    parts = await asyncio.gather(*(synthesize(turn) for turn in turns))
    listing = WORK/'parts.txt'
    listing.write_text(''.join(f"file '{p}'\n" for p in parts))
    target = OUT/'assets/media/vtc/v8/audio/e-01-2.mp3'
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = WORK/'dialogue.mp3'
    ffmpeg(['-f','concat','-safe','0','-i',listing,'-c:a','libmp3lame','-b:a','64k','-ar','24000',temporary])
    seconds = duration(temporary)
    assert 35 < seconds < 55
    temporary.replace(target)
    entry = {
        'original_src': 'media/vtc/v3/audio/e-01-2.mp3',
        'src': 'media/vtc/v8/audio/e-01-2.mp3',
        'duration_seconds': seconds,
        'original_turns': [{k:t[k] for k in ('speaker','text')} for t in source['turns']],
        'turns': turns,
        'translation': 'Alex accueille la cliente le soir et confirme que sa réservation est au nom de Green, pour Riverside Hotel. La cliente a 3 bagages et demande de l’aide avec le plus grand. Les documents et médicaments restent avec elle.',
        'voices': ['en-GB-RyanNeural','en-GB-SoniaNeural'],
        'rate': RATE,
        'sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
    }
    (OUT/'listening_corrections_v8.json').write_text(json.dumps({'revision':8,'dialogues':{'e-01-2':entry}}, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'src':entry['src'],'duration_seconds':seconds,'bytes':target.stat().st_size,'sha256':entry['sha256']}), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
