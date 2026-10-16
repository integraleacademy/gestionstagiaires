"""Rebuild the eight VTC visual tracks without changing narration or checkpoints.

The reviewed visual plan cites the exact narration that supports every card.
Cards appear with the corresponding caption (or original synthesis word when
that local build cache is available). The original AAC packets are copied and
verified bit for bit. Playback speed and thinking breaks belong to the player,
so all historical learner positions remain on the same media timeline.

Build-only dependencies match render_bilingual_english.py. No TTS or network
request is made. VTC_ONLY selects one module; VTC_PACING_WORK selects scratch.
"""
import argparse
import concurrent.futures
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import wave

from PIL import ImageDraw

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.aps62_v5.captions import canonical, timestamp
from scripts.vtc import render_visual_videos as visual
from scripts.vtc.render_bilingual_english import duration, ffmpeg, VOICES, RATES

OUT = ROOT / 'elearning_native/vtc'
ASSETS = OUT / 'assets/media/vtc/v9'
WORK = Path(os.environ.get('VTC_PACING_WORK', '/tmp/vtc-pacing-v9'))
BILINGUAL_WORK = Path(os.environ.get('VTC_BILINGUAL_WORK', '/tmp/vtc-bilingual-v7'))


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audio_fingerprint(path):
    """Fingerprint encoded packets, independent of MP4 mux timestamps."""
    import av
    digest = hashlib.sha256()
    count = 0
    with av.open(str(path)) as container:
        stream = container.streams.audio[0]
        properties = dict(codec=stream.codec_context.name,
                          sample_rate=stream.codec_context.sample_rate,
                          channels=stream.codec_context.channels)
        for packet in container.demux(stream):
            if packet.size:
                digest.update(bytes(packet))
                count += 1
    return dict(properties, packets=count, sha256=digest.hexdigest())


def read_vtt(path):
    cues = []
    def seconds(value):
        h, m, s = value.split(':')
        return int(h)*3600 + int(m)*60 + float(s)
    for block in path.read_text().strip().split('\n\n')[1:]:
        lines = block.splitlines()
        start, end = lines[0].split(' --> ')
        cues.append(dict(start=seconds(start), end=seconds(end), text='\n'.join(lines[1:])))
    assert cues and all(c['start'] < c['end'] for c in cues)
    return cues


def caption_timeline(text, cues):
    """Map normalized source characters to an existing caption, without ASR."""
    observed = ''.join(canonical(c['text']) for c in cues)
    assert observed == canonical(text), (text[:80], observed[:80])
    result = []
    for cue in cues:
        result.extend([dict(start=cue['start'], end=cue['end'], method='caption-cue')]
                      * len(canonical(cue['text'])))
    return result


def bilingual_word_timeline(source, scene_index, text, chapter):
    """Reuse v7 timings after its measured language-piece joins, if available."""
    words, offset, number = [], 0., 0
    for segment in source['language_segments'][scene_index]:
        spoken = segment['text'].strip().replace('/', ', ').replace('=', ' ')
        if not canonical(spoken):
            continue
        lang = segment['lang']
        key = hashlib.sha256((VOICES[lang]+RATES[lang]+spoken).encode()).hexdigest()[:24]
        timing = BILINGUAL_WORK / 'speech' / (key+'.json')
        pcm = BILINGUAL_WORK / 'E' / f'{scene_index:02}-{number:02}.wav'
        if not timing.exists() or not pcm.exists():
            return None
        boundaries = json.loads(timing.read_text())
        trim_start = max(0, boundaries[0]['offset']/1e7-.09)
        tempo = source['scene_audio'][scene_index]['french_tempo'] if lang == 'fr' else 1.
        for word in boundaries:
            start = chapter['start_seconds']+offset+(word['offset']/1e7-trim_start)/tempo
            end = start+word['duration']/1e7/tempo
            words.append(dict(text=word['text'], start=start, end=end))
        with wave.open(str(pcm), 'rb') as stream:
            offset += stream.getnframes()/stream.getframerate()
        number += 1
    assert ''.join(canonical(w['text']) for w in words) == canonical(text), scene_index
    result = []
    for word in words:
        result.extend([dict(start=round(word['start'], 3), end=round(word['end'], 3),
                            method='original-synthesis-word')]*len(canonical(word['text'])))
    return result


def source_data():
    sources = json.loads((OUT/'video_manifest_v4.json').read_text())
    sources['E'] = json.loads((OUT/'video_english_bilingual_v7.json').read_text())
    scripts = json.loads((OUT/'video_scripts_v4.json').read_text())
    return sources, scripts


