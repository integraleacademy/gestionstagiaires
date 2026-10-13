"""Generate the authorised complete VTC voice collection, keeping D.02 intact.

Only public course narration is sent to the existing Microsoft speech service.
French takes use Henri within the approved -2%..+4%, -1Hz..+2Hz envelope;
English teaching examples keep Ryan. No audio is time-stretched. The complete
manifest is written only after every new media file passes decoded-media QA.
"""
import argparse
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import ssl
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.vtc import render_quality_videos_v11 as base
from scripts.vtc import validate_quality_videos_v11 as qa

WORK = Path(os.environ.get('VTC_HENRI_WORK', '/tmp/vtc-henri-all'))
PREFIX = 'media/vtc/v15'
OUTPUT = base.OUT/'assets'/PREFIX
MANIFEST = base.OUT/'video_voice_v15.json'
OVERRIDES = Path(__file__).with_name('voice_delivery_overrides_v15.json')
VOICE = {'fr': 'fr-FR-HenriNeural', 'en': 'en-GB-RyanNeural'}
RATE = {'fr': '-2%', 'en': '-6%'}
APPROVED_SHA = 'a9e6aae708388e899694043f90576e5b748b26b7be8a8673b63a3cdb1bed06fc'


def thought_groups(text):
    """Lossless sentence groups: keep questions with answers and short leads.

    Boundaries are sentence ends, never word-count cuts inside sentences. The
    original whitespace is retained because visual anchors use literal text.
    """
    if not text.strip():
        return [text]
    sentences, cursor = [], 0
    for end in re.finditer(r'[.!?][»”"\']?(?:\s+|$)', text):
        sentences.append(text[cursor:end.end()])
        cursor = end.end()
    if cursor < len(text):
        sentences.append(text[cursor:])
    groups, current = [], ''
    for sentence in sentences:
        count = len(current.split())
        next_count = len(sentence.split())
        question = re.search(r'\?[»”"\']?\s*$', current)
        transition = re.match(r'(?:En revanche|Autre distinction|Enfin|Retenez|Prenons|Par exemple)\b', sentence)
        if current and not question and count >= 18 and (count+next_count > 48 or (transition and count >= 26)):
            groups.append(current)
            current = ''
        current += sentence
    if current:
        # Avoid an isolated short conclusion when the preceding group can carry it.
        if groups and len(current.split()) < 10 and len((groups[-1]+current).split()) <= 58:
            groups[-1] += current
        else:
            groups.append(current)
    assert ''.join(groups) == text and all(g.strip() for g in groups)
    return groups


def direction(text, *, first, last, kind):
    lower = text.casefold()
    if re.search(r'\b(attention|ne confondez|ne signifie pas|ne suffit pas|interdit|ne remplace pas)\b', lower):
        rate, pitch, intention = '-2%', '+0Hz', 'souligner une vigilance sans dramatiser'
    elif '?' in text:
        rate, pitch, intention = '+0%', '+1Hz', 'lier la question à son explication'
    elif re.search(r'\b(par exemple|prenons|imaginez|supposons|un exemple)\b', lower):
        rate, pitch, intention = '+3%', '+1Hz', 'raconter un exemple concret'
    elif re.search(r'\b(retenez|à retenir|en résumé|donc|avant de valider)\b', lower) and last:
        rate, pitch, intention = '-2%', '-1Hz', 'poser la conclusion'
    elif first:
        rate, pitch, intention = '+2%', '+1Hz', 'ouvrir une explication avec présence'
    elif last:
        rate, pitch, intention = '-2%', '+0Hz', 'terminer une idée posément'
    else:
        rate, pitch, intention = '+0%', '+0Hz', 'enchaîner une explication complète'
    return dict(rate=rate, pitch=pitch, gap_after_seconds=0 if last else (.12 if '?' in text else .08), intention=intention)


