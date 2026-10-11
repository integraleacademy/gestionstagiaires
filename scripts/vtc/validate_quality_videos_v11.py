"""Validate delivered lesson media, exact-word reveals, captions and quiet pauses.

Optionally create a contact sheet per module from the encoded videos. These
captures are build QA only, never production content or learner data.
"""
import argparse
import concurrent.futures
import json
from pathlib import Path
import sys
import time

import av
import numpy as np
from PIL import Image, ImageFont

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.vtc import render_quality_videos_v11 as renderer
from scripts.vtc.render_paced_videos import read_vtt


def inspect_video(path, seconds):
    """Decode every encoded frame, checking continuity rather than metadata only."""
    times = []
    with av.open(str(path)) as container:
        for frame in container.decode(video=0):
            assert (frame.width,frame.height) == (1280,720)
            assert frame.pts is not None and frame.time_base is not None
            at = float(frame.pts*frame.time_base)
            if times:
                assert .0499 <= at-times[-1] <= .0501, (path,'broken frame timeline',at)
            times.append(at)
    assert times and abs(times[0]) < .001
    assert abs(times[-1]+.05-seconds) < .051, (path,times[-1],seconds)
    assert abs(len(times)-round(seconds*20)) <= 1
    return dict(decoded_frames=len(times),first_frame_seconds=times[0],last_frame_seconds=times[-1])


def inspect_audio(path, pauses, seconds):
    samples = [[] for pause in pauses]
    frames = 0
    peak_all, energy, count = 0., 0., 0
    first_start, last_end = None, None
    with av.open(str(path)) as container:
        audio = container.streams.audio[0]
        assert audio.codec_context.name == 'aac'
        assert audio.codec_context.sample_rate == 48000
        for frame in container.decode(audio):
            values = frame.to_ndarray()
            assert np.isfinite(values).all()
            peak_all = max(peak_all,float(np.max(np.abs(values))))
            energy += float(np.square(values,dtype=np.float64).sum())
            count += values.size
            frames += 1
            start = float(frame.pts*frame.time_base)
            if first_start is None:
                first_start = start
            if last_end is not None:
                assert abs(start-last_end) < .0001, (path,'broken audio timeline',start,last_end)
            last_end = start+frame.samples/frame.sample_rate
            times = start+np.arange(frame.samples)/frame.sample_rate
            for i,pause in enumerate(pauses):
                selected = (times >= pause['at_seconds']-.03) & (times <= pause['at_seconds']+.10)
                if selected.any():
                    samples[i].extend(values[:,selected].ravel().tolist())
    assert frames
    assert abs(first_start) < .001
    # The final AAC packet may contain codec padding beyond the video endpoint.
    assert seconds-.001 <= last_end <= seconds+1024/48000+.001, (path,last_end,seconds)
    peaks = []
    for pause,values in zip(pauses,samples):
        assert len(values) >= 5000, (path,pause['id'],'missing decoded samples')
        peak = max(abs(value) for value in values)
        assert peak < .002, (path,pause['id'],'pause intersects audible audio',peak)
        peaks.append(dict(id=pause['id'],peak=peak))
    assert peak_all < 1., (path,'clipped decoded audio',peak_all)
    return dict(pauses=peaks,peak=peak_all,rms=float(np.sqrt(energy/count)),samples=count,
                first_sample_seconds=first_start,last_sample_end_seconds=last_end)


