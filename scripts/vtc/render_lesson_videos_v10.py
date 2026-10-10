"""Build one explanatory, word-synchronised video per authored VTC lesson.

Only authorised course narration reaches the speech provider. No learner data
are used. Speech and completed renders are content-addressed and resumable.
The original voice pitch/tempo is preserved; the course player applies 0.85x.
Pauses freeze a verified silent tail, never interrupt a spoken sentence.

Build dependencies: edge-tts, certifi, Pillow, PyAV, imageio-ffmpeg. No ffprobe.
"""
import argparse
import asyncio
import concurrent.futures
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import wave

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.aps62_v5.captions import canonical, make_cues, timestamp
from scripts.vtc.render_bilingual_english import duration, ffmpeg, VOICES, RATES
from scripts.vtc.render_paced_videos import ASS_HEADER

OUT = ROOT / 'elearning_native/vtc'
ASSETS = OUT / 'assets/media/vtc/v10'
WORK = Path(os.environ.get('VTC_LESSON_WORK', '/tmp/vtc-lessons-v10'))
AUTHORING = OUT / 'lesson_video_scripts_v10'
FONT = ROOT / 'scripts/academy_videos/assets/Manrope-600.ttf'
BOLD = FONT.with_name('Manrope-800.ttf')
PURPLE, INK = '#7045bd', '#281c3a'
SAMPLE_RATE, FPS = 48000, 20
TAIL_SILENCE = .85


def digest(value):
    return hashlib.sha256(value).hexdigest()


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def file_sha(path):
    return digest(path.read_bytes())


def atomic_json(path, value):
    temp = path.with_suffix('.partial.json')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')
    temp.replace(path)


def scene_text(scene):
    return ''.join(segment['text'] for segment in scene['segments'])


def validate_lesson(row):
    assert re.fullmatch(r'[A-H]\.\d{2}', row['ref']), row['ref']
    assert 1 <= int(row['ref'][2:]) <= 12
    assert row['title'] and row['objective']
    assert re.fullmatch(r'[0-9a-f]{64}', row['source_sha256'])
    image = (OUT/'assets'/row['image']).resolve()
    assert image.is_relative_to((OUT/'assets').resolve()) and image.is_file()
    assert 4 <= len(row['scenes']) <= 6, row['ref']
    for i, scene in enumerate(row['scenes']):
        assert scene['kind'] in ('concept', 'method') and scene['title'] and scene['label']
        assert 1 <= len(scene['points']) <= 3
        assert scene['segments'] and all(s['lang'] in VOICES and s['text'].strip() for s in scene['segments'])
        text = scene_text(scene)
        assert len(canonical(text)) >= 35, (row['ref'], i)
        cursor = 0
        for point in scene['points']:
            anchor = point['anchor_text']
            assert point['label'] and point['text'] and anchor
            assert text.count(anchor) == 1, (row['ref'], i, anchor)
            position = text.find(anchor, cursor)
            assert position >= cursor, (row['ref'], i, anchor)
            cursor = position+len(anchor)
        pause = scene.get('pause')
        if pause:
            assert pause['seconds'] in (4, 5) and pause['message'].strip()
        # Validate all raster/overlay text before spending time or TTS calls.
        background(row, scene, i)
        for point, box in zip(scene['points'], card_boxes(scene)):
            point_layout(point, box)
    return row


def wrap(text, size, width, bold=False):
    font = ImageFont.truetype(str(BOLD if bold else FONT), size)
    lines, current = [], ''
    for word in text.split():
        assert font.getlength(word) <= width, ('unbreakable text', word)
        trial = (current+' '+word).strip()
        if current and font.getlength(trial) > width:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    return lines


def fit(text, width, max_lines, sizes, bold=False):
    for size in sizes:
        lines = wrap(text, size, width, bold)
        if len(lines) <= max_lines:
            return size, lines
    raise ValueError('Visual text does not fit without truncation: '+text)


def raster_text(draw, text, xy, width, max_lines, sizes, color=INK, bold=False):
    size, lines = fit(text, width, max_lines, sizes, bold)
    font = ImageFont.truetype(str(BOLD if bold else FONT), size)
    x, y = xy
    for line in lines:
        draw.text((x, y), line, font=font, fill=color)
        y += size*1.3
    return y


