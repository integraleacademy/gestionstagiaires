"""Offline safeguards for a preview that must not replace learner media."""
import asyncio
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
    assert preview.VOICE == {'fr': 'fr-FR-HenriNeural'}
    assert preview.RATE == {'fr': '-2%'}
    assert preview.PREFIX == 'media/vtc/voice-preview-d02-henri'
    for scene in row['scenes']:
        text = renderer.scene_text(scene)
        assert not re.search(r'[.!?][A-Za-zÀ-ÖØ-öø-ÿ]', text), 'A take boundary must not merge sentences'
        assert all(text.count(p['anchor_text']) == 1 for p in scene['points'])
        for segment in scene['segments']:
            assert int(preview.delivery_settings(segment)['rate'][:-1]) >= -2


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


def test_directed_takes_reach_synthesizer_and_do_not_reuse_wrong_prosody(tmp_path, monkeypatch):
    import edge_tts
    calls = []

    class Speech:
        def __init__(self, text, **settings):
            calls.append(settings)
        async def stream(self):
            yield dict(type='audio', data=b'timing-test-only')
            yield dict(type='WordBoundary', text='Bonjour', offset=1_000_000, duration=5_000_000)

    monkeypatch.setattr(edge_tts, 'Communicate', Speech)
    monkeypatch.setattr(renderer, 'duration', lambda _: 1.)

    async def run():
        slots, locks = asyncio.Semaphore(1), {}
        segment = dict(lang='fr', text='Bonjour.')
        results = []
        for rate, pitch in [('-2%', '+0Hz'), ('+4%', '+1Hz'), ('+4%', '+2Hz'), ('+4%', '+1Hz')]:
            results.append(await renderer.synthesize(segment, slots, locks,
                voice_map=preview.VOICE, rate_map={'fr': rate}, pitch_map={'fr': pitch}, cache_dir=tmp_path))
        return results

    results = asyncio.run(run())
    assert len(calls) == 3
    assert [(c['rate'], c['pitch']) for c in calls] == [('-2%', '+0Hz'), ('+4%', '+1Hz'), ('+4%', '+2Hz')]
    assert len({str(r['audio']) for r in results}) == 3
    assert results[1]['audio'] == results[3]['audio']
    assert all(c['voice'] == 'fr-FR-HenriNeural' and c['boundary'] == 'WordBoundary' for c in calls)


def test_authored_join_keeps_audio_samples_and_word_timing(tmp_path):
    texts = ['La course part demain. ', 'Le client vient ici.']
    original = b'\x10\x00' * (renderer.SAMPLE_RATE*3)
    wav = tmp_path/'take.wav'
    with wave.open(str(wav), 'wb') as f:
        f.setparams((1,2,renderer.SAMPLE_RATE,0,'NONE','not compressed'))
        f.writeframes(original)
    pieces = [dict(lang='fr', text=t, audio=wav, words=boundaries(t,.65),
                   trim_start=0, seconds=3, gap_after_seconds=.07) for t in texts]
    scene = dict(segments=[dict(lang='fr', text=t) for t in texts])
    result = renderer.assemble_scene(scene, pieces, tmp_path, 0, playback_rate=1)
    with wave.open(str(result['path']), 'rb') as f:
        assembled = f.readframes(f.getnframes())
    gap = b'\0' * (round(.07*renderer.SAMPLE_RATE)*2)
    expected = original+gap+original
    assert assembled[:len(expected)] == expected
    assert assembled[len(expected):].strip(b'\0') == b''
    assert result['segments'][1]['start_seconds'] == pytest.approx(3.07)
    assert result['words'][4]['offset'] == 31_900_000