def inspect_one(row, video, captures=False):
    ref = row['ref']
    renderer.validate_lesson(row)
    assert video['content_sha256'] == renderer.signature_for(row), ref
    assert video['source_sha256'] == row['source_sha256']
    assert video['default_playback_rate'] == .85
    assert video['allowed_playback_rates'] == [.85,1]
    assert video['render_revision'] == 11
    for key in ('previous_src','previous_duration_seconds','previous_chapters','previous_media_sha256'):
        assert video[key] == row[key], (ref,key)
    assert video['source_authoring_sha256'] == renderer.digest(renderer.json_bytes(row))
    for key,digest_key in [('src','media_sha256'),('poster','poster_sha256'),('captions','captions_sha256')]:
        assert renderer.file_sha(renderer.OUT/'assets'/video[key]) == video[digest_key], (ref,key)
    path = renderer.OUT/'assets'/video['src']
    assert renderer.audio_fingerprint(path) == video['audio_provenance']
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
    font = ImageFont.truetype(str(renderer.FONT),36)
    for cue in cues:
        assert len(cue['text'].splitlines()) <= 2
        assert max(map(len,cue['text'].splitlines())) <= 44
        assert (cue['end']-cue['start'])/.85 >= 1.-.001, (ref,cue)
        assert len(cue['text'].replace('\n',' '))*.85/(cue['end']-cue['start']) <= 20., (ref,cue)
        assert max(font.getlength(line) for line in cue['text'].splitlines()) <= 1170
    assert [dict(c,start=round(c['start'],3),end=round(c['end'],3)) for c in cues] == video['presentation']['captions']
    assert len(video['scenes']) == len(row['scenes']) == len(video['chapters'])
    expected_pauses = [scene['pause'] for scene in row['scenes'] if scene.get('pause')]
    assert len(expected_pauses) == len(video['learning_pauses'])
    assert len({p['id'] for p in video['learning_pauses']}) == len(expected_pauses)
    pause_index = 0
    capture_files = []
    for i,(scene,timing,chapter) in enumerate(zip(row['scenes'],video['scenes'],video['chapters'])):
        for point,box in zip(scene['points'],renderer.card_boxes(scene)):
            layout = renderer.point_layout(point,box)
            assert layout['body_y']+len(layout['body_lines'])*layout['body_size']*1.3 < box[1]+box[3]
        assert chapter['ref'] == row['previous_chapters'][i]['ref']
        assert video['presentation']['scenes'][i] == dict(start=timing['start_seconds'],end=timing['end_seconds'],
             title=timing['title'],points=[dict(label=p['label'],text=p['text'],at_seconds=t['at_seconds'])
                for p,t in zip(scene['points'],timing['reveals'])])
        assert timing['language_segments'] == scene['segments']
        assert timing['start_seconds'] == chapter['start_seconds']
        assert timing['end_seconds'] == chapter['end_seconds']
        assert len(timing['reveals']) == len(scene['points'])
        assert [r['anchor_text'] for r in timing['reveals']] == [p['anchor_text'] for p in scene['points']]
        literal = renderer.scene_text(scene)
        normalized = renderer.canonical(literal)
        words = json.loads((renderer.WORK/ref/f'words-{i:02}.json').read_text())
        assert ''.join(renderer.canonical(w['text']) for w in words) == normalized
        timeline = [word for word in words for character in renderer.canonical(word['text'])]
        cursor = 0
        for point,reveal in zip(scene['points'],timing['reveals']):
            anchor = point['anchor_text']
            position = len(renderer.canonical(literal[:literal.index(anchor)]))
            assert position >= cursor
            # Independently check the exact quotation against original provider
            # word boundaries, including homonymous words in a scene heading.
            expected = timing['start_seconds']+timeline[position]['offset']/1e7
            assert abs(reveal['at_seconds']-expected) <= .001, (ref,i,anchor,expected,reveal)
            assert reveal['word_text'] == timeline[position]['text']
            cursor = position+len(renderer.canonical(anchor))
        assert all(r['timing_method'] == 'original-synthesis-word' for r in timing['reveals'])
        assert all(timing['start_seconds'] <= r['at_seconds'] < timing['speech_end_seconds'] for r in timing['reveals'])
        assert [r['at_seconds'] for r in timing['reveals']] == sorted(r['at_seconds'] for r in timing['reveals'])
        quiet = timing['verified_silence']
        assert quiet['end']-quiet['start'] >= .849
        assert quiet['start'] > timing['speech_end_seconds']
        previous_end = timing['start_seconds']
        for segment in timing['spoken_segments']:
            assert previous_end <= segment['start_seconds'] <= segment['end_seconds'] <= quiet['start']+.001
            assert segment['lang'] in ('fr','en')
            previous_end = segment['end_seconds']
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
                media_sha256=video['media_sha256'],content_sha256=video['content_sha256'],
                minimum_caption_seconds=min((c['end']-c['start'])/.85 for c in cues),
                maximum_caption_cps=max(len(c['text'].replace('\n',' '))*.85/(c['end']-c['start']) for c in cues),
                video=inspect_video(path,video['duration_seconds']),
                audio=inspect_audio(path,video['learning_pauses'],video['duration_seconds']),captures=capture_files)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--only')
    parser.add_argument('--captures',action='store_true')
    parser.add_argument('--manifest',type=Path,default=renderer.OUT/'video_quality_v11.json')
    parser.add_argument('--follow',action='store_true',help='Validate each current render as it becomes ready, for at most 30 minutes.')
    parser.add_argument('--jobs',type=int,default=2)
    args = parser.parse_args()
    rows = renderer.quality_rows()
    if args.only:
        selected = set(args.only.split(','))
        rows = [r for r in rows if r['ref'] in selected or r['ref'][0] in selected]
    selected_refs = {row['ref'] for row in rows}
    reports = {}
    deadline = time.monotonic()+1800
    assert 1 <= args.jobs <= 4
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        while True:
            # Reviewers may correct a source during the build. Refresh pending
            # rows as well as completed rows, without retaining old signatures.
            rows = [row for row in renderer.quality_rows() if row['ref'] in selected_refs]
            signatures = {row['ref']:renderer.signature_for(row) for row in rows}
            reports = {ref:report for ref,report in reports.items()
                       if report['content_sha256'] == signatures[ref]}
            pending = [row for row in rows if row['ref'] not in reports]
            if not pending:
                break
            manifest = json.loads(args.manifest.read_text())
            tasks = {}
            for row in pending:
                section = 'lessons' if '.' in row['ref'] else 'modules'
                video = manifest.get(section,{}).get(row['ref'])
                if args.follow and (not video or video.get('content_sha256') != signatures[row['ref']]):
                    continue
                assert video, 'Missing media: '+row['ref']
                tasks[pool.submit(inspect_one,row,video,args.captures)] = row['ref']
            for task in concurrent.futures.as_completed(tasks):
                report = task.result()
                reports[report['ref']] = report
                renderer.atomic_json(renderer.WORK/'validation-progress.json',dict(lessons=list(reports.values())))
                print('CHECKED',report['ref'],flush=True)
            if not tasks:
                assert args.follow and time.monotonic()<deadline, 'Timed out waiting for current media'
                time.sleep(2)
    reports = sorted(reports.values(),key=lambda report:report['ref'])
    if args.captures:
        for module in sorted({r['ref'][0] for r in reports}):
            images = [r for r in reports if r['ref'][0]==module]
            columns = 6 if any('.' not in r['ref'] for r in images) else 5
            count = sum(len(r['captures']) for r in images)
            contact = Image.new('RGB',(320*columns,180*((count+columns-1)//columns)),'white')
            cell = 0
            for y,row in enumerate(images):
                for x,path in enumerate(row['captures']):
                    with Image.open(path) as picture:
                        picture.thumbnail((320,180))
                        contact.paste(picture,(320*(cell%columns),180*(cell//columns)))
                        cell += 1
            contact.save(renderer.WORK/'qa'/f'{module}-contact.jpg',quality=90)
    suffix = (args.only or 'all').replace(',','-')
    report = renderer.WORK/f'validation-{suffix}.json'
    renderer.atomic_json(report,dict(lessons=reports,total_seconds=sum(r['duration_seconds'] for r in reports),
                                   total_bytes=sum(r['bytes'] for r in reports)))
    print('VALID',len(reports),'lessons',report,flush=True)


if __name__ == '__main__':
    main()
