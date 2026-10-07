"""Render continuous narrated APS lessons, with timed animated visual explanations.

Actual audio length is checked before encoding: a short lesson is an error, never
made longer with silence. Build-only dependencies: edge-tts, Pillow and ffmpeg.
"""
import asyncio
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import re
import sys

import edge_tts.communicate as communication
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.aps62_v6.content import courses
from scripts.aps62_v5.captions import canonical, timestamp
from scripts.render_aps62_v5 import speech, duration, run, FONT, TITLE_FONT, SETTINGS, draw_text

OUT = ROOT / 'elearning_native/aps62'
ASSETS = OUT / 'assets/media/aps62/v6'
WORK = Path(os.environ.get('APS62_WORK', '/tmp/aps62-v6'))


def wrapped(text, width=50, limit=7):
    font = ImageFont.truetype(str(FONT), 30)
    lines, current = [], ''
    for word in text.split():
        trial = (current + ' ' + word).strip()
        if font.getlength(trial) > width * 15 and current:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    assert len(lines) <= limit, text
    return r'\N'.join(lines)


def background(sid, row, index):
    scene = row['scenes'][index]
    im = Image.new('RGB', (1280, 720), '#f4f7fc')
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, 1280, 8), fill='#245bdc')
    draw_text(d, 'INTÉGRALE ACADEMY  /  APS', (48, 26), 880, 18, '#1c3651', 1)
    draw_text(d, f'MODULE {sid[6:8]}  ·  {index+1} / {len(row["scenes"])}', (986, 26), 270, 17, '#45617f', 1)
    end = draw_text(d, scene['title'], (48, 76), 1175, 37, '#173350', 3, True)
    assert end < 233, scene['title']
    d.rounded_rectangle((48, end+12, 120, end+17), 3, fill='#e1b53f')
    if scene['kind'] not in ('glossary', 'comparison'):
        picture = ImageOps.fit(Image.open(OUT/f'assets/media/aps62/v2/module-{sid[6:8]}.webp').convert('RGB'), (408, 282))
        im.paste(picture, (824, 260))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle((48, 254, 790, 553), 18, fill='#e4ecfa')
    d.rectangle((0, 598, 1280, 720), fill='#101922')
    for j in range(len(row['scenes'])):
        left = 48 + j * 1184 / len(row['scenes'])
        d.rounded_rectangle((left, 576, left + 1184 / len(row['scenes']) - 4, 581), 2,
            fill='#245bdc' if j <= index else '#d5dfed')
    return im


def ass_time(t):
    return timestamp(t)[:-1]


