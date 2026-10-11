"""Quality safeguards that failed in the independent 104-video audit."""
import json
import re

import pytest

from scripts.vtc import readable_captions_v11 as captions
from scripts.vtc import render_quality_videos_v11 as renderer


def words(text, starts, duration=.2):
    return [dict(text=word,offset=round(start*1e7),duration=round(duration*1e7))
            for word,start in zip(text.split(),starts)]


def assert_readable(cues, source):
    assert re.sub(r'\s+','',''.join(c['text'] for c in cues)) == re.sub(r'\s+','',source)
    for cue in cues:
        seconds = (cue['end']-cue['start'])/.85
        assert seconds >= 1.-.001
        assert len(cue['text'].replace('\n',' '))/seconds <= 20
        assert len(cue['text'].splitlines()) <= 2
        assert max(map(len,cue['text'].splitlines())) <= 44


def test_short_sentence_is_grouped_with_following_phrase_not_flashed():
    source = 'Oui. Le client confirme son prochain trajet.'
    cues = captions.make_cues(source,words(source,[.1,.35,.65,1.,1.45,1.85,2.3]),3.4)
    assert_readable(cues,source)
    assert not any(c['text'] == 'Oui.' for c in cues)


def test_punctuation_and_apostrophes_survive_reflow():
    source = "L’heure d’arrivée est-elle confirmée ? Oui, exactement."
    timing = words(source,[.1,.8,1.5,2.3,3.,3.4,4.2])
    assert_readable(captions.make_cues(source,timing,5.3),source)


def test_unreadable_source_is_rejected_instead_of_faking_word_timing():
    source = 'Anticonstitutionnellement'
    with pytest.raises(ValueError,match='reading break'):
        captions.make_cues(source,words(source,[.05],duration=.1),.3)


def test_mismatched_speech_is_rejected_before_captioning():
    with pytest.raises(ValueError,match='authored text'):
        captions.make_cues('Douze points sur vingt.',words('Décembre deux mille vingt.',[.1,.5,1.,1.5]),3)


def test_104_sources_keep_complete_historical_chapter_identities():
    rows = renderer.quality_rows()
    assert len(rows) == 104
    assert len({r['ref'] for r in rows}) == 104
    assert sum(len(r['scenes']) for r in rows) == 624
    assert sum(len(s['points']) for r in rows for s in r['scenes']) == 1554
    lessons = json.loads((renderer.OUT/'lesson_videos_v10.json').read_text())['lessons']
    modules = json.loads((renderer.OUT/'video_pacing_v9.json').read_text())['modules']
    for row in rows:
        previous = (lessons if '.' in row['ref'] else modules)[row['ref']]
        assert row['previous_src'] == previous['src']
        assert row['previous_chapters'] == previous['chapters']
        assert row['previous_duration_seconds'] == previous['duration_seconds']
        assert len(row['scenes']) == len(previous['chapters'])
        if '.' in row['ref']:
            assert row['source_sha256'] == previous['source_sha256']
        for scene in row['scenes']:
            text = renderer.scene_text(scene)
            assert all(text.count(p['anchor_text'])==1 for p in scene['points'])


def test_legacy_homophone_cards_reveal_at_new_spoken_explanations():
    row = next(r for r in renderer.quality_rows() if r['ref']=='D')
    scene = row['scenes'][17]
    assert [p['anchor_text'] for p in scene['points']] == [
        'A sans accent se remplace','Sont avec un T final se remplace','Pour une terminaison en é accent aigu']
    assert all(p['anchor_text'] in renderer.scene_text(scene) for p in scene['points'])


def test_exact_anchor_skips_the_same_words_in_a_title():
    source = 'Suivre les pronoms. Les pronoms évitent une répétition.'
    scene = dict(segments=[dict(lang='fr',text=source)],points=[dict(anchor_text='Les pronoms')])
    timing = words(source,[.1,.5,1.,1.6,2.,2.5,3.,3.5])
    reveal = renderer.anchored_reveals(scene,timing,10)[0]
    assert reveal['at_seconds'] == 11.6
    assert reveal['word_text'] == 'Les'


def test_all_1554_cards_fit_without_clipping():
    for row in renderer.quality_rows():
        for scene in row['scenes']:
            for point,box in zip(scene['points'],renderer.card_boxes(scene)):
                layout = renderer.point_layout(point,box)
                assert layout['body_size'] >= 20
                assert layout['body_y']+len(layout['body_lines'])*layout['body_size']*1.3 < box[1]+box[3]


def test_publication_uses_separate_immutable_asset_namespace():
    assert renderer.ASSETS == renderer.OUT/'assets/media/vtc/v11'
    assert renderer.WORK.name != 'vtc-lessons-v10'
