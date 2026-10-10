"""Render paced APS v11 lessons, retaining every authored spoken word.

Pitch-preserving tempo reduction, meaningful reflection pauses, exact word
landmarks and readable captions are applied together on one measured timeline.
"""
import asyncio
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys

from PIL import Image, ImageDraw, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.aps62_v10.video_content import courses
from scripts.aps62_v5.captions import canonical, timestamp
from scripts.render_aps62_v5 import speech, duration, run, FONT, TITLE_FONT, SETTINGS, draw_text
from scripts.aps62_v11.video_pacing import (TEMPO, make_plan, make_paced_cues,
    caption_metrics, insert_pcm_pauses, visual_frames)

OUT = ROOT / 'elearning_native/aps62'
from scripts.aps62_v10.field_visuals import draw_field_scene, fit_text

ASSETS = OUT / 'assets/media/aps62/v9'
WORK = Path(os.environ.get('APS62_WORK', '/tmp/aps62-v9'))


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


def background(sid, row, index, phase=1.0):
    scene = row['scenes'][index]
    im = Image.new('RGB', (1280, 720), '#f4f7fc')
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, 1280, 8), fill='#245bdc')
    draw_text(d, 'INTÉGRALE ACADEMY  /  APS', (48, 26), 880, 18, '#1c3651', 1)
    draw_text(d, f'MODULE {sid[6:8]}  ·  {index+1} / {len(row["scenes"])}', (986, 26), 270, 17, '#45617f', 1)
    end = draw_text(d, scene['title'], (48, 76), 1175, 37, '#173350', 3, True)
    assert end < 233, scene['title']
    d.rounded_rectangle((48, end+12, 120, end+17), 3, fill='#e1b53f')
    if scene['kind'] not in ('glossary', 'comparison') and not scene['kind'].startswith('field_'):
        picture = ImageOps.fit(Image.open(OUT/f'assets/media/aps62/v2/module-{sid[6:8]}.webp').convert('RGB'), (408, 282))
        im.paste(picture, (824, 260))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle((48, 254, 790, 553), 18, fill='#e4ecfa')
    d.rectangle((0, 598, 1280, 720), fill='#101922')
    for j in range(len(row['scenes'])):
        left = 48 + j * 1184 / len(row['scenes'])
        d.rounded_rectangle((left, 576, left + 1184 / len(row['scenes']) - 4, 581), 2,
            fill='#245bdc' if j <= index else '#d5dfed')
    if scene['kind'].startswith('field_'):
        draw_field_scene(im, scene, phase)
        if scene['kind'] == 'field_dialogue' and phase < 0:
            context = scene['text'].split(scene['dialogue'][0]['speaker']+' :',1)[0].strip()
            d.rounded_rectangle((48,240,1232,550),18,fill='#e4ecfa')
            fit_text(d, context, (76,272,1128,236),30)
    return im


def ass_time(t):
    return timestamp(t)[:-1]


