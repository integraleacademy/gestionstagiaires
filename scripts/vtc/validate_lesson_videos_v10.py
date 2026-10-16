"""Validate delivered lesson media, exact-word reveals, captions and quiet pauses.

Optionally create a contact sheet per module from the encoded videos. These
captures are build QA only, never production content or learner data.
"""
import argparse
import json
from pathlib import Path
import sys

import av
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.vtc import render_lesson_videos_v10 as renderer
from scripts.vtc.render_paced_videos import read_vtt


def inspect_audio(path, pauses):
    samples = [[] for pause in pauses]
    frames = 0
    with av.open(str(path)) as container:
        audio = container.streams.audio[0]
        assert audio.codec_context.name == 'aac'
        assert audio.codec_context.sample_rate == 48000
        for frame in container.decode(audio):
            values = frame.to_ndarray()
            assert np.isfinite(values).all()
            frames += 1
            start = float(frame.pts*frame.time_base)
            times = start+np.arange(frame.samples)/frame.sample_rate
            for i,pause in enumerate(pauses):
                selected = (times >= pause['at_seconds']-.03) & (times <= pause['at_seconds']+.10)
                if selected.any():
                    samples[i].extend(values[:,selected].ravel().tolist())
    assert frames
    peaks = []
    for pause,values in zip(pauses,samples):
        assert len(values) >= 5000, (path,pause['id'],'missing decoded samples')
        peak = max(abs(value) for value in values)
        assert peak < .002, (path,pause['id'],'pause intersects audible audio',peak)
        peaks.append(dict(id=pause['id'],peak=peak))
    return peaks


def inspect_one(row, video, captures=False):
    ref = row['ref']
    renderer.validate_lesson(row)
    assert video['content_sha256'] == renderer.signature_for(row), ref
    assert video['source_sha256'] == row['source_sha256']
    assert video['default_playback_rate'] == .85
    assert video['allowed_playback_rates'] == [.85,1]
    for key,digest_key in [('src','media_sha256'),('poster','poster_sha256'),('captions','captions_sha256')]:
        assert renderer.file_sha(renderer.OUT/'assets'/video[key]) == video[digest_key], (ref,key)
    path = renderer.OUT/'assets'/video['src']
    with av.open(str(path)) as container:
        track = container.streams.video[0]
        assert track.codec_context.name == 'h264'
        assert (track.width,track.height) == (1280,720)
        assert float(track.average_rate) == 20
        assert abs(container.duration/1e6-video['duration_seconds']) < .002
        assert len(container.streams.audio) == 1
    cues = read_vtt(renderer.OUT/'assets'/video['captions'])
    transcript = '\n\n'.join(renderer.scene_text(scene) for scene in row['scenes'])
    assert transcript == video['transcript']
    assert ''.join(''.join(c['text'].split()) for c in cues) == ''.join(transcript.split()), ref
    assert 0 <= cues[0]['start'] < cues[-1]['end'] < video['duration_seconds']
    assert all(a['end'] <= b['start']+.001 for a,b in zip(cues,cues[1:])), ref
    assert len(video['scenes']) == len(row['scenes']) == len(video['chapters'])
    expected_pauses = [scene['pause'] for scene in row['scenes'] if scene.get('pause')]
    assert len(expected_pauses) == len(video['learning_pauses'])
    assert len({p['id'] for p in video['learning_pauses']}) == len(expected_pauses)
    pause_index = 0
    capture_files = []
    for i,(scene,timing,chapter) in enumerate(zip(row['scenes'],video['scenes'],video['chapters'])):
        assert timing['language_segments'] == scene['segments']
        assert timing['start_seconds'] == chapter['start_seconds']
        assert timing['end_seconds'] == chapter['end_seconds']
        assert len(timing['reveals']) == len(scene['points'])
        assert [r['anchor_text'] for r in timing['reveals']] == [p['anchor_text'] for p in scene['points']]
        literal = renderer.scene_text(scene)
        normalized = renderer.canonical(literal)
        cursor = 0
        for point in scene['points']:
            anchor = point['anchor_text']
            position = normalized.find(renderer.canonical(anchor),cursor)
            # A normalization collision must never move a card to an earlier
            # phrase that differs only in case, accents or punctuation.
            assert position == len(renderer.canonical(literal[:literal.index(anchor)]))
            cursor = position+len(renderer.canonical(anchor))
        assert all(r['timing_method'] == 'original-synthesis-word' for r in timing['reveals'])
        assert all(timing['start_seconds'] <= r['at_seconds'] < timing['speech_end_seconds'] for r in timing['reveals'])
        assert [r['at_seconds'] for r in timing['reveals']] == sorted(r['at_seconds'] for r in timing['reveals'])
        quiet = timing['verified_silence']
        assert quiet['end']-quiet['start'] >= .849
        assert quiet['start'] > timing['speech_end_seconds']
        if scene.get('pause'):
            pause = video['learning_pauses'][pause_index]
            pause_index += 1
            assert quiet['start']+.15 <= pause['at_seconds'] < quiet['end']-.5
            assert pause['duration_seconds'] == scene['pause']['seconds']
            assert pause['message'] == scene['pause']['message']
        if captures:
            folder = renderer.WORK/'qa'/ref
            folder.mkdir(parents=True,exist_ok=True)
            frame_path = folder/f'{i:02}.jpg'
            at = min(timing['speech_end_seconds']-.1,timing['reveals'][-1]['at_seconds']+1)
            renderer.ffmpeg(['-ss',str(at),'-i',path,'-frames:v','1',frame_path])
            capture_files.append(str(frame_path))
    return dict(ref=ref,duration_seconds=video['duration_seconds'],bytes=path.stat().st_size,
                scenes=len(video['scenes']),cards=sum(len(s['reveals']) for s in video['scenes']),
                caption_cues=len(cues),pauses=len(video['learning_pauses']),
                pause_audio=inspect_audio(path,video['learning_pauses']),captures=capture_files)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--only')
    parser.add_argument('--captures',action='store_true')
    args = parser.parse_args()
    rows = renderer.read_lessons(renderer.AUTHORING)
    manifest = json.loads((renderer.OUT/'lesson_videos_v10.json').read_text())
    if args.only:
        selected = set(args.only.split(','))
        rows = [r for r in rows if r['ref'] in selected or r['ref'][0] in selected]
    reports = []
    for row in rows:
        reports.append(inspect_one(row,manifest['lessons'][row['ref']],args.captures))
        print('CHECKED',row['ref'],flush=True)
    if args.captures:
        for module in sorted({r['ref'][0] for r in reports}):
            images = [r for r in reports if r['ref'][0]==module]
            columns = max(len(r['captures']) for r in images)
            contact = Image.new('RGB',(320*columns,180*len(images)),'white')
            for y,row in enumerate(images):
                for x,path in enumerate(row['captures']):
                    with Image.open(path) as picture:
                        picture.thumbnail((320,180))
                        contact.paste(picture,(320*x,180*y))
            contact.save(renderer.WORK/'qa'/f'{module}-contact.jpg',quality=90)
    suffix = (args.only or 'all').replace(',','-')
    report = renderer.WORK/f'validation-{suffix}.json'
    renderer.atomic_json(report,dict(lessons=reports,total_seconds=sum(r['duration_seconds'] for r in reports),
                                   total_bytes=sum(r['bytes'] for r in reports)))
    print('VALID',len(reports),'lessons',report,flush=True)


if __name__ == '__main__':
    main()
