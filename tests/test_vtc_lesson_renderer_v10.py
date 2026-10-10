"""Checks for the authored words, visual timing and silence used by lesson video builds."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
import wave

import pytest

from scripts.vtc import render_lesson_videos_v10 as renderer


def sample_scene():
    return dict(title='Un exemple concret',label='Comprendre',kind='method',
                segments=[dict(lang='fr',text='Une réservation prépare le trajet. Le conducteur confirme les détails.')],
                points=[dict(label='Réserver',text='Préparer le trajet avant le départ.',anchor_text='Une réservation'),
                        dict(label='Confirmer',text='Vérifier les détails du trajet.',anchor_text='Le conducteur')],
                pause=dict(seconds=4,message='Retenez les deux étapes.'))


def boundaries(text):
    return [dict(text=word,offset=round((.1+i*.35)*1e7),duration=round(.25*1e7))
            for i,word in enumerate(text.split())]


def test_visual_reveals_follow_exact_spoken_anchor_not_equal_spacing():
    scene = sample_scene()
    words = boundaries(renderer.scene_text(scene))
    reveals = renderer.anchored_reveals(scene,words,12)
    assert [point['at_seconds'] for point in reveals] == [12.1,13.85]
    assert [point['word_text'] for point in reveals] == ['Une','Le']
    assert all(point['timing_method'] == 'original-synthesis-word' for point in reveals)


def test_bad_narration_boundaries_are_rejected_instead_of_guessed():
    with pytest.raises(AssertionError):
        renderer.anchored_reveals(sample_scene(),boundaries('Un autre texte sans rapport.'),0)


@pytest.mark.parametrize('count',[1,2,3])
@pytest.mark.parametrize('kind',['concept','method'])
def test_card_layouts_are_separate_and_inside_safe_area(count,kind):
    scene = sample_scene()
    scene['kind'] = kind
    scene['points'] = [deepcopy(scene['points'][0]) for _ in range(count)]
    boxes = renderer.card_boxes(scene)
    for box in boxes:
        x,y,w,h = box
        assert 40 <= x < x+w <= 1240
        assert 225 <= y < y+h <= 567
        layout = renderer.point_layout(scene['points'][0],box)
        assert layout['body_y']+len(layout['body_lines'])*layout['body_size']*1.3 < y+h
    for i,a in enumerate(boxes):
        for b in boxes[i+1:]:
            assert a[0]+a[2] <= b[0] or a[1]+a[3] <= b[1]


def test_layout_refuses_to_truncate_overfull_text():
    point = dict(label='Titre',text='Un texte vraiment trop long pour cet écran. '*70)
    with pytest.raises(ValueError,match='without truncation'):
        renderer.point_layout(point,(432,232,800,102))


def test_language_joins_keep_word_timing_and_add_silent_pause_tail(tmp_path):
    scene = sample_scene()
    scene['segments'] = [dict(lang='fr',text='Le client dit : '),
                         dict(lang='en',text='Good morning. '),
                         dict(lang='fr',text='Puis il confirme.')]
    pieces = []
    for segment in scene['segments']:
        words = boundaries(segment['text'])
        seconds = (words[-1]['offset']+words[-1]['duration'])/1e7+.18
        pieces.append(dict(segment,audio=Path('fake.mp3'),words=words,trim_start=0,seconds=seconds))
    def fake_decode(args):
        duration = float(args[args.index('-af')+1].split('duration=')[1].split(',')[0])
        with wave.open(str(args[-1]),'wb') as stream:
            stream.setparams((1,2,48000,0,'NONE','not compressed'))
            stream.writeframes(b'\x20\x01'*round(duration*48000))
    with patch.object(renderer,'ffmpeg',fake_decode):
        result = renderer.assemble_scene(scene,pieces,tmp_path,0)
    assert result['seconds']-result['silence_start'] >= .85-1e-6
    with wave.open(str(result['path']),'rb') as stream:
        assert stream.getnframes()/stream.getframerate() == result['seconds']
        stream.setpos(round(result['silence_start']*48000))
        assert not any(stream.readframes(stream.getnframes()-stream.tell()))
    all_words = result['words']
    second_voice_start = all_words[len(pieces[0]['words'])]['offset']/1e7
    assert second_voice_start == pytest.approx(pieces[0]['seconds']+.12+.1)
    assert result['speech_end'] < result['silence_start']
    assert ''.join(renderer.canonical(cue['text']) for cue in result['cues']) == renderer.canonical(renderer.scene_text(scene))


def test_reads_agreed_module_authoring_directory(tmp_path):
    for module in ('A','B'):
        (tmp_path/(module+'.json')).write_text(json.dumps(dict(revision=10,module=module,
            lessons=[dict(ref=module+'.01')])) )
    assert [row['ref'] for row in renderer.read_lessons(tmp_path)] == ['A.01','B.01']
