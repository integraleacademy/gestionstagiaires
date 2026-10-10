"""Correct module E pronunciation without changing learner video checkpoints.

Only authored course text is sent to the existing speech provider. English spans
are explicitly identified, including grammar terms outside quotation marks.
Historical course JSON and v4 media are never overwritten. Requires edge-tts,
PyAV, imageio-ffmpeg and the existing visual renderer's dependencies.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import wave

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.aps62_v5.captions import canonical, make_cues

OUT = ROOT / 'elearning_native/vtc'
WORK = Path(os.environ.get('VTC_BILINGUAL_WORK', '/tmp/vtc-bilingual-v7'))
VOICES = {'fr': 'fr-FR-HenriNeural', 'en': 'en-GB-RyanNeural'}
RATES = {'fr': '-2%', 'en': '-6%'}
# Indexed by scene, in addition to all quotations and concept-scene headings.
EXTRA_ENGLISH = {
    1: ['be', 'I am, you are, he is, she is, we are, they are'],
    2: ['who', 'where', 'when', 'what', 'how many'],
    3: ['do', 'does'],
    4: ['morning/evening', 'a.m./p.m.', 'at', 'on'],
    6: ['in', 'at', 'next to', 'opposite', 'between'],
    7: ['please'],
    11: ['would you like', 'be'],
    13: ['faster', 'shorter', 'more comfortable', 'than'],
    17: ['will', 'I’ll'],
}


def segments(text, index):
    """Return a lossless language partition, never infer language from letters."""
    spans = [(m.start(), m.end()) for m in re.finditer('«[^»]+»', text)]
    if index % 2 == 0:
        spans.append((0, text.index('. ') + 1))
    for phrase in EXTRA_ENGLISH.get(index, []):
        matches = list(re.finditer(r'(?<!\w)' + re.escape(phrase) + r'(?!\w)', text))
        assert matches, (index, phrase)
        spans.extend((m.start(), m.end()) for m in matches)
    mask = [False] * len(text)
    for start, end in spans:
        mask[start:end] = [True] * (end-start)
    result = []
    start = 0
    for end in range(1, len(text)+1):
        if end == len(text) or mask[end] != mask[start]:
            result.append({'lang': 'en' if mask[start] else 'fr', 'text': text[start:end]})
            start = end
    assert ''.join(s['text'] for s in result) == text
    return result


def duration(path):
    import av
    with av.open(str(path)) as container:
        return container.duration / 1e6


def ffmpeg(args):
    import imageio_ffmpeg
    command = [imageio_ffmpeg.get_ffmpeg_exe(), '-nostdin', '-v', 'error', '-y', *map(str, args)]
    subprocess.run(command, check=True, capture_output=True)


async def synthesize(segment, slots, locks):
    import edge_tts
    # Slashes are separators, not a word to teach; removing = preserves captions.
    text = segment['text'].strip().replace('/', ', ').replace('=', ' ')
    if not canonical(text):
        return None
    lang = segment['lang']
    key = hashlib.sha256((VOICES[lang]+RATES[lang]+text).encode()).hexdigest()[:24]
    target = WORK / 'speech' / (key+'.mp3')
    timing = target.with_suffix('.json')
    async with locks.setdefault(key, asyncio.Lock()), slots:
        if not (target.exists() and timing.exists()):
            for attempt in range(4):
                try:
                    words = []
                    async def collect():
                        with target.with_suffix('.partial').open('wb') as stream:
                            async for chunk in edge_tts.Communicate(text, voice=VOICES[lang],
                                    rate=RATES[lang], boundary='WordBoundary').stream():
                                if chunk['type'] == 'audio':
                                    stream.write(chunk['data'])
                                elif chunk['type'] == 'WordBoundary':
                                    words.append(chunk)
                    await asyncio.wait_for(collect(), timeout=100)
                    assert words and canonical(text) == ''.join(canonical(w['text']) for w in words), (text, words)
                    target.with_suffix('.partial').replace(target)
                    timing.write_text(json.dumps(words, ensure_ascii=False))
                    break
                except Exception:
                    if attempt == 3:
                        raise
                    await asyncio.sleep(2 * (attempt+1))
    words = json.loads(timing.read_text())
    # Retain consonants around the provider's word boundaries, trim only the
    # empty lead/tail of individual synthesis requests before joining voices.
    start = max(0, words[0]['offset']/1e7-.09)
    end = min(duration(target), (words[-1]['offset']+words[-1]['duration'])/1e7+.14)
    return dict(segment, audio=target, words=words, trim_start=start, seconds=end-start)


def assemble_scene(index, text, pieces, seconds):
    pieces = [p for p in pieces if p]
    english = sum(p['seconds'] for p in pieces if p['lang']=='en')
    french = sum(p['seconds'] for p in pieces if p['lang']=='fr')
    # Never speed up English examples. A small FR-only tempo adjustment allows
    # the original scene checkpoints to survive; refuse an excessive speedup.
    available = seconds-.08
    french_tempo = max(1., french / (available-english)) if french else 1.
    assert available > english and french_tempo <= 1.12, (index, seconds, english, french, french_tempo)
    words, pcm, offset = [], [], 0.
    for number, piece in enumerate(pieces):
        tempo = french_tempo if piece['lang']=='fr' else 1.
        target = WORK / 'E' / f'{index:02}-{number:02}.wav'
        ffmpeg(['-i', piece['audio'], '-af',
            f"atrim=start={piece['trim_start']:.7f}:duration={piece['seconds']:.7f},asetpts=PTS-STARTPTS,atempo={tempo:.8f}",
            '-ar', '48000', '-ac', '1', '-c:a', 'pcm_s16le', target])
        with wave.open(str(target), 'rb') as audio:
            frames = audio.readframes(audio.getnframes())
        for word in piece['words']:
            words.append(dict(word,
                offset=round((offset+(word['offset']/1e7-piece['trim_start'])/tempo)*1e7),
                duration=round(word['duration']/tempo)))
        pcm.append(frames)
        offset += len(frames)/96000
    # Minor encoder/tempo rounding is handled in silence only, never truncating
    # a word. Add the remaining quiet time at the end of this exact scene.
    assert offset <= seconds+.025, (index, offset, seconds)
    raw = b''.join(pcm)
    samples = round(seconds*48000)
    assert (words[-1]['offset']+words[-1]['duration'])/1e7 < seconds
    raw = raw[:samples*2].ljust(samples*2, b'\0')
    target = WORK / 'E' / f'scene-{index:02}.wav'
    with wave.open(str(target), 'wb') as audio:
        audio.setparams((1,2,48000,0,'NONE','not compressed'))
        audio.writeframes(raw)
    cues = make_cues(text, words)
    return (target, cues), dict(scene=index, duration_seconds=seconds,
        english_seconds=round(english,3), french_seconds=round(french,3),
        french_tempo=round(french_tempo,5), english_tempo=1.,
        tail_silence_seconds=round(max(0,seconds-offset),3))


async def main():
    import certifi
    import edge_tts.communicate as communication
    from scripts.vtc import render_visual_videos as visual
    communication._SSL_CTX.load_verify_locations(cafile=certifi.where())
    (WORK/'speech').mkdir(parents=True, exist_ok=True)
    (WORK/'E').mkdir(exist_ok=True)
    row = json.loads((OUT/'video_scripts_v4.json').read_text())['E']
    # Expand the written shorthand for speech and captions so both third-person
    # singular forms are actually demonstrated; retain the original file.
    row['scenes'][1]['text'] = row['scenes'][1]['text'].replace('he/she is', 'he is, she is')
    # The native reading of times is longer than the previous mispronounced
    # reading. Shorten only the French linking prose, preserving every example
    # and teaching point instead of rushing the English or moving checkpoints.
    row['scenes'][4]['text'] = (
        'Numbers, dates and times. « Half past seven » : 7 h 30 ; '
        '« a quarter past seven » : 7 h 15 ; « a quarter to eight » : 7 h 45. '
        'Ou « seven thirty ». Précisez morning/evening ou a.m./p.m. '
        'Pour éviter l’ambiguïté, écrivez le mois en lettres : « 12 June ». '
        'Heure : at ; jour : on. Exemple : « at eight on Monday ».')
    row['transcript'] = '\n\n'.join(scene['text'] for scene in row['scenes'])
    old = json.loads((OUT/'video_manifest_v4.json').read_text())['E']
    partition = [segments(scene['text'], i) for i,scene in enumerate(row['scenes'])]
    (WORK/'segments.json').write_text(json.dumps(partition,ensure_ascii=False,indent=2))
    slots = asyncio.Semaphore(4)
    locks = {}
    async def one(i):
        result = await asyncio.gather(*(synthesize(s, slots, locks) for s in partition[i]))
        print('SPEECH', i+1, '/', len(partition), flush=True)
        return result
    spoken = await asyncio.gather(*(one(i) for i in range(len(partition))))
    voices, stats = [], []
    for i, (scene, pieces, chapter) in enumerate(zip(row['scenes'], spoken, old['chapters'])):
        seconds = chapter['end_seconds']-chapter['start_seconds']
        if i == len(spoken)-1:
            seconds = old['duration_seconds']-chapter['start_seconds']
        voice, stat = assemble_scene(i,scene['text'],pieces,seconds)
        voices.append(voice);stats.append(stat)
        print('SCENE', json.dumps(stat), flush=True)
    visual.WORK = WORK
    visual.ASSETS = OUT/'assets/media/vtc/v7'
    visual.ASSETS.mkdir(parents=True, exist_ok=True)
    visual.duration = duration
    visual.run = lambda args: ffmpeg(args[1:])
    signature = hashlib.sha256(json.dumps(partition,ensure_ascii=False,sort_keys=True).encode()+Path(__file__).read_bytes()).hexdigest()
    rendered = visual.render('E', row, voices, signature)
    assert abs(rendered['duration_seconds']-old['duration_seconds']) < .025, rendered['duration_seconds']
    assert all(abs(a['start_seconds']-b['start_seconds']) < .002 for a,b in zip(rendered['chapters'],old['chapters']))
    rendered.update(src='media/vtc/v7/lesson-e.mp4', captions='media/vtc/v7/lesson-e.vtt',
        poster=old['poster'], duration_seconds=old['duration_seconds'], chapters=old['chapters'],
        voice=VOICES, rate=RATES, render_revision=7, scene_audio=stats,
        source_video=old['src'], language_segments=partition)
    (OUT/'video_english_bilingual_v7.json').write_text(json.dumps(rendered,ensure_ascii=False,indent=2)+'\n')
    # Poster is shared with v4; the generated duplicate is intentionally unused.
    (visual.ASSETS/'lesson-e.jpg').unlink()


if __name__=='__main__':
    asyncio.run(main())