def card_boxes(scene):
    count = len(scene['points'])
    if scene['kind'] == 'concept':
        gap = 12
        height = (330-gap*(count-1))/count
        return [(432, 232+i*(height+gap), 800, height) for i in range(count)]
    gap = 18
    width = (1184-gap*(count-1))/count
    return [(48+i*(width+gap), 232, width, 330) for i in range(count)]


def point_layout(point, box):
    x, y, width, height = box
    usable = width-48
    label_size, label_lines = fit(point['label'], usable, 2, (25, 24, 23, 22, 21, 20), True)
    label_height = len(label_lines)*label_size*1.28
    body_height = height-32-label_height
    for size in (27, 26, 25, 24, 23, 22, 21, 20):
        body_lines = wrap(point['text'], size, usable)
        if len(body_lines)*size*1.3 <= body_height:
            return dict(x=x+24, y=y+14, width=usable, label_size=label_size,
                        label_lines=label_lines, body_size=size, body_lines=body_lines,
                        body_y=y+14+label_height+3)
    raise ValueError('Card does not fit without truncation: '+point['text'])


def background(row, scene, index):
    im = Image.new('RGB', (1280,720), '#f8f5fd')
    d = ImageDraw.Draw(im)
    d.rectangle((0,0,1280,8), fill=PURPLE)
    raster_text(d, 'INTÉGRALE ACADEMY  /  CHAUFFEUR VTC', (48,26), 900, 1, (18,), PURPLE, True)
    raster_text(d, 'LEÇON '+row['ref'], (1060,26), 180, 1, (18,), PURPLE)
    raster_text(d, scene['label'].upper(), (48,78), 1184, 1, (18,17,16), PURPLE, True)
    raster_text(d, scene['title'], (48,111), 1184, 2, (37,36,35,34,33,32), bold=True)
    if scene['kind'] == 'concept':
        with Image.open(OUT/'assets'/row['image']) as source:
            picture = ImageOps.contain(source.convert('RGB'), (342,318))
        im.paste(picture, (48+(342-picture.width)//2, 238+(318-picture.height)//2))
        d = ImageDraw.Draw(im)
    for box in card_boxes(scene):
        x,y,w,h = box
        d.rounded_rectangle((x,y,x+w,y+h), 16, fill='#eee6f8')
    count = len(row['scenes'])
    for j in range(count):
        x = 48+j*1184/count
        d.rounded_rectangle((x,580,x+1184/count-6,585), 2, fill=PURPLE if j <= index else '#ddd1ed')
    d.rectangle((0,602,1280,720), fill='#1d1429')
    return im


async def synthesize(segment, slots, locks):
    import edge_tts
    text = segment['text'].strip()
    lang = segment['lang']
    key = digest(json_bytes(dict(voice=VOICES[lang], rate=RATES[lang], text=text)))
    target = WORK/'speech'/(key+'.mp3')
    timing = target.with_suffix('.json')
    async with locks.setdefault(key, asyncio.Lock()), slots:
        if not (target.is_file() and timing.is_file()):
            for attempt in range(5):
                try:
                    words = []
                    async def collect():
                        with target.with_suffix('.partial').open('wb') as audio:
                            async for chunk in edge_tts.Communicate(text, voice=VOICES[lang],
                                    rate=RATES[lang], boundary='WordBoundary').stream():
                                if chunk['type'] == 'audio':
                                    audio.write(chunk['data'])
                                elif chunk['type'] == 'WordBoundary':
                                    words.append(chunk)
                    await asyncio.wait_for(collect(), 100)
                    assert words and canonical(text) == ''.join(canonical(w['text']) for w in words), text
                    target.with_suffix('.partial').replace(target)
                    atomic_json(timing, words)
                    break
                except Exception:
                    if attempt == 4:
                        raise
                    await asyncio.sleep(2*(attempt+1))
        words = json.loads(timing.read_text())
        assert canonical(text) == ''.join(canonical(w['text']) for w in words)
    trim_start = max(0, words[0]['offset']/1e7-.10)
    end = min(duration(target), (words[-1]['offset']+words[-1]['duration'])/1e7+.18)
    return dict(segment, audio=target, words=words, trim_start=trim_start, seconds=end-trim_start)


def assemble_scene(scene, pieces, folder, index):
    pcm, words, offset = [], [], 0.
    for n, piece in enumerate(pieces):
        target = folder/f'piece-{index:02}-{n:02}.wav'
        ffmpeg(['-i', piece['audio'], '-af',
                f"atrim=start={piece['trim_start']:.7f}:duration={piece['seconds']:.7f},asetpts=PTS-STARTPTS",
                '-ar', str(SAMPLE_RATE), '-ac', '1', '-c:a', 'pcm_s16le', target])
        with wave.open(str(target), 'rb') as stream:
            raw = stream.readframes(stream.getnframes())
        for word in piece['words']:
            words.append(dict(word, offset=round((offset+word['offset']/1e7-piece['trim_start'])*1e7)))
        pcm.append(raw)
        offset += len(raw)/(SAMPLE_RATE*2)
        if n < len(pieces)-1:
            gap = round(.12*SAMPLE_RATE)*2
            pcm.append(b'\0'*gap)
            offset += gap/(SAMPLE_RATE*2)
    speech_end = (words[-1]['offset']+words[-1]['duration'])/1e7
    # Round upward to a frame boundary, adding time only to the silent tail.
    seconds = math.ceil((offset+TAIL_SILENCE)*FPS)/FPS
    raw = b''.join(pcm).ljust(round(seconds*SAMPLE_RATE)*2, b'\0')
    target = folder/f'scene-{index:02}.wav'
    with wave.open(str(target), 'wb') as stream:
        stream.setparams((1,2,SAMPLE_RATE,0,'NONE','not compressed'))
        stream.writeframes(raw)
    assert seconds-offset >= TAIL_SILENCE-.00001
    return dict(path=target, seconds=seconds, words=words, cues=make_cues(scene_text(scene), words),
                speech_end=speech_end, silence_start=offset, silence_end=seconds)


def anchored_reveals(scene, words, start):
    text = scene_text(scene)
    timeline = []
    for word in words:
        timeline.extend([word]*(len(canonical(word['text']))))
    assert len(timeline) == len(canonical(text))
    reveals, cursor = [], 0
    for point in scene['points']:
        needle = canonical(point['anchor_text'])
        pos = canonical(text).find(needle, cursor)
        assert pos >= cursor and needle
        word = timeline[pos]
        reveals.append(dict(anchor_text=point['anchor_text'],
                            at_seconds=round(start+word['offset']/1e7,3),
                            timing_method='original-synthesis-word',
                            word_text=word['text']))
        cursor = pos+len(needle)
    return reveals


def ass_text(lines):
    # ASS markup is renderer-owned; narration/cards are plain source text.
    return r'\N'.join(lines).replace('{','｛').replace('}','｝')


def render(row, spoken, signature):
    ref = row['ref']
    slug = ref.lower().replace('.', '-')
    folder = WORK/ref
    folder.mkdir(parents=True, exist_ok=True)
    audio = [assemble_scene(scene, pieces, folder, i)
             for i,(scene,pieces) in enumerate(zip(row['scenes'], spoken))]
    frames, events, cues, chapters, pauses, scene_data = [], [], [], [], [], []
    offset = 0.
    def event(start, end, value, style='Visual', layer=1):
        assert 0 <= start < end
        events.append(f'Dialogue: {layer},{timestamp(start)[:-1]},{timestamp(end)[:-1]},'
                      f'{style},,0,0,0,,{value}\n')
    for i,(scene, voice) in enumerate(zip(row['scenes'], audio)):
        end = offset+voice['seconds']
        picture = background(row, scene, i)
        path = folder/f'scene-{i:02}.png'
        picture.save(path)
        frames.extend([f"file '{path}'", f"duration {voice['seconds']:.6f}"])
        reveal = anchored_reveals(scene, voice['words'], offset)
        for point, timing, box in zip(scene['points'], reveal, card_boxes(scene)):
            layout = point_layout(point, box)
            x,y = layout['x'], layout['y']
            value = (r'{\an7\pos('+f'{x:.1f},{y:.1f}'+r')\fad(100,0)\fs'+str(layout['label_size'])
                     +r'\b1\c&HBD4570&}'+ass_text(layout['label_lines']))
            event(timing['at_seconds'], end, value)
            value = (r'{\an7\pos('+f"{x:.1f},{layout['body_y']:.1f}"+r')\fad(100,0)\fs'+str(layout['body_size'])
                     +r'\b0\c&H3A1C28&}'+ass_text(layout['body_lines']))
            event(timing['at_seconds'], end, value)
        for cue in voice['cues']:
            cue = dict(cue, start=round(cue['start']+offset,3), end=round(min(cue['end']+offset,end-.02),3))
            assert cue['start'] < cue['end']
            cues.append(cue)
            event(cue['start'], cue['end'], ass_text(cue['text'].splitlines()), 'Caption', 2)
        chapters.append(dict(ref=f'{ref}-{i+1:02}', title=scene['title'], kind=scene['kind'],
                             start_seconds=round(offset,3), end_seconds=round(end,3)))
        silence_start, silence_end = offset+voice['silence_start'], end
        pause = scene.get('pause')
        if pause:
            pauses.append(dict(id=f'vtc-{slug}-pause-{i+1}', at_seconds=round(silence_start+.2,3),
                               duration_seconds=pause['seconds'], message=pause['message'],
                               kind=pause.get('kind', 'repeat' if pause['seconds']==5 else 'reflect')))
        scene_data.append(dict(index=i, title=scene['title'], language_segments=scene['segments'],
                               start_seconds=round(offset,3), end_seconds=round(end,3),
                               speech_end_seconds=round(offset+voice['speech_end'],3),
                               verified_silence=dict(start=round(silence_start,3),end=round(silence_end,3)),
                               reveals=reveal))
        if i == 0:
            poster = picture.copy()
            d = ImageDraw.Draw(poster)
            for point,box in zip(scene['points'],card_boxes(scene)):
                layout = point_layout(point,box)
                raster_text(d, point['label'],(layout['x'],layout['y']),layout['width'],2,
                            (layout['label_size'],),PURPLE,True)
                raster_text(d, point['text'],(layout['x'],layout['body_y']),layout['width'],20,
                            (layout['body_size'],))
            poster.save(ASSETS/f'lesson-{slug}.jpg',quality=88)
        offset = end
    frames.append(f"file '{path}'")
    (folder/'frames.txt').write_text('\n'.join(frames)+'\n')
    (folder/'audio.txt').write_text(''.join(f"file '{a['path']}'\n" for a in audio))
    ass = folder/'lesson.ass'
    ass.write_text(ASS_HEADER+''.join(events))
    merged = folder/'narration.wav'
    ffmpeg(['-f','concat','-safe','0','-i',folder/'audio.txt','-c:a','pcm_s16le',merged])
    target = ASSETS/f'lesson-{slug}.mp4'
    temporary = folder/'complete.mp4'
    ffmpeg(['-f','concat','-safe','0','-i',folder/'frames.txt','-i',merged,'-t',f'{offset:.6f}',
            '-vf',f'fps={FPS},ass={ass}:fontsdir={FONT.parent},format=yuv420p',
            '-c:v','libx264','-preset','veryfast','-crf','27','-threads','2',
            '-c:a','aac','-b:a','80k','-ar',str(SAMPLE_RATE),'-movflags','+faststart',temporary])
    actual = duration(temporary)
    assert abs(actual-offset) < .08, (ref, actual, offset)
    temporary.replace(target)
    vtt_path = ASSETS/f'lesson-{slug}.vtt'
    vtt_path.write_text('WEBVTT\n\n'+''.join(f"{timestamp(c['start'])} --> {timestamp(c['end'])}\n{c['text']}\n\n" for c in cues))
    result = dict(src=f'media/vtc/v10/lesson-{slug}.mp4', poster=f'media/vtc/v10/lesson-{slug}.jpg',
                  captions=f'media/vtc/v10/lesson-{slug}.vtt',duration_seconds=actual,narration_seconds=round(offset,3),
                  transcript='\n\n'.join(scene_text(scene) for scene in row['scenes']),
                  title=row['title'], lesson_ref=ref, objective=row['objective'], voice=VOICES, rate=RATES,
                  audio=True,burned_captions=True,course_only=True,animated=True,chapters=chapters,
                  content_sha256=signature,source_sha256=row['source_sha256'],render_revision=10,
                  source_code_sha256=code_signature(),default_playback_rate=.85,allowed_playback_rates=[.85,1],
                  learning_pauses=pauses,scenes=scene_data,
                  media_sha256=file_sha(target),poster_sha256=file_sha(ASSETS/f'lesson-{slug}.jpg'),
                  captions_sha256=file_sha(vtt_path))
    atomic_json(folder/'result.json', result)
    print('READY',ref,round(actual,2),'seconds',target.stat().st_size,'bytes',flush=True)
    return result


def code_signature():
    dependencies = [Path(__file__), ROOT/'scripts/aps62_v5/captions.py',
                    ROOT/'scripts/vtc/render_bilingual_english.py',
                    ROOT/'scripts/vtc/render_paced_videos.py', FONT, BOLD]
    return digest(b''.join(path.read_bytes() for path in dependencies))


def signature_for(row):
    return digest(json_bytes(row)+code_signature().encode()+file_sha(OUT/'assets'/row['image']).encode())


def cached_result(row, signature):
    path = WORK/row['ref']/'result.json'
    if not path.is_file():
        return None
    result = json.loads(path.read_text())
    if result.get('content_sha256') != signature:
        return None
    for key, digest_key in [('src','media_sha256'),('poster','poster_sha256'),('captions','captions_sha256')]:
        file = OUT/'assets'/result[key]
        if not file.is_file() or file_sha(file) != result[digest_key]:
            return None
    return result


def read_lessons(path):
    if path.is_dir():
        rows = [row for file in sorted(path.glob('[A-H].json')) for row in read_lessons(file)]
        assert len({row['ref'] for row in rows}) == len(rows)
        return rows
    data = json.loads(path.read_text())
    rows = data.get('lessons', data)
    if isinstance(rows, dict):
        rows = list(rows.values())
    assert len({row['ref'] for row in rows}) == len(rows)
    return rows


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scripts',type=Path,default=AUTHORING)
    parser.add_argument('--only',help='Comma separated refs or module letters')
    parser.add_argument('--plan-only',action='store_true')
    parser.add_argument('--speech-only',action='store_true')
    args = parser.parse_args()
    rows = read_lessons(args.scripts)
    if args.only:
        selected = set(args.only.split(','))
        rows = [row for row in rows if row['ref'] in selected or row['ref'][0] in selected]
    assert rows, 'No lessons selected'
    for row in rows:
        validate_lesson(row)
    print('VALIDATED',len(rows),'lessons',sum(len(r['scenes']) for r in rows),'scenes',flush=True)
    if args.plan_only:
        return
    import certifi
    import edge_tts.communicate as communication
    communication._SSL_CTX.load_verify_locations(cafile=certifi.where())
    ASSETS.mkdir(parents=True,exist_ok=True)
    (WORK/'speech').mkdir(parents=True,exist_ok=True)
    manifest_path = OUT/'lesson_videos_v10.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else dict(revision=10,lessons={})
    speech_slots,render_slots = asyncio.Semaphore(4),asyncio.Semaphore(2)
    locks = {}
    loop = asyncio.get_running_loop()
    failures = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        async def one(row):
            try:
                signature = signature_for(row)
                result = cached_result(row,signature)
                if result:
                    print('CACHED',row['ref'],flush=True)
                else:
                    spoken = await asyncio.gather(*(asyncio.gather(*(synthesize(s,speech_slots,locks)
                              for s in scene['segments'])) for scene in row['scenes']))
                    print('SPEECH',row['ref'],flush=True)
                    if args.speech_only:
                        return
                    async with render_slots:
                        result = await loop.run_in_executor(pool,render,row,spoken,signature)
                manifest['lessons'][row['ref']] = result
                manifest['lessons'] = dict(sorted(manifest['lessons'].items()))
                atomic_json(manifest_path,manifest)
            except Exception as exc:
                failures.append((row['ref'],str(exc)))
                print('FAILED',row['ref'],repr(exc),flush=True)
        await asyncio.gather(*(one(row) for row in rows))
    if failures:
        raise RuntimeError(f'{len(failures)} lesson(s) failed: {failures}')
    print('COMPLETE',len(rows),'lessons',flush=True)


if __name__ == '__main__':
    asyncio.run(main())
