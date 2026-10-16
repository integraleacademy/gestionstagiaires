"""Render immutable APS v5 course videos with Henri and punctuated captions.

Build-only dependencies: edge-tts, Pillow, ffmpeg. Resume-safe caches are keyed
by authored text and settings. APS62_ONLY can select a dossier for a preview.
"""
import asyncio
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import edge_tts
import edge_tts.communicate as communication
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.aps62_v5.content import courses
from scripts.aps62_v5.captions import make_cues, timestamp

OUT = ROOT / 'elearning_native/aps62'
ASSETS = OUT / 'assets/media/aps62/v5'
WORK = Path(os.environ.get('APS62_WORK', '/tmp/aps62-v5'))
SETTINGS = json.loads((ROOT / 'scripts/academy_videos/reference_settings.json').read_text())
FONT = ROOT / 'scripts/academy_videos/assets/Manrope-600.ttf'
TITLE_FONT = ROOT / 'scripts/academy_videos/assets/Manrope-800.ttf'
LABELS = ['Comprendre la règle', 'Un exemple concret', 'À retenir']
REVISION = 5


def run(args):
    result = subprocess.run(args, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors='replace'))
    return result


def duration(path):
    return float(run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                      '-of', 'default=nw=1:nk=1', str(path)]).stdout)


def draw_text(draw, text, xy, width, size, color, max_lines, bold=False):
    font = ImageFont.truetype(str(TITLE_FONT if bold else FONT), size)
    lines, line = [], ''
    for word in text.split():
        trial = (line + ' ' + word).strip()
        if line and font.getlength(trial) > width:
            lines.append(line)
            line = word
        else:
            line = trial
    if line:
        lines.append(line)
    if len(lines) > max_lines:
        raise ValueError('Slide text overflow: ' + text)
    x, y = xy
    for line in lines:
        draw.text((x, y), line, font=font, fill=color)
        y += size * 1.38
    return y


def frame(sid, row, scene):
    im = Image.new('RGB', (1280, 720), '#f5f7fc')
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, 1280, 8), fill='#275de5')
    draw_text(d, 'INTÉGRALE ACADEMY  /  APS', (48, 28), 830, 18, '#193452', 1)
    draw_text(d, f'MODULE {sid[6:8]}  ·  {scene+1} / 3', (1010, 28), 250, 17, '#496078', 1)
    picture = ImageOps.fit(Image.open(OUT / f'assets/media/aps62/v2/module-{sid[6:8]}.webp').convert('RGB'), (390, 290))
    im.paste(picture, (842, 110))
    d = ImageDraw.Draw(im)
    draw_text(d, LABELS[scene].upper(), (48, 96), 744, 20, '#275de5', 1)
    end = draw_text(d, row['title'], (48, 140), 740, 38, '#152c48', 3, True)
    d.rounded_rectangle((48, end+20, 112, end+25), 2, fill='#ddb13e')
    key = ('rule', 'example', 'takeaway')[scene]
    # One complete idea on screen; the voice explains it, subtitles carry every word.
    first = row[key].split('. ', 1)[0].rstrip('.') + '.'
    draw_text(d, first, (48, end+48), 740, 29, '#24415d', 5)
    term = row['glossary'][scene]
    d.rounded_rectangle((842, 414, 1232, 560), 14, fill='#e5edfb')
    term_end = draw_text(d, term['term'], (860, 427), 355, 22, '#193452', 1, True)
    definition_end = draw_text(d, term['definition'], (860, term_end+8), 355, 18, '#24415d', 3)
    assert definition_end < 562, term
    for j in range(3):
        d.rounded_rectangle((48+j*405, 574, 431+j*405, 579), 2,
                            fill='#275de5' if j <= scene else '#dbe3ef')
    d.rectangle((0, 598, 1280, 720), fill='#101922')
    return im


async def speech(text, folder, index, slots):
    signature = hashlib.sha256((SETTINGS['voice'] + SETTINGS['rate'] + text).encode()).hexdigest()[:20]
    audio = folder / f'{index}-{signature}.mp3'
    timings = audio.with_suffix('.words.json')
    if audio.exists() and timings.exists():
        return audio, make_cues(text, json.loads(timings.read_text()))
    async with slots:
        for attempt in range(4):
            try:
                boundaries = []
                async def collect():
                    with audio.with_suffix('.partial').open('wb') as output:
                        async for item in edge_tts.Communicate(text, voice=SETTINGS['voice'],
                            rate=SETTINGS['rate'], boundary='WordBoundary').stream():
                            if item['type'] == 'audio':
                                output.write(item['data'])
                            elif item['type'] == 'WordBoundary':
                                boundaries.append(item)
                await asyncio.wait_for(collect(), timeout=100)
                cues = make_cues(text, boundaries)
                audio.with_suffix('.partial').replace(audio)
                timings.write_text(json.dumps(boundaries, ensure_ascii=False))
                return audio, cues
            except Exception:
                if attempt == 3:
                    raise
                await asyncio.sleep(2 * (attempt + 1))


