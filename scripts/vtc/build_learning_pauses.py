"""Place learner-controlled reflection breaks in existing, verified silent tails.

No audio, video duration or learner history is changed. The browser holds the
frame and resumes after four seconds (five for English repetition), unless the
learner chooses to remain paused. Build-only dependency: imageio-ffmpeg.
"""
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'elearning_native/vtc'
ENGLISH = {
    0: 'My name is Lina. I’m your driver.',
    2: 'How many passengers are there?',
    4: 'a quarter to eight',
    6: 'In front of',
    8: 'two pieces of luggage',
    10: 'Please fasten your seat belt',
    12: 'It takes about thirty minutes',
    14: 'The fare is sixty euros, including tax',
    16: 'I’m sorry for the delay',
    18: 'The payment has gone through',
    20: 'I need some help',
    22: 'There is a museum near the hotel.',
}
EXTRA = {
    'B': {10: 'Prenez le temps de distinguer TVA collectée et TVA déductible.',
          16: 'Reprenez les trois étapes : marge, taux de marge, seuil de rentabilité.'},
    'D': {6: 'Repérez quel nom est repris par le pronom.',
          10: 'Distinguez les nuances : au moins, au plus, certains et tous.',
          16: 'Reprenez mentalement un exemple d’accord avant de poursuivre.'},
}


def silent_intervals(path):
    import imageio_ffmpeg
    result = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-nostdin', '-hide_banner',
        '-i', str(path), '-vn', '-af', 'silencedetect=noise=-35dB:d=0.15',
        '-f', 'null', '-'], capture_output=True, text=True, check=True)
    intervals, start = [], None
    for line in result.stderr.splitlines():
        found = re.search(r'silence_start: ([\d.]+)', line)
        if found:
            start = float(found[1])
        found = re.search(r'silence_end: ([\d.]+)', line)
        if found and start is not None:
            intervals.append((start, float(found[1])))
            start = None
    return intervals


def make_module(letter, video):
    source = OUT / 'assets' / video['src']
    silences = silent_intervals(source)
    paragraphs = video['transcript'].split('\n\n')
    pauses = []
    for index, chapter in enumerate(video['chapters'][:-1]):
        message = None
        seconds = 4
        kind = 'reflect'
        if index % 2 == 1:
            message = 'Prenez un instant pour retenir : ' + chapter['title'] + '.'
        if index in EXTRA.get(letter, {}):
            message = EXTRA[letter][index]
        if letter == 'E' and index in ENGLISH:
            phrase = ENGLISH[index]
            assert phrase in paragraphs[index], (index, phrase)
            message = 'À vous de répéter : « ' + phrase + ' »'
            seconds = 5
            kind = 'repeat'
        if not message:
            continue
        boundary = chapter['end_seconds']
        quiet = next(((a, b) for a, b in silences if a < boundary < b), None)
        assert quiet is not None, (letter, index, boundary)
        # Start within the already-silent final tail, not inside the last word.
        # Leave as much room as possible before the next visual cut. The player
        # also watches video frames to avoid a coarse timeupdate-only trigger.
        start, end = quiet
        assert boundary-start > .15, (letter, index, quiet)
        at = start + min(.12, (boundary-start)/3)
        pauses.append(dict(id=f'{letter.lower()}-{index:02}', at_seconds=round(at, 3),
            duration_seconds=seconds, message=message, kind=kind, scene_index=index,
            chapter_ref=chapter['ref'], chapter_end_seconds=boundary,
            verified_silence={'start': start, 'end': end}))
    return dict(source_video=video['src'], source_file_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        transcript_sha256=hashlib.sha256(video['transcript'].encode()).hexdigest(), pauses=pauses)


def main():
    videos = json.loads((OUT/'video_manifest_v4.json').read_text())
    videos['E'] = json.loads((OUT/'video_english_bilingual_v7.json').read_text())
    modules = {}
    for letter, video in videos.items():
        modules[letter] = make_module(letter, video)
        print(letter, len(modules[letter]['pauses']), 'reviewed pauses', flush=True)
    path = OUT / 'video_learning_pauses_v9.json'
    path.write_text(json.dumps(dict(revision=9, modules=modules), ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
