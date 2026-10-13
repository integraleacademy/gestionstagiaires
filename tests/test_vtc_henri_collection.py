"""All VTC videos retain their text, English models and trusted viewing."""
import copy
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from elearning_native import vtc_video_quality as quality
from scripts.vtc import render_henri_collection as build
from scripts.vtc.readable_captions_v11 import make_cues
from scripts.aps62_v5.captions import align_words, canonical


def test_narration_partition_is_lossless_and_preserves_english_models():
    original = {r['ref']:r for r in build.base.quality_rows()}
    prepared = build.prepare_rows()
    assert len(prepared) == 104
    for row in prepared:
        for before, after in zip(original[row['ref']]['scenes'],row['scenes']):
            assert build.base.scene_text(after) == build.base.scene_text(before)
            assert [s['text'] for s in after['segments'] if s['lang']=='en'] == [s['text'] for s in before['segments'] if s['lang']=='en']
            if row['ref'] == 'D.02':
                continue
            for segment in after['segments']:
                delivery = segment['delivery']
                if segment['lang']=='en':
                    assert delivery['rate']=='-6%' and delivery['pitch']=='+0Hz'
                else:
                    assert -2 <= int(delivery['rate'][:-1]) <= 4
                    assert -1 <= int(delivery['pitch'][:-2]) <= 2
                assert 0 <= delivery['gap_after_seconds'] <= .16


def test_question_answer_and_original_spacing_are_kept_together():
    text = 'Voici les premières informations utiles pour comprendre le cas et préparer une réponse précise à la question posée. Quelle date retenir ? Celle du départ. Enfin, vérifiez le document.'
    groups = build.thought_groups(text)
    assert ''.join(groups) == text
    assert any('Quelle date retenir ? Celle du départ.' in g for g in groups)
    assert all(g[-1].isspace() for g in groups[:-1])


def test_dense_real_henri_passage_has_readable_synchronised_lossless_captions():
    fixture=json.loads((Path(__file__).parent/'fixtures/vtc_henri_dense_words.json').read_text())
    cues=make_cues(fixture['text'],fixture['words'],fixture['seconds'],playback_rate=1)
    assert ''.join(''.join(c['text'].split()) for c in cues)==''.join(fixture['text'].split())
    words=align_words(fixture['text'],fixture['words'])
    timeline=[word for word in words for char in canonical(word['text'])]
    cursor=0
    for cue in cues:
        assert cue['end']-cue['start'] >= 1
        assert len(cue['text'].replace('\n',' '))/(cue['end']-cue['start']) <= 20
        assert len(cue['text'].splitlines()) <= 2 and max(map(len,cue['text'].splitlines())) <= 44
        assert -.161 <= cue['start']-timeline[cursor]['start'] <= .391
        cursor += len(canonical(cue['text']))


@pytest.mark.parametrize('generation',['original','v11'])
@pytest.mark.parametrize('completed',[True,False])
def test_all_104_known_timelines_keep_completion_and_chapter_resume(generation,completed):
    baseline = quality.quality_manifest()
    latest = quality.approved_voice_updates()
    assert len(latest)==104
    for ref,after in latest.items():
        before=baseline['lessons' if '.' in ref else 'modules'][ref]
        prefix='previous_' if generation=='original' else ''
        duration, chapters=before[prefix+'duration_seconds'],before[prefix+'chapters']
        index=len(chapters)//2
        chapter=chapters[index]
        watched=duration if completed else chapter['start_seconds']+.37*(chapter['end_seconds']-chapter['start_seconds'])
        record=dict(duration_seconds=duration,watched_seconds=watched,completed=completed,completed_at='2026-10-12' if completed else None)
        frozen=copy.deepcopy(record)
        video_id=f'vtc-{ref[0].lower()}-'+(f'{ref[2:]}-explanation-v10' if '.' in ref else 'capsule')
        result=quality.compatible_record(video_id,record,after['duration_seconds'])
        assert record==frozen
        assert result['completed'] is completed
        assert result['duration_seconds']==after['duration_seconds']
        expected=after['duration_seconds'] if completed else after['chapters'][index]['start_seconds']+.37*(after['chapters'][index]['end_seconds']-after['chapters'][index]['start_seconds'])
        assert result['watched_seconds']==pytest.approx(expected,abs=.003),ref
        assert result['completed_at']==record['completed_at']


@pytest.mark.parametrize('mutation',['missing_lesson','missing_summary','approved_take','reference','voice','previous','path'])
def test_incomplete_or_mismatched_full_collection_is_rejected(tmp_path,mutation):
    root=quality.ROOT
    data=json.loads((root/'video_voice_v15.json').read_text())
    row=data['modules']['A']
    if mutation=='missing_lesson': del data['lessons']['H.12']
    elif mutation=='missing_summary': del data['modules']['H']
    elif mutation=='approved_take': data['lessons']['D.02']['media_sha256']='0'*64
    elif mutation=='reference': data['reference_media_sha256']='0'*64
    elif mutation=='voice': row['voice']={'fr':'another-voice'}
    elif mutation=='previous': row['previous_media_sha256']='0'*64
    elif mutation=='path': row['src']='media/vtc/v15/../v11/lesson-a.mp4'
    (tmp_path/'video_voice_v15.json').write_text(json.dumps(data))
    for name in ('video_voice_v14.json','video_quality_v11.json','lesson_videos_v10.json','video_pacing_v9.json','assets'):
        (tmp_path/name).symlink_to(root/name,target_is_directory=name=='assets')
    quality.quality_manifest.cache_clear();quality.approved_voice_updates.cache_clear()
    try:
        with patch.object(quality,'ROOT',tmp_path),pytest.raises(ValueError,match='VTC voice'):
            quality.approved_voice_updates()
    finally:
        quality.quality_manifest.cache_clear();quality.approved_voice_updates.cache_clear()
