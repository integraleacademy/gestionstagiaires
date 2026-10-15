"""Refuse incomplete media publication and write the measured catalogue."""
import hashlib
import json
from .compile import ROOT, RES, all_cards, validate_complete, narration, signature
from .render import duration, run

def main():
    rows=all_cards();validate_complete(rows)
    folder=RES/'assets/media/a3p/v4'
    expected={r['id']+'.'+ext for r in rows for ext in ('mp4','jpg','vtt','json')}
    assert {p.name for p in folder.iterdir()}==expected
    result={}
    for row in rows:
        path=folder/(row['id']+'.mp4');meta=json.loads(folder.joinpath(row['id']+'.json').read_text())
        assert meta['source_sha256']==signature(row,narration(row)), row['id']
        assert meta['video_sha256']==hashlib.sha256(path.read_bytes()).hexdigest()
        actual=duration(path)
        assert abs(actual-meta['duration_seconds'])<.1 and actual>=300
        assert meta['narration_seconds']>=295 and meta['voice']=='fr-FR-HenriNeural'
        assert meta['burned_captions'] and meta['required']
        assert folder.joinpath(row['id']+'.vtt').read_text().startswith('WEBVTT\n')
        assert actual/60<row['minutes']-12
        result[row['id']]=meta
    RES.joinpath('v4/media_manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print('VERIFIED',len(result),'videos',round(sum(r['duration_seconds'] for r in result.values())/60,2),'actual minutes')

if __name__=='__main__':main()
