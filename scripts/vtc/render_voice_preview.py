"""Prepare or render the D.02 voice comparison; never publish a course revision.

The default command is entirely local. --render sends only the fixed, reviewed
D.02 narration to the Microsoft speech service already used by the VTC renderer.
It must not be run until the requested external narration transfer is authorized.
Generated media use a separate namespace and do not replace learner media.
"""
import argparse
import asyncio
from copy import deepcopy
from importlib import metadata
import json
import os
from pathlib import Path
import re
import ssl
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.vtc import render_quality_videos_v11 as base

SOURCE = Path(__file__).with_name('voice_preview_d02.json')
VOICE = {'fr': 'fr-FR-HenriNeural'}
# Keep -2% as the slowest delivery; thought groups may be slightly livelier.
RATE = {'fr': '-2%'}
PREFIX = 'media/vtc/voice-preview-d02-henri'
OUTPUT = base.OUT/'assets'/PREFIX
WORK = Path(os.environ.get('VTC_VOICE_PREVIEW_WORK', '/tmp/vtc-voice-preview-d02-henri'))


def delivery_settings(segment):
    direction = segment.get('delivery', {})
    rate = direction.get('rate', RATE[segment['lang']])
    pitch = direction.get('pitch', '+0Hz')
    gap = direction.get('gap_after_seconds', .12)
    if (not re.fullmatch(r'[+-]\d+%', rate) or not -2 <= int(rate[:-1]) <= 4
            or not re.fullmatch(r'[+-]\d+Hz', pitch) or not -2 <= int(pitch[:-2]) <= 2
            or not isinstance(gap, (int, float)) or not 0 <= gap <= .35):
        raise ValueError('Henri delivery must stay subtle and must not slow down further')
    return dict(rate=rate, pitch=pitch, gap_after_seconds=gap)


def prepare():
    row = json.loads(SOURCE.read_text())
    original = next(r for r in base.read_lessons(base.AUTHORING/'D.json') if r['ref']=='D.02')
    prior = json.loads((base.OUT/'video_quality_v11.json').read_text())['lessons']['D.02']
    if (row.get('ref') != 'D.02' or row.get('preview_only') is not True
            or row.get('source_sha256') != original['source_sha256']
            or len(row.get('scenes', [])) != len(prior['chapters'])
            or any(s.get('lang') != 'fr' for scene in row['scenes'] for s in scene['segments'])):
        raise ValueError('The preview must match the reviewed French D.02 lesson')
    row.update(previous_src=prior['src'], previous_duration_seconds=prior['duration_seconds'],
               previous_chapters=deepcopy(prior['chapters']), previous_media_sha256=prior['media_sha256'])
    base.validate_lesson(row)
    for scene in row['scenes']:
        for segment in scene['segments']:
            delivery_settings(segment)
    signature = base.digest(base.json_bytes(dict(row=row, voice=VOICE, rate=RATE, playback_rate=1))
                            + base.code_signature().encode() + Path(__file__).read_bytes())
    return row, signature


def plan(row):
    return dict(status='prepared_not_generated', lesson=row['ref'], title=row['title'],
                scenes=len(row['scenes']), words=sum(len(base.scene_text(s).split()) for s in row['scenes']),
                voice=VOICE['fr'], synthesis_rate=RATE['fr'], playback_rate=1,
                delivery_mode='authored-thought-groups',
                takes=sum(len(scene['segments']) for scene in row['scenes']),
                synthesis_rate_range=['-2%', '+4%'],
                speech_service='Microsoft speech', transfer='Reviewed narration only; no learner data',
                output_prefix=PREFIX, replaces_live_video=False)


async def generate(row, signature):
    # TLS validation stays enabled and supports the runtime's configured CA.
    import edge_tts.communicate as communication
    from edge_tts.constants import SEC_MS_GEC_VERSION
    cafile = ssl.get_default_verify_paths().cafile
    if cafile:
        communication._SSL_CTX.load_verify_locations(cafile=cafile)
    speech = WORK/'speech'
    for folder in (WORK, speech, OUTPUT):
        folder.mkdir(parents=True, exist_ok=True)
    slots, locks = asyncio.Semaphore(2), {}
    async def take(segment):
        direction = delivery_settings(segment)
        piece = await base.synthesize(segment, slots, locks, voice_map=VOICE,
            rate_map={segment['lang']: direction['rate']},
            pitch_map={segment['lang']: direction['pitch']}, cache_dir=speech)
        return dict(piece, gap_after_seconds=direction['gap_after_seconds'])
    spoken = await asyncio.gather(*(asyncio.gather(*(
        take(segment)
        for segment in scene['segments'])) for scene in row['scenes']))
    result = await asyncio.to_thread(base.render, row, spoken, signature,
        output_dir=OUTPUT, work_dir=WORK, media_prefix=PREFIX, voice_map=VOICE,
        rate_map=RATE, revision='voice-preview-d02-henri-rhythm-2', playback_rate=1)
    result.update(preview_only=True, voice_time_stretching=False,
                  delivery_mode='authored-thought-groups', rate_mode='per-segment',
                  synthesis_rate_range=['-2%', '+4%'],
                  preview_source_sha256=base.file_sha(SOURCE))
    package_source = metadata.distribution('edge-tts').read_text('direct_url.json')
    package_source = json.loads(package_source) if package_source else {}
    result['speech_client'] = dict(version=metadata.version('edge-tts'),
        protocol_version=SEC_MS_GEC_VERSION.split('-')[0],
        source_revision=package_source.get('vcs_info', {}).get('commit_id'),
        requirements_sha256=base.file_sha(Path(__file__).with_name('voice_preview_requirements.txt')))
    # Decode the whole result, not just its metadata, before making it reviewable.
    base.ffmpeg(['-xerror', '-i', OUTPUT/'lesson-d-02.mp4', '-f', 'null', '-'])
    base.atomic_json(OUTPUT/'preview.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--render', action='store_true', help='Generate the authorized narration and preview media')
    args = parser.parse_args()
    row, signature = prepare()
    print(json.dumps(plan(row), ensure_ascii=False, indent=2))
    if args.render:
        result = asyncio.run(generate(row, signature))
        print('PREVIEW READY:', result['src'], result['duration_seconds'])


if __name__ == '__main__':
    main()
