"""Offline safeguards for a preview that must not replace learner media."""
import json
import re
import wave

import pytest

from scripts.vtc import render_voice_preview as preview
from scripts.vtc import render_quality_videos_v11 as renderer
from scripts.vtc.readable_captions_v11 import make_cues


def boundaries(text, step=.48):
    return [dict(text=t,offset=round((.12+i*step)*1e7),duration=round(.3*1e7))
            for i,t in enumerate(text.split()) if renderer.canonical(t)]


def test_preview_preparation_keeps_lesson_identity_and_existing_collection():
    live = renderer.OUT/'video_quality_v11.json'
    before = live.read_bytes()
    row, signature = preview.prepare()
    assert row['ref'] == 'D.02' and len(row['scenes']) == 4
    assert row['previous_src'] == 'media/vtc/v11/lesson-d-02.mp4'
    assert len(signature) == 64
    assert preview.PREFIX not in before.decode()
    assert live.read_bytes() == before
    assert preview.plan(row)['status'] == 'prepared_not_generated'
    for scene in row['scenes']:
        text = renderer.scene_text(scene)
        assert all(text.count(p['anchor_text']) == 1 for p in scene['points'])


def test_default_command_never_generates_audio(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError('Preparation must never call the speech service')
    monkeypatch.setattr(preview, 'generate', forbidden)
    monkeypatch.setattr(preview.sys, 'argv', ['render_voice_preview.py'])
    preview.main()
    result = json.loads(capsys.readouterr().out)
    assert result['replaces_live_video'] is False
    assert result['playback_rate'] == 1


def test_preview_captions_fit_at_actual_one_x_and_retain_all_words():
    row, _ = preview.prepare()
    for scene in row['scenes']:
        source = renderer.scene_text(scene)
        words = boundaries(source)
        finish = (words[-1]['offset']+words[-1]['duration'])/1e7+1
        cues = make_cues(source, words, finish, playback_rate=1)
        assert re.sub(r'\s+', '', ''.join(c['text'] for c in cues)) == re.sub(r'\s+', '', source)
        for cue in cues:
            seconds = cue['end']-cue['start']
            assert seconds >= 1-.001
            assert len(cue['text'].replace('\n',' '))/seconds <= 20
            assert len(cue['text'].splitlines()) <= 2
            assert max(map(len,cue['text'].splitlines())) <= 44
        reveals = renderer.anchored_reveals(scene, words, 0)
        assert all(0 <= r['at_seconds'] < finish for r in reveals)


def test_wrong_spoken_words_cannot_be_subtitled_as_the_course():
    with pytest.raises(ValueError, match='authored text'):
        make_cues('Le treize juin.', boundaries('Le douze juin.'), 3, playback_rate=1)


def test_scene_assembly_does_not_stretch_the_voice(tmp_path):
    source = 'La course part demain.'
    wav = tmp_path/'take.wav'
    # Offline PCM fixture tests timing only; this is not a speech quality test.
    original = b'\x10\x00' * (renderer.SAMPLE_RATE*3)
    with wave.open(str(wav), 'wb') as f:
        f.setparams((1,2,renderer.SAMPLE_RATE,0,'NONE','not compressed'))
        f.writeframes(original)
    piece = dict(lang='fr',text=source,audio=wav,words=boundaries(source,.65),trim_start=0,seconds=3)
    scene = dict(segments=[dict(lang='fr',text=source)])
    result = renderer.assemble_scene(scene,[piece],tmp_path,0,playback_rate=1)
    with wave.open(str(result['path']),'rb') as f:
        assembled = f.readframes(f.getnframes())
    assert assembled[:len(original)] == original
    assert assembled[len(original):].strip(b'\0') == b''
    assert result['seconds'] >= 3+renderer.TAIL_SILENCE
    assert result['segments'][0]['end_seconds'] == 3