def render(sid, row, voices, signature):
    folder, offset, captions, parts = WORK / sid, 0, [], []
    for index, (audio, cues) in enumerate(voices):
        png, srt, part = (folder / f'{index}.{ext}' for ext in ('png', 'srt', 'mp4'))
        picture = frame(sid, row, index)
        picture.save(png)
        if index == 0:
            picture.save(ASSETS / f'{sid}.jpg', quality=87)
        srt.write_text(''.join(f"{i+1}\n{timestamp(c['start'], ',')} --> {timestamp(c['end'], ',')}\n{c['text']}\n\n" for i, c in enumerate(cues)))
        # ASS is explicitly authored at the video resolution, avoiding implicit SRT scaling.
        ass = folder / f'{index}.ass'
        header = '[Script Info]\nScriptType: v4.00+\nPlayResX: 1280\nPlayResY: 720\nWrapStyle: 2\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,Manrope,38,&H00FFFFFF,&H00FFFFFF,&H00101922,&H00101922,0,0,0,0,100,100,0,0,1,0,0,2,55,55,22,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
        def ass_time(seconds):
            return timestamp(seconds)[:-1]
        ass.write_text(header + ''.join('Dialogue: 0,' + ass_time(c['start']) + ',' + ass_time(c['end']) + ',Default,,0,0,0,,' + c['text'].replace('\n', r'\N') + '\n' for c in cues))
        seconds = max(duration(audio) + .5, cues[-1]['end'] + .15)
        vf = f"ass={ass}:fontsdir={FONT.parent},format=yuv420p"
        run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-loop', '1', '-framerate', '12',
             '-i', str(png), '-i', str(audio), '-t', str(seconds), '-vf', vf,
             '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '29', '-tune', 'stillimage',
             '-threads', '2', '-c:a', 'aac', '-b:a', '72k', '-ar', '48000', '-af', 'apad',
             '-movflags', '+faststart', str(part)])
        encoded = duration(part)
        assert abs(encoded - seconds) < .2
        captions.extend(dict(c, start=c['start']+offset, end=c['end']+offset) for c in cues)
        offset += encoded
        parts.append(part)
    concat = folder / 'concat.txt'
    concat.write_text(''.join(f"file '{path}'\n" for path in parts))
    destination, temporary = ASSETS / f'{sid}.mp4', ASSETS / f'{sid}.partial.mp4'
    run(['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-y', '-f', 'concat', '-safe', '0',
         '-i', str(concat), '-c:v', 'copy', '-c:a', 'aac', '-b:a', '72k',
         '-af', 'aresample=async=1:first_pts=0', '-movflags', '+faststart', str(temporary)])
    actual = duration(temporary)
    assert abs(actual - offset) < .3 and actual > captions[-1]['end']
    temporary.replace(destination)
    (ASSETS / f'{sid}.vtt').write_text('WEBVTT\n\n' + ''.join(f"{timestamp(c['start'])} --> {timestamp(c['end'])}\n{c['text']}\n\n" for c in captions))
    result = dict(src=f'media/aps62/v5/{sid}.mp4', poster=f'media/aps62/v5/{sid}.jpg',
        captions=f'media/aps62/v5/{sid}.vtt', duration_seconds=actual,
        transcript='\n\n'.join(row[k] for k in ('rule', 'example', 'takeaway')),
        voice=SETTINGS['voice'], rate=SETTINGS['rate'], burned_captions=True,
        render_revision=REVISION, content_sha256=signature, course_only=True)
    (folder / 'result.json').write_text(json.dumps(result, ensure_ascii=False))
    print(sid, round(actual, 1), 'seconds', destination.stat().st_size, flush=True)
    return result


async def main():
    assert SETTINGS['voice'] == 'fr-FR-HenriNeural' and SETTINGS['rate'] == '-2%'
    communication._SSL_CTX.load_verify_locations(cafile='/etc/ssl/certs/ca-certificates.crt')
    ASSETS.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=3)
    speech_slots, video_slots = asyncio.Semaphore(5), asyncio.Semaphore(3)
    path = OUT / 'video_manifest_v5.json'
    manifest = json.loads(path.read_text()) if path.exists() else {}
    only = os.environ.get('APS62_ONLY')
    async def one(sid, row):
        async with video_slots:
            folder = WORK / sid
            folder.mkdir(exist_ok=True)
            signature = hashlib.sha256(json.dumps(row, ensure_ascii=False, sort_keys=True).encode()
                + Path(__file__).read_bytes() + (ROOT/'scripts/aps62_v5/captions.py').read_bytes()).hexdigest()
            cached = json.loads((folder/'result.json').read_text()) if (folder/'result.json').exists() else {}
            if cached.get('content_sha256') == signature and (ASSETS/f'{sid}.mp4').exists():
                result = cached
            else:
                voices = await asyncio.gather(*(speech(row[key], folder, i, speech_slots)
                    for i, key in enumerate(('rule', 'example', 'takeaway'))))
                result = await asyncio.get_running_loop().run_in_executor(pool, render, sid, row, voices, signature)
            manifest[sid] = result
            path.write_text(json.dumps(dict(sorted(manifest.items())), ensure_ascii=False, indent=2)+'\n')
    await asyncio.gather(*(one(sid, row) for sid, row in courses().items() if not only or sid == only))
    print('DONE', len(manifest), 'course videos', flush=True)


if __name__ == '__main__':
    asyncio.run(main())
