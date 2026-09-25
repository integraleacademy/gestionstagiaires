"""Refuse to publish the manifest until every video has a validated render."""
import json,os
from pathlib import Path
ROOT=Path(__file__).resolve().parent
WORK=Path(os.environ['ACADEMY_WORK'])
MEDIA=ROOT.parents[1]/'elearning_native/media'
entries=[]
for v in json.loads((ROOT/'series.json').read_text()):
    result=json.loads((WORK/v['id']/'render.json').read_text())
    assert result['voice']=='fr-FR-HenriNeural' and result['rate']=='-2%'
    assert result['reference_style']=='missions-limites-20260920'
    assert (result['width'],result['height'])==(3840,2160)
    filename=v['id']+'.mp4';poster=v['id']+'.jpg'
    assert (MEDIA/filename).stat().st_size==result['bytes']
    assert (MEDIA/poster).stat().st_size>1000
    entries.append({**{k:v[k] for k in ['course_id','course_version','activity_id','id','title','module','sequence']},
       'filename':filename,'poster':poster,'duration_seconds':result['duration_seconds']})
assert len(entries)==16
(ROOT.parents[1]/'elearning_native/video_series.json').write_text(json.dumps(entries,ensure_ascii=False,indent=2)+'\n')
print('16 capsules validées + 1 capsule existante = 17 séquences couvertes')
