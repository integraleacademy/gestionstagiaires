#!/usr/bin/env python3
"""Extract the supplied 2020 annales, including the printed yellow answer markers.

The source PDF is private input: pass its path explicitly; it is never copied.
Editorial corrections are maintained separately from faithfully extracted answers.
Requires pdfplumber and pypdf. Run from the repository root.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

import pdfplumber

SECTIONS = [
    ('A', 'Réglementation du T3P', 2, 3, 45, 15),
    ('B', 'Gestion', 4, 5, 45, 18),
    ('C', 'Sécurité routière', 6, 9, 30, 20),
    ('D', 'Français', 10, 11, 30, 10),
    ('E', 'Anglais', 12, 14, 30, 20),
    ('F', 'Développement commercial et gestion spécifiques VTC', 15, 16, 30, 16),
    ('G', 'Réglementation nationale spécifique VTC', 17, 17, 20, 8),
]


def extract(pdf_path):
    result = {'id': 'annales-2020', 'title': 'Annales VTC · 28 janvier 2020',
              'year': 2020, 'source_filename': pdf_path.name,
              'source_sha256': hashlib.sha256(pdf_path.read_bytes()).hexdigest(),
              'sections': [], 'excluded_sections': [
                  {'title': 'Réglementation nationale et gestion spécifiques taxi', 'module': 'G(T)', 'pages': [18, 19], 'question_count': 15, 'reason': 'Spécialité taxi, hors parcours VTC'},
                  {'title': 'Sécurité routière et réglementation VMDTR', 'module': 'F(M)', 'pages': [20, 21], 'question_count': 16, 'reason': 'Spécialité moto, hors parcours VTC'},
                  {'title': 'Prise en charge du passager et développement commercial VMDTR', 'module': 'G(M)', 'pages': [22], 'question_count': 8, 'reason': 'Spécialité moto, hors parcours VTC'}]}
    with pdfplumber.open(pdf_path) as pdf:
        # This exact image is the yellow "à cocher" marker in the page-2 legend.
        yellow = hashlib.sha256(pdf.pages[1].images[0]['stream'].get_data()).digest()
        for module, title, first, last, minutes, expected in SECTIONS:
            section = {'id': f'annales-2020-{module.lower()}', 'module': module,
                       'title': title, 'minutes': minutes, 'questions': []}
            question, mode, pending_marker = None, None, False
            for page_number in range(first, last + 1):
                page = pdf.pages[page_number - 1]
                words = page.extract_words(x_tolerance=2, y_tolerance=2)
                rows = []
                for word in sorted(words, key=lambda w: (round(w['top'], 1), w['x0'])):
                    if word['top'] < (130 if page_number == first else 40) or word['top'] > 800:
                        continue
                    row = next((r for r in reversed(rows[-3:]) if abs(r[0]['top'] - word['top']) < 2), None)
                    if row is None:
                        rows.append([word])
                    else:
                        row.append(word)
                for row in rows:
                    row.sort(key=lambda w: w['x0'])
                    initial = row[0]
                    text = ' '.join(w['text'] for w in row)
                    if initial['text'].isdigit() and 16 < initial['x0'] < 18:
                        number = int(initial['text'])
                        question = {'id': f'annales-2020-{module.lower()}-{number:02}',
                                    'number': number, 'page': page_number,
                                    'prompt': ' '.join(w['text'] for w in row[1:]),
                                    'original_kind': 'qcm', 'options': [], 'answers': [],
                                    'correction_origin': 'source'}
                        section['questions'].append(question)
                        mode = 'prompt'
                    elif question is None:
                        continue
                    elif text.startswith('(0 point'):
                        question['points'] = int(re.search(r'/\s*(\d+)', text).group(1))
                        mode = None
                    elif text.startswith('Indication/Right answer'):
                        question['original_kind'] = 'qrc'
                        question['original_answer'] = text.split(':', 1)[1].strip()
                        mode = 'original_answer'
                    elif initial['text'] in 'ABCD' and len(initial['text']) == 1 and initial['x0'] < 16:
                        option_id = initial['text'].lower()
                        question['options'].append({'id': option_id, 'text': ' '.join(w['text'] for w in row[1:])})
                        markers = [im for im in page.images if im['x0'] < 30 and im['width'] < 15 and abs(im['top'] - initial['top'] + 4.1) < 2]
                        assert len(markers) == 1 or (len(row) == 1 and initial['top'] > 780), (page_number, question['id'], option_id, markers)
                        pending_marker = not markers
                        if markers and hashlib.sha256(markers[0]['stream'].get_data()).digest() == yellow:
                            question['answers'].append(option_id)
                        mode = 'option'
                    elif mode == 'option':
                        question['options'][-1]['text'] += ' ' + text
                        if pending_marker:
                            markers = [im for im in page.images if im['x0'] < 30 and im['width'] < 15 and abs(im['top'] - initial['top']) < 3]
                            assert len(markers) == 1, (page_number, question['id'], 'continued marker')
                            if hashlib.sha256(markers[0]['stream'].get_data()).digest() == yellow:
                                question['answers'].append(question['options'][-1]['id'])
                            pending_marker = False
                    elif mode in ('prompt', 'original_answer'):
                        question[mode] = (question[mode] + ' ' + text).strip()
            assert len(section['questions']) == expected, (module, len(section['questions']))
            for q in section['questions']:
                for option in q['options']:
                    option['text'] = option['text'].strip()
                if q['original_kind'] == 'qcm':
                    assert q['answers'], q['id']
                    q['kind'] = 'multiple' if len(q['answers']) > 1 else 'single'
            result['sections'].append(section)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdf', type=Path)
    parser.add_argument('--raw-output', type=Path)
    args = parser.parse_args()
    result = extract(args.pdf)
    if args.raw_output:
        args.raw_output.parent.mkdir(parents=True, exist_ok=True)
        args.raw_output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
