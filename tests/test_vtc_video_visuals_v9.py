"""Keep every paced VTC visual tied to the narration actually heard.

These tests audit authored learning material, not learner completion state.
The French source is v4; English uses the pronunciation-reviewed v7 source.
"""
import hashlib
import json
from pathlib import Path

import pytest
from PIL import ImageFont

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'elearning_native/vtc'
VISUALS = json.loads((DATA / 'video_visuals_v9.json').read_text())
SCRIPTS = json.loads((DATA / 'video_scripts_v4.json').read_text())
ENGLISH = json.loads((DATA / 'video_english_bilingual_v7.json').read_text())


def narration(letter):
    if letter == 'E':
        return ENGLISH['transcript'].split('\n\n')
    return [scene['text'] for scene in SCRIPTS[letter]['scenes']]


def scene(letter, ref, kind):
    return next(item for item in VISUALS['modules'][letter]['scenes']
                if item['ref'] == ref and item['kind'] == kind)


def displayed(letter, ref, kind):
    return '\n'.join(point['text'] for point in scene(letter, ref, kind)['points'])


def lines(text, size, width):
    font = ImageFont.truetype(str(ROOT / 'scripts/academy_videos/assets/Manrope-600.ttf'), size)
    rows, row = [], ''
    for word in text.split():
        trial = (row + ' ' + word).strip()
        if row and font.getlength(trial) > width:
            rows.append(row)
            row = word
        else:
            row = trial
    if row:
        rows.append(row)
    return rows


def test_all_eight_videos_and_192_scenes_are_reviewed():
    assert VISUALS['revision'] == 9
    assert set(VISUALS['modules']) == set('ABCDEFGH')
    assert sum(len(row['scenes']) for row in VISUALS['modules'].values()) == 192


@pytest.mark.parametrize('letter', 'ABCDEFGH')
def test_visual_revision_tracks_exact_narration_and_chapter_order(letter):
    texts = narration(letter)
    actual = VISUALS['modules'][letter]['scenes']
    original = SCRIPTS[letter]['scenes']
    assert len(actual) == len(original) == len(texts) == 24
    assert VISUALS['source_transcript_sha256'][letter] == hashlib.sha256(
        '\n\n'.join(texts).encode('utf-8')).hexdigest()
    assert [(s['ref'], s['kind'], s['title']) for s in actual] == [
        (s['ref'], s['kind'], s['title']) for s in original]
    for text, visual in zip(texts, actual):
        assert len(visual['points']) == 3
        positions = []
        for point in visual['points']:
            label = 'label' if visual['kind'] == 'concept' else 'title'
            assert set(point) == {label, 'text', 'anchor_text'}
            assert point[label].strip() and point['text'].strip()
            anchor = point['anchor_text']
            # A unique verbatim anchor prevents ambiguous or inferred timing.
            assert anchor.strip() and text.count(anchor) == 1, (visual['ref'], anchor)
            positions.append(text.index(anchor))
        assert positions == sorted(set(positions)), (letter, visual['ref'])


@pytest.mark.parametrize('letter', 'ABCDEFGH')
def test_every_card_fits_the_existing_video_dimensions(letter):
    for visual in VISUALS['modules'][letter]['scenes']:
        concept = visual['kind'] == 'concept'
        for point in visual['points']:
            title = point['label' if concept else 'title']
            assert len(lines(title, 21 if concept else 25, 694 if concept else 318)) <= (1 if concept else 2)
            assert len(lines(point['text'], 25 if concept else 26, 694 if concept else 318)) <= (2 if concept else 4)


def test_vat_formulas_and_commission_example_are_in_the_explained_scene():
    assert 'HT × (1 + taux)' in displayed('B', 'B.06', 'method')
    assert 'TTC ÷ (1 + taux)' in displayed('B', 'B.06', 'method')
    assert 'HT ×' not in displayed('B', 'B.06', 'concept')
    assert 'TVA des ventes' in displayed('B', 'B.06', 'concept')
    assert '60 ÷ 0,80 = 75 €' in displayed('F', 'F.03', 'method')
    assert 'contribution unitaire' not in displayed('B', 'B.09', 'method')
    assert 'Moment où le seuil est atteint' in displayed('B', 'B.09', 'method')


def test_english_cards_show_the_same_examples_as_the_reviewed_voice():
    assert 'My name is Lina. I’m your driver.' in displayed('E', 'E.01', 'concept')
    assert 'Are you Mr Green?' in displayed('E', 'E.01', 'method')
    assert 'Mr Brown' not in displayed('E', 'E.01', 'method')
    assert 'thirty minutes' in displayed('E', 'E.07', 'concept')
    assert 'twenty minutes' not in displayed('E', 'E.07', 'concept')
    assert 'I’ve lost my phone.' in displayed('E', 'E.11', 'concept')
    assert 'The payment hasn’t gone through.' in displayed('E', 'E.10', 'method')
    for number, word in [(13, 'Thirteen'), (30, 'thirty'), (14, 'Fourteen'),
                         (40, 'forty'), (15, 'Fifteen'), (50, 'fifty')]:
        assert f'{word} = {number}' in displayed('E', 'E.03', 'method')


def test_french_grammar_examples_match_the_spoken_example():
    assert 'Le chauffeur présente la facture au client, qui la vérifie' in displayed('D', 'D.04', 'method')
    assert '« qui » = le client ; « la » = la facture.' in displayed('D', 'D.04', 'method')
    assert 'Le client est arrivé tôt, pourtant la voiture était déjà prête' in displayed('D', 'D.05', 'method')
    assert 'Le client est arrivé tôt, donc la voiture était déjà prête' in displayed('D', 'D.05', 'method')
    assert 'Les clients arrivent.' in displayed('D', 'D.09', 'concept')
    assert '« a » peut se remplacer par « avait ».' in displayed('D', 'D.09', 'method')


def test_spoken_reference_numbers_are_visible_in_the_right_scene():
    numbers = displayed('A', 'A.08', 'method')
    assert all(number in numbers for number in ('17', '112', '15', 'SMS', '3919', '116 006'))
    assert any(p['title'] == 'Le 114' for p in scene('A', 'A.08', 'method')['points'])
    assert '10' in displayed('H', 'H.11', 'concept')
    assert 'Facturation : 2' in displayed('H', 'H.11', 'concept')
    assert 'Au moins 12 sur 20' in displayed('H', 'H.11', 'concept')
    assert '84 kW' in displayed('G', 'G.03', 'concept')
    assert '1,70 m' in displayed('G', 'G.03', 'concept')