def build_plan(letter, source, script, reviewed):
    scenes = deepcopy(script['scenes'])
    paragraphs = source['transcript'].split('\n\n')
    captions = read_vtt(OUT/'assets'/source['captions'])
    assert len(scenes) == len(paragraphs) == len(source['chapters']) == 24
    assert len(reviewed['scenes']) == 24
    timings = []
    for i, (scene, text, chapter, corrected) in enumerate(zip(
            scenes, paragraphs, source['chapters'], reviewed['scenes'])):
        assert scene['ref'] == corrected['ref'] == chapter['ref']
        assert scene['kind'] == corrected['kind'] == chapter['kind']
        assert len(corrected['points']) == 3
        scene.update(corrected)
        scene['text'] = text
        cues = [c for c in captions if chapter['start_seconds'] <= c['start'] < chapter['end_seconds']]
        timeline = (bilingual_word_timeline(source, i, text, chapter) if letter == 'E' else None)
        if timeline is None:
            timeline = caption_timeline(text, cues)
        normalized, cursor, reveals = canonical(text), 0, []
        for point in scene['points']:
            assert point['anchor_text'] in text, (letter, i, point['anchor_text'])
            needle = canonical(point['anchor_text'])
            position = normalized.find(needle, cursor)
            assert position >= 0 and needle, (letter, i, point['anchor_text'])
            cursor = position+len(needle)
            boundary = timeline[position]
            reveal = max(chapter['start_seconds'], boundary['start'])
            assert reveal < chapter['end_seconds']-.1
            reveals.append(dict(anchor_text=point['anchor_text'],
                                at_seconds=round(reveal, 3),
                                timing_method=boundary['method'],
                                source_interval_seconds=[boundary['start'], boundary['end']]))
        assert reveals == sorted(reveals, key=lambda r: r['at_seconds'])
        timings.append(dict(scene=i, ref=scene['ref'], kind=scene['kind'], points=reveals))
    return scenes, captions, timings