def prepare_paced_audio(sid, row, audio):
    folder = WORK/sid
    boundaries = json.loads(audio.with_suffix('.words.json').read_text())
    source_seconds = duration(audio)
    assert source_seconds >= 300, f'{sid}: source narration too short'
    plan = make_plan(row, boundaries, source_seconds)
    slow_audio, paced_audio = folder/'slowed.wav', folder/'paced.wav'
    run(['ffmpeg','-nostdin','-v','error','-y','-i',str(audio),
         '-af',f'atempo={TEMPO}','-ac','1','-ar','48000','-c:a','pcm_s16le',str(slow_audio)])
    pcm = insert_pcm_pauses(slow_audio, paced_audio, plan['insertions'])
    plan['pcm'] = pcm
    plan['planned_seconds'] = pcm['duration_seconds']
    plan['scenes'][-1]['end_seconds'] = pcm['duration_seconds']
    assert pcm['duration_seconds'] > plan['words'][-1]['end']
    cues = make_paced_cues(row['transcript'], plan['words'], pcm['duration_seconds'])
    plan['captions'] = caption_metrics(cues)
    (folder/'pacing.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2)+'\n')
    return paced_audio, cues, plan


def render(sid, row, audio, cues, signature):
    folder = WORK/sid
    audio, cues, plan = prepare_paced_audio(sid, row, audio)
    audio_seconds = duration(audio)
    concat, events = [], []
    def event(start, end, text, style='Visual', layer=1):
        events.append(f'Dialogue: {layer},{ass_time(start)},{ass_time(end)},{style},,0,0,0,,{text}\n')
    chapters = []
    for i, (scene, layout) in enumerate(zip(row['scenes'], plan['scenes'])):
        start, end = layout['start_seconds'], layout['end_seconds']
        picture = background(sid, row, i)
        path = folder/f'{i}.png'
        picture.save(path)
        if i == 0:
            # The poster includes a useful course idea even before playback.
            poster = picture.copy()
            draw_text(ImageDraw.Draw(poster), row['rule'].split('. ', 1)[0]+'.', (76, 294), 684, 30, '#193b61', 6)
            poster.save(ASSETS/f'{sid}.jpg', quality=86)
        if scene['kind'].startswith('field_'):
            # No correction, document or dialogue turn appears before its exact
            # spoken landmark. Reflection pauses keep the situation visible.
            for frame_index, frame in enumerate(visual_frames(scene, layout)):
                frame_path = folder/f'{i}-landmark-{frame_index}.png'
                background(sid, row, i, frame['phase']).save(frame_path)
                concat.extend([f"file '{frame_path}'", f'duration {frame["end_seconds"]-frame["start_seconds"]:.6f}'])
                path = frame_path
        else:
            concat.extend([f"file '{path}'", f'duration {end-start:.6f}'])
        chapters.append(dict(title=scene['title'], start_seconds=round(start, 3), end_seconds=round(end, 3)))
        if scene['kind'].startswith('field_'):
            # The complete evidence/decision diagram is in the background.
            event(start, end, r'{\an7\pos(48,564)\p1\c&HDC5B24&\fscx0\t(0,'+str(round((end-start)*1000))+r',\fscx100)}m 0 0 l 1184 0 1184 3 0 3', layer=0)
        elif scene['kind'] == 'glossary':
            for j, term in enumerate(row['glossary']):
                reveal = layout['reveal_seconds']['term_'+str(j)]
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
                # A summary can reveal the answer to the example too early.
                sentence = 'Prenez le temps de lire et de comprendre la situation.'
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
        '-i',str(audio),'-t',str(audio_seconds),'-vf',f'fps=12,ass={ass}:fontsdir={FONT.parent},format=yuv420p',
        '-c:v','libx264','-preset','ultrafast','-crf','29','-threads','1',
        '-c:a','aac','-b:a','64k','-ar','48000','-af','apad','-movflags','+faststart',str(temporary)])
    actual = duration(temporary)
    assert actual >= 300 and abs(actual-audio_seconds) < .5 and actual >= cues[-1]['end']
    temporary.replace(ASSETS/f'{sid}.mp4')
    (ASSETS/f'{sid}.vtt').write_text('WEBVTT\n\n'+''.join(f"{timestamp(c['start'])} --> {timestamp(c['end'])}\n{c['text']}\n\n" for c in cues).rstrip()+'\n')
    result = dict(src=f'media/aps62/v9/{sid}.mp4', poster=f'media/aps62/v9/{sid}.jpg',
        captions=f'media/aps62/v9/{sid}.vtt', duration_seconds=actual,
        narration_seconds=audio_seconds, transcript=row['transcript'], chapters=chapters,
        voice=SETTINGS['voice'], rate=SETTINGS['rate'], burned_captions=True,
        animated=True, field_demonstrations=True, render_revision=9, content_sha256=signature, course_only=True,
        pacing=dict(tempo=TEMPO, pitch_preserved=True, source_narration_seconds=plan['source_seconds'],
                    added_pause_seconds=plan['added_pause_seconds'],
                    transition_target_seconds=plan['transition_target_seconds'],
                    correction_target_seconds=plan['correction_target_seconds'],
                    final_definition_minimum_seconds=plan['final_definition_minimum_seconds'],
                    word_aligned_visuals=True, all_words_preserved=True,
                    pause_count=len(plan['insertions']), captions=plan['captions'],
                    pauses=[{k:v for k,v in p.items() if k!='source_cut_seconds'} for p in plan['insertions']],
                    scenes=[dict(title=s['title'], kind=s['kind'], start_seconds=l['start_seconds'],
                                 end_seconds=l['end_seconds'], reveal_seconds=l['reveal_seconds'])
                            for s,l in zip(row['scenes'],plan['scenes'])]))
    (folder/'result.json').write_text(json.dumps(result, ensure_ascii=False))
    print(sid, round(actual,1), 'seconds', (ASSETS/f'{sid}.mp4').stat().st_size, flush=True)
    return result


