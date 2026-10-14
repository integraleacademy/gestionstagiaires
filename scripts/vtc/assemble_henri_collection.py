"""Assemble and validate the complete Henri release entirely offline.

Useful after separately authorised rendering batches. This command never
calls the speech client and never submits narration to a service.
Every cached render is checked against the current authoring/code signature,
and every output is decoded again before the complete manifest is published.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts.vtc import render_henri_collection as build


def inspect(row):
    path=build.WORK/row['ref']/'result.json'
    video=json.loads(path.read_text())
    actual=deepcopy(row)
    for scene,timing in zip(actual['scenes'],video['scenes']):
        scene['segments']=timing['language_segments']
    report=build.qa.inspect_one(actual,video,expected_signature=build.signature(row),
        playback_rate=1,revision=15,work_dir=build.WORK)
    assert 0.005 < report['audio']['rms'] < .5
    return row['ref'],video,report


def main():
    rows=[r for r in build.prepare_rows() if r['ref']!='D.02']
    assert len(rows)==103
    # Fail before spending time decoding if a rendering batch is missing.
    for row in rows:
        assert (build.WORK/row['ref']/'result.json').exists(),row['ref']
    manifest=dict(revision=15,scope='all-vtc-videos',approved_on='2026-10-13',
        reference_media_sha256=build.APPROVED_SHA,lessons={'D.02':build.approved_take()},modules={})
    reports={}
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(inspect,row) for row in rows]
        for future in as_completed(futures):
            ref,video,report=future.result()
            manifest['lessons' if '.' in ref else 'modules'][ref]=video
            reports[ref]=report
            build.base.atomic_json(build.WORK/'validation-complete-progress.json',reports)
            print('VERIFIED',ref,len(reports)+1,'/104',flush=True)
    assert set(manifest['lessons'])=={f'{m}.{i:02}' for m in 'ABCDEFGH' for i in range(1,13)}
    assert set(manifest['modules'])==set('ABCDEFGH')
    for section in ('lessons','modules'):
        manifest[section]=dict(sorted(manifest[section].items()))
    build.base.atomic_json(build.WORK/'validation-progress.json',reports)
    build.base.atomic_json(build.MANIFEST,manifest)
    print('COMPLETE 104/104; offline validation passed',flush=True)


if __name__=='__main__':
    main()