def prepare_rows():
    prior = json.loads((base.OUT/'video_quality_v11.json').read_text())
    rows = base.quality_rows()
    overrides = json.loads(OVERRIDES.read_text()) if OVERRIDES.exists() else {}
    for row in rows:
        if row['ref'] == 'D.02':
            continue
        before = prior['lessons' if '.' in row['ref'] else 'modules'][row['ref']]
        row.update(previous_src=before['src'], previous_duration_seconds=before['duration_seconds'],
                   previous_chapters=deepcopy(before['chapters']), previous_media_sha256=before['media_sha256'])
        for scene_index,scene in enumerate(row['scenes']):
            original = base.scene_text(scene)
            segments = []
            for segment in scene['segments']:
                if segment['lang'] == 'en':
                    segments.append(dict(segment, delivery=dict(rate='-6%', pitch='+0Hz',
                        gap_after_seconds=.12, intention='conserver le modèle anglais natif')))
                    continue
                groups = thought_groups(segment['text'])
                for i, text in enumerate(groups):
                    delivery = direction(text, first=i==0, last=i==len(groups)-1, kind=scene['kind'])
                    # A language switch still keeps the existing gentle join.
                    if i == len(groups)-1 and segment is not scene['segments'][-1]:
                        delivery['gap_after_seconds'] = .12
                    segments.append(dict(lang='fr', text=text, delivery=delivery))
            scene['segments'] = segments
            assert base.scene_text(scene) == original
            for edit in overrides.get(row['ref'],{}).get(str(scene_index),[]):
                matches=[s for s in segments if edit['text'] in s['text'] and s['lang']=='fr']
                assert len(matches)==1,(row['ref'],scene_index,edit['text'])
                segment=matches[0]
                speech=segment['delivery'].get('speech_text',segment['text']).replace(edit['text'],edit['speech_text'])
                assert base.canonical(speech)==base.canonical(segment['text'])
                segment['delivery'].update(speech_text=speech,rate='-2%')
    return rows


def signature(row):
    return base.digest(base.signature_for(row).encode()+Path(__file__).read_bytes())


def approved_take():
    row = json.loads((base.OUT/'video_voice_v14.json').read_text())['lessons']['D.02']
    assert row['media_sha256'] == APPROVED_SHA
    for key, checksum in [('src','media_sha256'),('poster','poster_sha256'),('captions','captions_sha256')]:
        assert base.file_sha(base.OUT/'assets'/row[key]) == row[checksum]
    return row


def reading_breaks(segment):
    """Shorter complete clauses for a dense passage; never cut inside a word."""
    if segment['delivery'].get('speech_text'):
        return [segment]  # Keep the explicitly directed punctuation intact.
    parts, current, cursor = [], '', 0
    for match in re.finditer(r'[.!?;:,][»”"\']?(?:\s+|$)', segment['text']):
        current += segment['text'][cursor:match.end()]
        cursor = match.end()
        if len(current.split()) >= 16 and not re.search(r'\?[»”"\']?\s*$',current):
            parts.append(current);current=''
    current += segment['text'][cursor:]
    if current:
        if parts and len(current.split()) < 7:
            parts[-1] += current
        else:
            parts.append(current)
    assert ''.join(parts)==segment['text']
    return [dict(segment,text=text,delivery=dict(segment['delivery'],rate='-2%',
                gap_after_seconds=.16 if i<len(parts)-1 else segment['delivery']['gap_after_seconds']))
            for i,text in enumerate(parts)]


