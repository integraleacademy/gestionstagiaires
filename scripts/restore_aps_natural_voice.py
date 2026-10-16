"""Restore the original Henri take; retime pictures and captions together.

No TTS call, pitch shift or audio time stretching is used. Source v8 contains
the same complete narration as v9. Its PCM samples are kept in order, with the
existing reflection pauses projected onto the natural timeline. Old media stay
immutable. Run on a preparation branch, then review before publication.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import wave

ROOT = Path(__file__).resolve().parents[1] / 'elearning_native/aps62'
ASSETS = ROOT / 'assets'
REVISION = '20261013-aps-natural-voice'
OUTPUT = ASSETS / 'media/aps62/v13'


def run(*args):
    return subprocess.check_output(args, stderr=subprocess.PIPE)


def probe(path):
    return json.loads(run('ffprobe', '-v', 'error', '-show_streams',
                          '-show_format', '-of', 'json', str(path)))


def stamp(seconds):
    ms = round(seconds * 1000)
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f'{h:02}:{m:02}:{s:02}.{ms:03}'


def retime_vtt(text, scale):
    def replace(match):
        h, m, s, ms = map(int, match.groups())
        return stamp((h*3600 + m*60 + s + ms/1000) * scale)
    return re.sub(r'(\d{2}):(\d{2}):(\d{2})\.(\d{3})', replace, text)


def restore(sid, source, previous):
    assert source['transcript'] == previous['transcript']
    assert source['voice'] == previous['voice'] == 'fr-FR-HenriNeural'
    pacing = previous['pacing']
    scale = pacing['tempo']
    assert scale == .87 and source['narration_seconds'] == pacing['source_narration_seconds']
    target = previous['duration_seconds'] * scale
    assert target >= 300
    with tempfile.TemporaryDirectory(prefix=sid+'-natural-') as work:
        folder = Path(work)
        raw, restored = folder/'original.wav', folder/'natural.wav'
        run('ffmpeg','-nostdin','-v','error','-y','-i',str(ASSETS/source['src']),
            '-t',str(source['narration_seconds']),'-vn','-ac','1','-ar','48000',
            '-c:a','pcm_s16le',str(raw))
        with wave.open(str(raw),'rb') as f:
            params = f.getparams()
            pcm = f.readframes(f.getnframes())
        frame_bytes, rate = params.nchannels * params.sampwidth, params.framerate
        pieces, retained, cursor, prior_pauses = [], [], 0, 0.0
        for pause in pacing['pauses']:
            source_cut = (pause['start_seconds'] - prior_pauses) * scale
            cut = round(source_cut * rate) * frame_bytes
            assert cursor <= cut <= len(pcm)
            retained.append(pcm[cursor:cut])
            pieces.append(pcm[cursor:cut])
            pieces.append(b'\0' * (round(pause['added_seconds'] * scale * rate) * frame_bytes))
            cursor = cut
            prior_pauses += pause['added_seconds']
        retained.append(pcm[cursor:])
        pieces.append(pcm[cursor:])
        assert b''.join(retained) == pcm, 'Original voice samples were changed'
        result_pcm = b''.join(pieces)
        wanted = round(target * rate) * frame_bytes
        # Only the final post-narration hold absorbs rounding; never trim speech.
        assert wanted >= len(result_pcm), (sid, (wanted-len(result_pcm))/rate/frame_bytes)
        result_pcm += b'\0' * (wanted-len(result_pcm))
        with wave.open(str(restored),'wb') as f:
            f.setparams(params)
            f.writeframes(result_pcm)
        output = OUTPUT / f'{sid}.mp4'
        run('ffmpeg','-nostdin','-v','error','-y','-itsscale',str(scale),
            '-i',str(ASSETS/previous['src']),'-i',str(restored),
            '-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-b:a','128k',
            '-t',str(target),'-movflags','+faststart',str(output))
        info = probe(output)
        actual = float(info['format']['duration'])
        assert abs(actual-target) < .15, (sid, actual, target)
        def picture_hash(path):
            return run('ffmpeg','-nostdin','-v','error','-i',str(path),
                       '-map','0:v:0','-c:v','copy','-f','hash','-hash','sha256','-').decode().strip()
        source_pictures = picture_hash(ASSETS/previous['src'])
        assert picture_hash(output) == source_pictures, 'Picture stream changed'
        run('ffmpeg','-nostdin','-v','error','-xerror','-i',str(output),'-f','null','-')
        captions = OUTPUT / f'{sid}.vtt'
        captions.write_text(retime_vtt((ASSETS/previous['captions']).read_text(),scale))
        chapters = [{**c,'start_seconds':round(c['start_seconds']*scale,3),
                     'end_seconds':round(c['end_seconds']*scale,3)} for c in previous['chapters']]
        chapters[-1]['end_seconds'] = actual
        result = dict(src=f'media/aps62/v13/{sid}.mp4',captions=f'media/aps62/v13/{sid}.vtt',
            duration_seconds=actual, narration_seconds=round(len(result_pcm)/frame_bytes/rate,6),
            chapters=chapters, render_revision=REVISION, voice=source['voice'], rate=source['rate'],
            previous_src=previous['src'],previous_duration_seconds=previous['duration_seconds'],
            timeline_scale=scale,source_src=source['src'],
            original_voice_samples_preserved=True,voice_time_stretching=False,
            source_pcm_sha256=hashlib.sha256(pcm).hexdigest(),
            picture_stream_hash=source_pictures,
            video_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
            captions_sha256=hashlib.sha256(captions.read_bytes()).hexdigest(),
            transcript_sha256=hashlib.sha256(previous['transcript'].encode()).hexdigest())
        print(sid,round(actual,2),'seconds; original samples retained; full decode OK',flush=True)
        return sid,result


def main():
    OUTPUT.mkdir(parents=True,exist_ok=True)
    source=json.loads((ROOT/'video_manifest_v8.json').read_text())
    previous=json.loads((ROOT/'video_manifest_v9.json').read_text())
    selected=set(filter(None,os.environ.get('APS_NATURAL_ONLY','').split(',')))
    rows=[(sid,source[sid],old) for sid,old in previous.items() if not selected or sid in selected]
    with ThreadPoolExecutor(max_workers=int(os.environ.get('APS_NATURAL_WORKERS','2'))) as pool:
        results=dict(pool.map(lambda args:restore(*args),rows))
    if selected:
        destination=Path(os.environ.get('APS_NATURAL_REPORT','/tmp/aps-natural-sample.json'))
    else:
        assert len(results)==62
        destination=ROOT/'natural_voice_v13.json'
    destination.write_text(json.dumps({'revision':REVISION,'videos':results},ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':
    main()
