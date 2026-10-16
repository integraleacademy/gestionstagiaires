"""Author VTC video chapters from existing course explanations and reviewed methods.

The source paragraphs are retained verbatim. Every lesson has its own three-step
visual; narration is continuous course content, with no pause or writing tasks.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'elearning_native/vtc'
BASE = '20261006-vtc-v3-105h'


def methods():
    result = {}
    for line in Path(__file__).with_name('visual_methods.txt').read_text().splitlines():
        if not line.strip():
            continue
        ref, *parts = line.split('|')
        assert len(parts) == 6, ref
        result[ref] = [dict(title=parts[i], text=parts[i+1]) for i in range(0, 6, 2)]
    assert len(result) == 96
    return result


def build():
    steps = methods()
    result = {}
    for letter in 'ABCDEFGH':
        course = json.loads((OUT / f'courses/academy-vtc-{letter.lower()}/{BASE}.json').read_text())
        scenes = []
        for section in course['sections'][:12]:
            lesson = section['activities'][0]['vtc']
            paras = [p['text'] for p in lesson['paragraphs'] if p['kind'] == 'paragraph']
            ref = lesson['ref']
            # Split each lesson into a concept and its practical application.
            # These are authored explanatory paragraphs, not quiz prompts.
            for i, kind in enumerate(('concept', 'method')):
                title = lesson['title'].strip()
                ending = ' ' if title.endswith(('.', '?', '!')) else '. '
                text = (title + ending if i == 0 else '') + paras[i]
                scenes.append(dict(ref=ref, title=lesson['title'], kind=kind,
                    label='Comprendre' if i == 0 else 'Dans la pratique',
                    text=text, points=lesson['cards'] if i == 0 else steps[ref],
                    image=lesson['image']))
        result[letter] = dict(title=course['title'], scenes=scenes,
            transcript='\n\n'.join(s['text'] for s in scenes))
        assert len(result[letter]['transcript'].split()) > 1200
    (OUT / 'video_scripts_v4.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print({k: len(v['transcript'].split()) for k, v in result.items()})
    return result


if __name__ == '__main__':
    build()
