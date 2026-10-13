"""Render the D.02 comparison locally with Kokoro; never replace course media.

The first render downloads public model weights. Narration stays on this machine.
French words retain the full-phrase pronunciation from Misaki. Caption boundaries
come from the synthesis model's phoneme durations, not proportional text timing.
"""
import argparse
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.vtc import render_voice_preview as preview

base = preview.base
VOICE = 'ff_siwis'
SPEED = .90
PREFIX = 'media/vtc/voice-preview-d02-local'
OUTPUT = base.OUT/'assets'/PREFIX
WORK = Path(os.environ.get('VTC_LOCAL_VOICE_WORK', '/tmp/vtc-voice-preview-local-d02'))
TIMING_METHOD = 'kokoro-synthesis-phoneme-durations'


def word_boundaries(result, vocabulary):
    from kokoro import KPipeline
    from misaki.en import MToken
    # Keep precisely the characters accepted by KModel.forward.
    phonemes = ''.join(c for c in result.phonemes if c in vocabulary)
    words = [w for w in result.graphemes.split() if base.canonical(w)]
    groups = list(re.finditer(r'(\S+)(\s*)', phonemes))
    voiced = [g for g in groups if base.canonical(g[1])]
    if len(voiced) != len(words):
        raise ValueError('French word/phoneme mapping is ambiguous: '+result.graphemes)
    if len(result.pred_dur) != len(phonemes)+2:
        raise ValueError('Model phoneme duration count mismatch')
    source = iter(words)
    tokens = [MToken(text=next(source) if base.canonical(g[1]) else '',
                     tag='', whitespace=g[2], phonemes=g[1]) for g in groups]
    KPipeline.join_timestamps(tokens, result.pred_dur)
    boundaries = []
    for token in tokens:
        if not token.text:
            continue
        if token.start_ts is None or token.end_ts is None or token.end_ts <= token.start_ts:
            raise ValueError('Missing synthesis word timing')
        boundaries.append(dict(text=token.text, offset=round(token.start_ts*1e7),
                               duration=round((token.end_ts-token.start_ts)*1e7)))
    if ''.join(base.canonical(w['text']) for w in boundaries) != base.canonical(result.graphemes):
        raise ValueError('Narrated words differ from the authored text')
    return boundaries


def synthesize_local(pipeline, segment):
    import numpy as np
    import soundfile as sf
    text = segment['text']
    key = base.digest(base.json_bytes(dict(text=text, voice=VOICE, speed=SPEED,
                     code=base.file_sha(Path(__file__)))))
    folder = WORK/'speech'
    folder.mkdir(parents=True, exist_ok=True)
    path, metadata = folder/(key+'.wav'), folder/(key+'.json')
    if path.is_file() and metadata.is_file():
        saved = json.loads(metadata.read_text())
        if saved['audio_sha256'] != base.file_sha(path):
            raise ValueError('Local voice cache changed')
        return dict(segment, audio=path, trim_start=0,
                    seconds=base.duration(path), words=saved['words'])
    chunks, words, texts = [], [], []
    samples = 0
    for result in pipeline(text, voice=VOICE, speed=SPEED):
        boundaries = word_boundaries(result, pipeline.model.vocab)
        audio = result.audio.numpy()
        if not np.isfinite(audio).all() or len(audio) == 0:
            raise ValueError('Invalid synthesized audio')
        offset = samples/24000
        words.extend(dict(w, offset=w['offset']+round(offset*1e7)) for w in boundaries)
        chunks.append(audio)
        samples += len(audio)
        texts.append(result.graphemes)
        # Punctuation is synthesized in the same phrase; no extra inter-word gaps.
        print('SPEECH', len(audio)/24000, 'seconds', result.graphemes[:65], flush=True)
    if base.canonical(' '.join(texts)) != base.canonical(text):
        raise ValueError('The local pipeline omitted narration text')
    sf.write(path, np.concatenate(chunks), 24000, subtype='PCM_16')
    base.atomic_json(metadata, dict(words=words, audio_sha256=base.file_sha(path),
                                   timing_method=TIMING_METHOD))
    return dict(segment, audio=path, trim_start=0, seconds=samples/24000, words=words)


def generate(row, signature):
    os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
    os.environ['HF_HUB_DISABLE_XET'] = '1'
    import torch
    from kokoro import KPipeline
    torch.set_num_threads(4)
    torch.manual_seed(20261013)
    pipeline = KPipeline(lang_code='f', repo_id='hexgrad/Kokoro-82M', device='cpu')
    row['voice_direction'] = 'Voix française féminine ; phrases complètes ; aucun étirement audio.'
    OUTPUT.mkdir(parents=True, exist_ok=True)
    spoken = [[synthesize_local(pipeline, segment) for segment in scene['segments']]
              for scene in row['scenes']]
    result = base.render(row, spoken, signature, output_dir=OUTPUT, work_dir=WORK,
        media_prefix=PREFIX, voice_map={'fr':'Kokoro-82M/ff_siwis'}, rate_map={'fr':SPEED},
        revision='voice-preview-d02-local', playback_rate=1)
    for scene in result['scenes']:
        for reveal in scene['reveals']:
            reveal['timing_method'] = TIMING_METHOD
    result.update(preview_only=True, voice_time_stretching=False,
                  narration_transfer='none', caption_timing_method=TIMING_METHOD,
                  preview_source_sha256=base.file_sha(preview.SOURCE),
                  voice_attribution='Kokoro-82M (Apache-2.0), French ff_siwis / SIWIS')
    base.ffmpeg(['-xerror', '-i', OUTPUT/'lesson-d-02.mp4', '-f', 'null', '-'])
    base.atomic_json(OUTPUT/'preview.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--render', action='store_true')
    args = parser.parse_args()
    row, signature = preview.prepare()
    signature = base.digest((signature+base.file_sha(Path(__file__))).encode())
    print(json.dumps(dict(status='prepared_not_generated', voice=VOICE, synthesis_speed=SPEED,
                          narration_transfer='none', replaces_live_video=False), indent=2))
    if args.render:
        result = generate(row, signature)
        print('PREVIEW READY:', result['src'], result['duration_seconds'])


if __name__ == '__main__':
    main()
