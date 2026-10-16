"""Pacing checks cover meaningful timing, preservation and generated frames."""
import array
import json
import re
import wave

import pytest

from scripts.aps62_v10.video_content import courses
from scripts.aps62_v11.video_pacing import (
    TEMPO, make_plan, make_paced_cues, caption_metrics,
    insert_pcm_pauses, visual_frames,
)


def synthetic_boundaries(text):
    tokens = list(re.finditer(r"[^\W_]+(?:['’\-][^\W_]+)*", text))
    now, result = .1, []
    for index, token in enumerate(tokens):
        length = .20 + len(token.group()) * .021
        result.append(dict(text=token.group(), offset=round(now*1e7), duration=round(length*1e7)))
        next_position = tokens[index+1].start() if index+1<len(tokens) else len(text)
        punctuation = text[token.end():next_position]
        gap = .8 if re.search(r'[.!?]',punctuation) else .30 if re.search(r'[:;]',punctuation) else .025
        now += length + gap
    return result, now + .3


@pytest.mark.parametrize('sid', sorted(courses()))
def test_every_authored_video_preserves_words_and_adds_meaningful_pauses(sid):
    row = courses()[sid]
    boundaries, duration = synthetic_boundaries(row['transcript'])
    plan = make_plan(row, boundaries, duration)
    assert plan['tempo'] == .87
    assert len(plan['words']) == len(boundaries)
    reconstructed = ''.join(w['text'] for w in plan['words'])
    assert re.sub(r'\s+', '', reconstructed) == re.sub(r'\s+', '', row['transcript'])
    assert all(left['end'] <= right['start'] for left,right in zip(plan['words'],plan['words'][1:]))
    for pause in plan['insertions']:
        index = pause['before_word']
        assert plan['words'][index]['start'] - plan['words'][index-1]['end'] >= pause['target_gap_seconds'] - 1e-7
        assert pause['existing_gap_seconds'] >= .15
    for scene, layout in zip(row['scenes'],plan['scenes']):
        if scene['kind'] == 'glossary':
            assert layout['end_seconds'] - layout['reveal_seconds']['term_2'] >= 8 - 1e-7
        if scene['kind'].startswith('field_'):
            frames = visual_frames(scene,layout)
            assert frames[0]['start_seconds'] == layout['start_seconds']
            assert frames[-1]['end_seconds'] == layout['end_seconds']
            assert all(a['end_seconds'] == b['start_seconds'] for a,b in zip(frames,frames[1:]))
        if scene['kind']=='field_dialogue':
            frames = visual_frames(scene,layout)
            assert frames[0]['phase'] < 0  # context only, no premature Agent bubble
            for index,threshold in enumerate((0,.3,.56)):
                reveal = next(f['start_seconds'] for f in frames if f['phase']>=threshold)
                assert reveal == layout['reveal_seconds']['turn_'+str(index)]
        if scene['kind'] in ('field_consequence','field_evolution'):
            frames = visual_frames(scene,layout)
            reveal = next(f['start_seconds'] for f in frames if f['phase']>=.3)
            assert reveal == layout['reveal_seconds']['decision']
            word = layout['landmarks']['decision']
            assert plan['words'][word]['start']-plan['words'][word-1]['end'] >= 4-1e-7


def test_subtitles_keep_all_authored_punctuation_with_readable_sync_and_no_overlap():
    row = courses()['aps62-10-07']
    boundaries, duration = synthetic_boundaries(row['transcript'])
    plan = make_plan(row,boundaries,duration)
    cues = make_paced_cues(row['transcript'],plan['words'],plan['planned_seconds'])
    assert re.sub(r'\s+','',''.join(c['text'] for c in cues)) == re.sub(r'\s+','',row['transcript'])
    assert all(len(c['text'].splitlines())<=2 for c in cues)
    assert all(max(map(len,c['text'].splitlines()))<=44 for c in cues)
    assert all(c['end']>c['start'] for c in cues)
    assert all(a['end']<=b['start'] for a,b in zip(cues,cues[1:]))
    for cue in cues:
        first_word = plan['words'][cue['first_word']]
        assert first_word['start']-.301 <= cue['start'] <= first_word['start']+.151
    metrics = caption_metrics(cues)
    assert metrics['count'] == len(cues)
    assert metrics['maximum_cps'] < 22


def test_pcm_insertion_preserves_every_source_sample_and_inserts_only_silence(tmp_path):
    source = tmp_path/'source.wav'
    target = tmp_path/'target.wav'
    samples = array.array('h',[((i*79)%30000)-15000 for i in range(8000)])
    with wave.open(str(source),'wb') as f:
        f.setparams((1,2,8000,8000,'NONE','not compressed'))
        f.writeframes(samples.tobytes())
    pauses = [dict(source_cut_seconds=.25,added_seconds=.5),dict(source_cut_seconds=.75,added_seconds=.3)]
    report = insert_pcm_pauses(source,target,pauses,tail_seconds=.1)
    with wave.open(str(target),'rb') as f:
        result = array.array('h',f.readframes(f.getnframes()))
    expected = samples[:2000]+array.array('h',[0])*4000+samples[2000:6000]+array.array('h',[0])*2400+samples[6000:]+array.array('h',[0])*800
    assert result == expected
    assert report['source_frames']==8000
    assert report['inserted_frames']==6400
    assert report['duration_seconds']==1.9


def test_alignment_fails_instead_of_dropping_or_changing_a_word():
    row = courses()['aps62-12-02']
    boundaries, duration = synthetic_boundaries(row['transcript'])
    boundaries[4]['text'] = 'inventé'
    with pytest.raises(ValueError,match='do not match'):
        make_plan(row,boundaries,duration)