async def generate(rows):
    import edge_tts.communicate as communication
    cafile = ssl.get_default_verify_paths().cafile
    if cafile:
        communication._SSL_CTX.load_verify_locations(cafile=cafile)
    for folder in (WORK, WORK/'speech', OUTPUT):
        folder.mkdir(parents=True, exist_ok=True)
    base.atomic_json(WORK/'delivery-plan.json', rows)
    manifest = dict(revision=15, scope='all-vtc-videos', approved_on='2026-10-13',
                    reference_media_sha256=APPROVED_SHA, lessons={'D.02': approved_take()}, modules={})
    speech_slots, render_slots, row_slots = asyncio.Semaphore(4), asyncio.Semaphore(2), asyncio.Semaphore(6)
    locks, failures, reports = {}, [], {}

    async def take(segment):
        delivery = segment['delivery']
        speech_text=delivery.get('speech_text',segment['text'])
        assert base.canonical(speech_text)==base.canonical(segment['text'])
        piece = await base.synthesize(dict(segment,text=speech_text), speech_slots, locks, voice_map=VOICE,
            rate_map={segment['lang']:delivery['rate']}, pitch_map={segment['lang']:delivery['pitch']},
            cache_dir=WORK/'speech')
        return dict(piece, text=segment['text'],gap_after_seconds=delivery['gap_after_seconds']) if piece else None

    async def one(row):
        if row['ref'] == 'D.02':
            print('PRESERVED D.02 approved bytes', flush=True)
            return
        async with row_slots:
            try:
                actual_row = deepcopy(row)
                adjustments = []
                sig = signature(row)
                cached = WORK/row['ref']/'result.json'
                result = json.loads(cached.read_text()) if cached.exists() else None
                if result and (result.get('content_sha256') != sig or any(
                        not (base.OUT/'assets'/result[k]).is_file() or base.file_sha(base.OUT/'assets'/result[k]) != result[h]
                        for k,h in [('src','media_sha256'),('poster','poster_sha256'),('captions','captions_sha256')])):
                    result = None
                if not result:
                    spoken = []
                    folder = WORK/row['ref']
                    folder.mkdir(parents=True,exist_ok=True)
                    for i,scene in enumerate(actual_row['scenes']):
                        for attempt in range(3):
                            pieces = await asyncio.gather(*(take(s) for s in scene['segments']))
                            try:
                                # Real word timings determine whether the dense
                                # passage needs a little more breathing space.
                                async with render_slots:
                                    await asyncio.to_thread(base.assemble_scene,scene,pieces,folder,i,playback_rate=1)
                                spoken.append(pieces)
                                break
                            except ValueError as exc:
                                if 'natural reading break' not in str(exc) or attempt==2:
                                    raise
                                segments=[]
                                for segment in scene['segments']:
                                    if segment['lang']=='en':
                                        segments.append(segment)
                                    elif attempt==0:
                                        segments.append(dict(segment,delivery=dict(segment['delivery'],rate='-2%')))
                                    else:
                                        segments.extend(reading_breaks(segment))
                                scene['segments']=segments
                                adjustments.append(dict(scene=i,action='neutral-rate' if attempt==0 else 'clause-breaths'))
                    print('SPEECH', row['ref'], flush=True)
                    languages = {s['lang'] for scene in row['scenes'] for s in scene['segments']}
                    async with render_slots:
                        result = await asyncio.to_thread(base.render, actual_row, spoken, sig,
                            output_dir=OUTPUT, work_dir=WORK, media_prefix=PREFIX,
                            voice_map={k:VOICE[k] for k in sorted(languages)},
                            rate_map={k:RATE[k] for k in sorted(languages)}, revision=15, playback_rate=1)
                    result['delivery_adjustments']=adjustments
                else:
                    for scene,timing in zip(actual_row['scenes'],result['scenes']):
                        scene['segments']=timing['language_segments']
                result.update(preview_only=False, voice_time_stretching=False, delivery_mode='sentence-thought-groups',
                              rate_mode='per-segment', synthesis_rate_range=['-2%','+4%'])
                base.atomic_json(cached, result)
                async with render_slots:
                    report = await asyncio.to_thread(qa.inspect_one, actual_row, result,
                        expected_signature=sig, playback_rate=1, revision=15, work_dir=WORK)
                reports[row['ref']] = report
                section = 'lessons' if '.' in row['ref'] else 'modules'
                manifest[section][row['ref']] = result
                base.atomic_json(WORK/'manifest.partial.json', manifest)
                base.atomic_json(WORK/'validation-progress.json', reports)
                print('CHECKED', row['ref'], len(reports)+1, '/104', flush=True)
            except Exception as exc:
                failures.append((row['ref'],repr(exc)))
                print('FAILED', row['ref'], repr(exc), flush=True)
    await asyncio.gather(*(one(row) for row in rows))
    base.atomic_json(WORK/'failures.json', failures)
    if failures:
        raise RuntimeError(f'{len(failures)} videos need attention: {failures}')
    expected = {f'{m}.{i:02}' for m in 'ABCDEFGH' for i in range(1,13)}
    if set(manifest['lessons']) == expected and set(manifest['modules']) == set('ABCDEFGH'):
        for row in rows:
            if row['ref'] != 'D.02':
                key = 'lessons' if '.' in row['ref'] else 'modules'
                assert manifest[key][row['ref']]['content_sha256'] == signature(row)
        manifest['lessons'] = dict(sorted(manifest['lessons'].items()))
        manifest['modules'] = dict(sorted(manifest['modules'].items()))
        base.atomic_json(MANIFEST, manifest)
        print('COMPLETE 104/104; full manifest ready', flush=True)
    else:
        print('SUBSET CHECKED; no collection manifest published', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--render', action='store_true')
    parser.add_argument('--only', help='Comma-separated exact references for diagnostics')
    args = parser.parse_args()
    rows = prepare_rows()
    if args.only:
        selected = set(args.only.split(','))
        rows = [r for r in rows if r['ref'] in selected]
    for row in rows:
        if row['ref'] != 'D.02':
            base.validate_lesson(row)
    print('PREPARED',len(rows),'videos',sum(len(s['segments']) for r in rows for s in r['scenes']),'takes',flush=True)
    if args.render:
        asyncio.run(generate(rows))


if __name__ == '__main__':
    main()