async def reliable_speech(transcript, folder, slots):
    """Retry a truncated provider response; never pad speech or discard words.

    Some otherwise successful streams include all word boundaries but stop the
    MP3 before the final words. Use a fresh cache key for each retry and require
    the real decoded audio to cover the final cue before any video is encoded.
    """
    for attempt in range(3):
        # Existing full source takes may be reused locally; the signature in the
        # filename includes exact text and voice settings. CI regenerates them.
        source_folder = Path(os.environ.get('APS62_SOURCE_WORK', '/tmp/aps62-v8'))/folder.name
        if source_folder != folder and source_folder.exists():
            expected = hashlib.sha256((SETTINGS['voice']+SETTINGS['rate']+transcript).encode()).hexdigest()[:20]
            for suffix in ('.mp3','.words.json'):
                original = source_folder/f'{attempt}-{expected}{suffix}'
                destination = folder/original.name
                if original.exists() and not destination.exists():
                    shutil.copyfile(original, destination)
        audio, cues = await speech(transcript, folder, attempt, slots)
        actual = duration(audio)
        if actual >= 300 and cues and actual >= cues[-1]['end']:
            run(['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-i', str(audio), '-f', 'null', '-'])
            return audio, cues
        print(f'{folder.name}: incomplete narration on take {attempt+1}, requesting a fresh take', flush=True)
    raise RuntimeError(f'{folder.name}: provider audio does not cover all spoken words after three takes')


async def main():
    # edge-tts verifies TLS using its bundled CA store on macOS and Linux.
    # Do not depend on a Linux-only path or change the library's private context.
    ASSETS.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    workers = max(1, int(os.environ.get('APS62_RENDER_WORKERS', '3')))
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
    speech_slots = asyncio.Semaphore(max(1, int(os.environ.get('APS62_SPEECH_WORKERS', '3'))))
    video_slots = asyncio.Semaphore(workers)
    path = OUT/'video_manifest_v9.json'
    manifest = json.loads(path.read_text()) if path.exists() else {}
    only = {sid.strip() for sid in os.environ.get('APS62_ONLY', '').split(',') if sid.strip()}
    shard_count = int(os.environ.get('APS62_SHARD_COUNT', '1'))
    shard_index = int(os.environ.get('APS62_SHARD_INDEX', '0'))
    assert shard_count > 0 and 0 <= shard_index < shard_count
    dependencies = b''.join(p.read_bytes() for p in (
        Path(__file__), ROOT/'scripts/render_aps62_v5.py', ROOT/'scripts/aps62_v11/video_pacing.py',
        ROOT/'scripts/aps62_v9/field_videos.py', ROOT/'scripts/aps62_v9/field_visuals.py',
        ROOT/'scripts/aps62_v10/video_content.py', ROOT/'scripts/aps62_v10/content_fixes.py',
        ROOT/'scripts/aps62_v10/radio_demonstrations.py', ROOT/'scripts/aps62_v10/field_visuals.py',
        ROOT/'scripts/aps62_v5/captions.py',
        ROOT/'scripts/academy_videos/reference_settings.json', FONT, TITLE_FONT))
    async def one(sid, row):
        async with video_slots:
            folder = WORK/sid
            folder.mkdir(exist_ok=True)
            signature = hashlib.sha256(json.dumps(row,ensure_ascii=False,sort_keys=True).encode()+dependencies).hexdigest()
            cached = json.loads((folder/'result.json').read_text()) if (folder/'result.json').exists() else {}
            if cached.get('content_sha256') == signature and (ASSETS/f'{sid}.mp4').exists():
                result = cached
            else:
                audio, cues = await reliable_speech(row['transcript'], folder, speech_slots)
                result = await asyncio.get_running_loop().run_in_executor(pool, render, sid, row, audio, cues, signature)
            manifest[sid] = result
            path.write_text(json.dumps(dict(sorted(manifest.items())),ensure_ascii=False,indent=2)+'\n')
    selected = [(sid, row) for index, (sid, row) in enumerate(sorted(courses().items()))
                if index % shard_count == shard_index and (not only or sid in only)]
    assert selected, 'No matching APS video to render'
    await asyncio.gather(*(one(sid,row) for sid,row in selected))
    print('DONE',len(manifest),'continuous course videos',flush=True)


if __name__ == '__main__':
    asyncio.run(main())
