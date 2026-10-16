"""Render only the fictional v10 listening exercise; no real personal data sent."""
import asyncio
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import edge_tts
from scripts.aps62_v10.practical_cases import THREAT_CALL_AUDIO

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / 'elearning_native/aps62/assets/media/aps62/v10'
SETTINGS = json.loads((ROOT / 'scripts/academy_videos/reference_settings.json').read_text())
BASENAME = 'aps62-12-05-appel-exercice'


def timestamp(seconds):
    ms = round(seconds * 1000)
    return f'{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02}.{ms % 1000:03}'


async def render():
    ASSETS.mkdir(parents=True, exist_ok=True)
    spoken = 'Exercice fictif. ' + THREAT_CALL_AUDIO['narration_text']
    destination = ASSETS / (BASENAME + '.mp3')
    temporary = ASSETS / (BASENAME + '.partial.mp3')
    words = []
    with temporary.open('wb') as output:
        async for chunk in edge_tts.Communicate(
            spoken, voice=SETTINGS['voice'], rate=SETTINGS['rate'],
            pitch=SETTINGS['pitch'], volume=SETTINGS['volume'],
            boundary='WordBoundary',
        ).stream():
            if chunk['type'] == 'audio':
                output.write(chunk['data'])
            elif chunk['type'] == 'WordBoundary':
                words.append({'text': chunk['text'], 'start': chunk['offset'] / 1e7,
                              'end': (chunk['offset'] + chunk['duration']) / 1e7})
    if not words or temporary.stat().st_size < 5000:
        raise RuntimeError('Missing audio or caption timing')
    temporary.replace(destination)
    cues, group = [], []
    for word in words:
        if group and (len(' '.join(x['text'] for x in group)) + len(word['text']) > 78 or len(group) >= 13):
            cues.append({'start': group[0]['start'], 'end': group[-1]['end'],
                         'text': ' '.join(x['text'] for x in group)})
            group = []
        group.append(word)
    if group:
        cues.append({'start': group[0]['start'], 'end': group[-1]['end'],
                     'text': ' '.join(x['text'] for x in group)})
    (ASSETS / (BASENAME + '.vtt')).write_text(
        'WEBVTT\n\n' + '\n\n'.join(f"{timestamp(c['start'])} --> {timestamp(c['end'])}\n{c['text']}" for c in cues) + '\n')
    (ASSETS / (BASENAME + '.transcript.txt')).write_text(
        'Exercice fictif.\n' + THREAT_CALL_AUDIO['transcript'] + '\n')
    metadata = {
        'id': THREAT_CALL_AUDIO['id'], 'title': THREAT_CALL_AUDIO['title'],
        'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'provider': 'Microsoft Edge TTS through edge-tts',
        'voice': SETTINGS['voice'], 'rate': SETTINGS['rate'],
        'pitch': SETTINGS['pitch'], 'volume': SETTINGS['volume'],
        'fictional': True, 'spoken_text': spoken,
        'text_sha256': hashlib.sha256(spoken.encode()).hexdigest(),
        'audio_sha256': hashlib.sha256(destination.read_bytes()).hexdigest(),
        'caption_end_seconds': cues[-1]['end'],
        'source': 'scripts/aps62_v10/practical_cases.py:THREAT_CALL_AUDIO',
        'src': 'media/aps62/v10/' + BASENAME + '.mp3',
        'captions': 'media/aps62/v10/' + BASENAME + '.vtt',
        'transcript': THREAT_CALL_AUDIO['transcript'],
        'qa': {'word_boundaries_present': True, 'human_listening_confirmed': False},
    }
    ffprobe = shutil.which('ffprobe') or str(ROOT.parent / 'bin/ffprobe')
    ffmpeg = shutil.which('ffmpeg') or str(ROOT.parent / 'bin/ffmpeg')
    duration = float(subprocess.check_output([ffprobe, '-v', 'error', '-show_entries',
        'format=duration', '-of', 'default=nw=1:nk=1', str(destination)]))
    subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-xerror', '-i',
        str(destination), '-f', 'null', '-'], check=True, capture_output=True)
    if duration < cues[-1]['end']:
        raise RuntimeError('Audio ends before the final caption')
    metadata['duration_seconds'] = duration
    metadata['qa'].update({'complete_decode': True, 'final_caption_inside_audio': True})
    (ASSETS / (BASENAME + '.json')).write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'audio': str(destination), 'bytes': destination.stat().st_size,
                      'caption_end_seconds': cues[-1]['end']}, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(render())