def render(sid, row, audio, cues, signature):
    folder = WORK/sid
    words = json.loads(audio.with_suffix('.words.json').read_text())
    audio_seconds = duration(audio)
    assert audio_seconds >= 300, f'{sid}: only {audio_seconds}s of actual narration'
    # Locate chapter boundaries in the exact spoken words, including edge-tts
    # punctuation normalization. Caption alignment already checked completeness.
    starts, char_count, word_index, cursor = [0.0], 0, 0, 0
    for scene in row['scenes'][:-1]:
        char_count += len(canonical(scene['text']))
        while word_index < len(words) and cursor < char_count:
            cursor += len(canonical(words[word_index]['text']))
            word_index += 1
        assert cursor == char_count, (sid, scene['title'])
        starts.append(max(0, words[word_index]['offset']/1e7-.08))
    ends = starts[1:] + [audio_seconds + .25]
    concat, events = [], []
    def event(start, end, text, style='Visual', layer=1):
        events.append(f'Dialogue: {layer},{ass_time(start)},{ass_time(end)},{style},,0,0,0,,{text}\n')
    chapters = []
    for i, (scene, start, end) in enumerate(zip(row['scenes'], starts, ends)):
        picture = background(sid, row, i)
        path = folder/f'{i}.png'
        picture.save(path)
        if i == 0:
            # The poster includes a useful course idea even before playback.
            poster = picture.copy()
            draw_text(ImageDraw.Draw(poster), row['rule'].split('. ', 1)[0]+'.', (76, 294), 684, 30, '#193b61', 6)
            poster.save(ASSETS/f'{sid}.jpg', quality=86)
        concat.extend([f"file '{path}'", f'duration {end-start:.6f}'])
        chapters.append(dict(title=scene['title'], start_seconds=round(start, 3), end_seconds=round(end, 3)))
        if scene['kind'] == 'glossary':
            positions = [canonical(scene['text']).find(canonical(t['term'])) for t in row['glossary']]
            total = len(canonical(scene['text']))
            for j, term in enumerate(row['glossary']):
                reveal = start + (end-start) * positions[j] / total
                x = 50 + j*404
                text = r'{\an7\move('+str(x+28)+',262,'+str(x)+r',262,0,650)\fad(350,150)\fs29\b1\c&H854621&}'+wrapped(term['term'],23,2)
                text += r'\N\N{\fs25\b0\c&H51361C&}'+wrapped(term['definition'],22,6)
                event(reveal, end, text)
        elif scene['kind'] == 'comparison':
            for j, (label, value, color) in enumerate([('L’action adaptée', row['good'], '456919'), ('L’erreur à éviter', row['bad'], '254EA1')]):
                x = 52 + j*614
                text = r'{\an7\move('+str(x+24)+',265,'+str(x)+r',265,0,650)\fad(350,150)\fs27\b1\c&H'+color+r'&}'+label
                text += r'\N\N{\fs28\b0\c&H51361C&}'+wrapped(value,36,6)
                event(start + j*min(8,(end-start)/3), end, text)
        else:
            # A complete idea appears as the narration begins. No clipped sentences.
            sentence = re.split(r'(?<=[.!?])\s+', scene['text'])[0]
            if len(sentence.split()) > 40:
                sentence = row['takeaway']
            event(start+.15, end, r'{\an7\move(104,286,76,286,0,650)\fad(350,180)\fs30\c&H51361C&}'+wrapped(sentence,45,7))
            # The underline grows across the card to indicate the current chapter;
            # it is separate from captions and never flashes or masks the content.
            event(start, end, r'{\an7\pos(76,551)\p1\c&HDC5B24&\fscx0\t(0,'+str(round((end-start)*1000))+r',\fscx100)}m 0 0 l 684 0 684 3 0 3', layer=0)
    concat.append(f"file '{path}'")
    (folder/'frames.txt').write_text('\n'.join(concat)+'\n')
    header = '[Script Info]\nScriptType: v4.00+\nPlayResX: 1280\nPlayResY: 720\nWrapStyle: 2\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Caption,Manrope,38,&H00FFFFFF,&H00FFFFFF,&H00101922,&H00101922,0,0,0,0,100,100,0,0,1,0,0,2,55,55,22,1\nStyle: Visual,Manrope,30,&H0051361C,&H0051361C,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
    for cue in cues:
        event(cue['start'], cue['end'], cue['text'].replace('\n', r'\N'), 'Caption', 2)
    ass = folder/'lesson.ass'
    ass.write_text(header+''.join(events))
    temporary = folder/'complete.mp4'
    run(['ffmpeg','-nostdin','-v','error','-y','-f','concat','-safe','0','-i',str(folder/'frames.txt'),
        '-i',str(audio),'-t',str(audio_seconds+.25),'-vf',f'fps=12,ass={ass}:fontsdir={FONT.parent},format=yuv420p',
        '-c:v','libx264','-preset','ultrafast','-crf','29','-threads','1',
        '-c:a','aac','-b:a','64k','-ar','48000','-af','apad','-movflags','+faststart',str(temporary)])
    actual = duration(temporary)
    assert actual >= 300 and abs(actual-audio_seconds) < .5 and actual >= cues[-1]['end']
    temporary.replace(ASSETS/f'{sid}.mp4')
    (ASSETS/f'{sid}.vtt').write_text('WEBVTT\n\n'+''.join(f"{timestamp(c['start'])} --> {timestamp(c['end'])}\n{c['text']}\n\n" for c in cues))
    result = dict(src=f'media/aps62/v6/{sid}.mp4', poster=f'media/aps62/v6/{sid}.jpg',
        captions=f'media/aps62/v6/{sid}.vtt', duration_seconds=actual,
        narration_seconds=audio_seconds, transcript=row['transcript'], chapters=chapters,
        voice=SETTINGS['voice'], rate=SETTINGS['rate'], burned_captions=True,
        animated=True, render_revision=6, content_sha256=signature, course_only=True)
    (folder/'result.json').write_text(json.dumps(result, ensure_ascii=False))
    print(sid, round(actual,1), 'seconds', (ASSETS/f'{sid}.mp4').stat().st_size, flush=True)
    return result


async def main():
    communication._SSL_CTX.load_verify_locations(cafile='/etc/ssl/certs/ca-certificates.crt')
    ASSETS.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=5)
    speech_slots, video_slots = asyncio.Semaphore(4), asyncio.Semaphore(5)
    path = OUT/'video_manifest_v6.json'
    manifest = json.loads(path.read_text()) if path.exists() else {}
    only = os.environ.get('APS62_ONLY')
    async def one(sid, row):
        async with video_slots:
            folder = WORK/sid
            folder.mkdir(exist_ok=True)
            signature = hashlib.sha256(json.dumps(row,ensure_ascii=False,sort_keys=True).encode()+Path(__file__).read_bytes()).hexdigest()
            cached = json.loads((folder/'result.json').read_text()) if (folder/'result.json').exists() else {}
            if cached.get('content_sha256') == signature and (ASSETS/f'{sid}.mp4').exists():
                result = cached
            else:
                audio, cues = await speech(row['transcript'], folder, 0, speech_slots)
                result = await asyncio.get_running_loop().run_in_executor(pool, render, sid, row, audio, cues, signature)
            manifest[sid] = result
            path.write_text(json.dumps(dict(sorted(manifest.items())),ensure_ascii=False,indent=2)+'\n')
    await asyncio.gather(*(one(sid,row) for sid,row in courses().items() if not only or sid == only))
    print('DONE',len(manifest),'continuous course videos',flush=True)


if __name__ == '__main__':
    asyncio.run(main())