ASS_HEADER = '''[Script Info]
ScriptType: v4.00+
PlayResX: 1280
PlayResY: 720
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,Manrope,36,&H00FFFFFF,&H00FFFFFF,&H0029141D,&H0029141D,0,0,0,0,100,100,0,0,1,0,0,2,55,55,21,1
Style: Visual,Manrope,26,&H003A1C28,&H003A1C28,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''


def prepare_visuals(letter, source, scenes, captions, timings, folder):
    events, frames = [], []
    def event(start, end, text, style='Visual', layer=1):
        events.append(f'Dialogue: {layer},{timestamp(start)[:-1]},{timestamp(end)[:-1]},'
                      f'{style},,0,0,0,,{text}\n')
    for i, (scene, chapter, timing) in enumerate(zip(scenes, source['chapters'], timings)):
        end = chapter['end_seconds'] if i < 23 else source['duration_seconds']
        seconds = end-chapter['start_seconds']
        picture = visual.background(letter, scene, i, len(scenes))
        png = folder/f'scene-{i:02}.png'
        picture.save(png)
        frames.extend([f"file '{png}'", f'duration {seconds:.6f}'])
        for j, (point, reveal) in enumerate(zip(scene['points'], timing['points'])):
            if scene['kind'] == 'concept':
                x, y, title = 510, 247+j*108, point['label']
                title_size, body_size, width, title_lines, body_lines = 21, 25, 694, 1, 2
            else:
                x, y, title = 72+j*407, 349, point['title']
                title_size, body_size, width, title_lines, body_lines = 25, 26, 318, 2, 4
            # No sliding animation: a short fade avoids dragging a reader's gaze.
            value = (r'{\an7\pos('+str(x)+','+str(y)+r')\fad(120,0)\fs'+str(title_size)
                     + r'\b1\c&HBD4570&}'+visual.wrapped(title,title_size,width,title_lines))
            value += (r'\N{\fs'+str(body_size)+r'\b0\c&H3A1C28&}'
                      +visual.wrapped(point['text'],body_size,width,body_lines))
            event(reveal['at_seconds'], end, value)
            if scene['kind'] == 'method':
                event(reveal['at_seconds'], end,
                      r'{\an7\pos('+str(x)+r',543)\p1\c&HBD4570&}m 0 0 l 318 0 318 4 0 4', layer=0)
        if i == 0:
            # A complete first scene gives the idle learner a legible overview.
            poster = picture.copy()
            draw = ImageDraw.Draw(poster)
            for j, point in enumerate(scene['points']):
                visual.draw_text(draw,point['label'],(510,247+j*108),694,21,visual.PURPLE,1,True)
                visual.draw_text(draw,point['text'],(510,277+j*108),694,24,visual.INK,2)
            poster.save(folder/'poster.jpg', quality=88)
    for cue in captions:
        event(cue['start'],cue['end'],cue['text'].replace('\n',r'\N'),'Caption',2)
    frames.append(f"file '{png}'")
    (folder/'frames.txt').write_text('\n'.join(frames)+'\n')
    (folder/'lesson.ass').write_text(ASS_HEADER+''.join(events))


def render(letter, source, script, reviewed, plan_only=False):
    folder = WORK/letter
    folder.mkdir(parents=True, exist_ok=True)
    scenes, captions, timings = build_plan(letter, source, script, reviewed)
    prepare_visuals(letter, source, scenes, captions, timings, folder)
    source_video = OUT/'assets'/source['src']
    signature = hashlib.sha256(json.dumps(dict(source=source, visual_plan=reviewed),
        sort_keys=True, ensure_ascii=False).encode()+Path(__file__).read_bytes()).hexdigest()
    (folder/'visual-timings.json').write_text(json.dumps(timings, ensure_ascii=False, indent=2)+'\n')
    if plan_only:
        print('PLAN',letter,len(scenes),'scenes',flush=True)
        return None
    cached_path = folder/'result.json'
    target = ASSETS/f'lesson-{letter.lower()}.mp4'
    if cached_path.exists() and target.exists():
        cached = json.loads(cached_path.read_text())
        if cached.get('content_sha256') == signature and cached.get('file_sha256') == sha256(target):
            print('CACHED',letter,flush=True)
            return cached
    temporary = folder/'complete.mp4'
    print('RENDER',letter,source['duration_seconds'],'seconds',flush=True)
    ffmpeg(['-f','concat','-safe','0','-i',folder/'frames.txt','-i',source_video,
            '-map','0:v:0','-map','1:a:0','-t',source['duration_seconds'],
            '-vf',f'fps=20,ass={folder / "lesson.ass"}:fontsdir={visual.FONT.parent},format=yuv420p',
            '-c:v','libx264','-preset','veryfast','-crf','27','-threads','2',
            '-c:a','copy','-movflags','+faststart',temporary])
    actual = duration(temporary)
    assert abs(actual-source['duration_seconds']) <= .05, (letter,actual,source['duration_seconds'])
    original_audio = audio_fingerprint(source_video)
    assert audio_fingerprint(temporary) == original_audio, (letter,'AAC packets changed')
    temporary.replace(target)
    poster = ASSETS/f'lesson-{letter.lower()}.jpg'
    poster.write_bytes((folder/'poster.jpg').read_bytes())
    result = deepcopy(source)
    result.update(src=f'media/vtc/v9/lesson-{letter.lower()}.mp4',
                  poster=f'media/vtc/v9/lesson-{letter.lower()}.jpg',
                  source_video=source['src'], source_file_sha256=sha256(source_video),
                  source_content_sha256=source['content_sha256'],
                  file_sha256=sha256(target), poster_sha256=sha256(poster),
                  captions_sha256=sha256(OUT/'assets'/source['captions']),
                  audio_provenance=dict(mode='encoded-packet-copy', **original_audio),
                  content_sha256=signature, render_revision=9, visual_reveals=timings,
                  actual_duration_seconds=actual,
                  visual_timing_note='Cards use the original synthesis word when available; '
                  'otherwise the original caption cue containing the cited phrase. '
                  'Caption cues can start before the cited word within the same sentence.')
    cached_path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print('READY',letter,actual,'seconds',target.stat().st_size,'bytes',flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--only', default=os.environ.get('VTC_ONLY'))
    parser.add_argument('--plan-only', action='store_true')
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args()
    ASSETS.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    sources, scripts = source_data()
    reviewed = json.loads((OUT/'video_visuals_v9.json').read_text())
    assert reviewed['revision'] == 9
    letters = [args.only.upper()] if args.only else list('ABCDEFGH')
    for letter in letters:
        assert reviewed['source_transcript_sha256'][letter] == hashlib.sha256(
            sources[letter]['transcript'].encode()).hexdigest(), letter
    manifest_path = OUT/'video_pacing_v9.json'
    manifest = (json.loads(manifest_path.read_text()) if manifest_path.exists()
                else dict(revision=9, default_playback_rate=.85, modules={}))
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(render, letter, sources[letter], scripts[letter],
                               reviewed['modules'][letter], args.plan_only):letter for letter in letters}
        for future in concurrent.futures.as_completed(futures):
            letter = futures[future]
            result = future.result()
            if result is not None:
                manifest['modules'][letter] = result
                manifest['modules'] = dict(sorted(manifest['modules'].items()))
                manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')


if __name__ == '__main__':
    main()
