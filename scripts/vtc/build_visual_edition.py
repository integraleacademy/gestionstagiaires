"""Publish an immutable VTC visual edition after media verification.

The 105-hour programme and existing assignments are preserved. The longer video
replaces part of the same 20-minute synthesis slot, rather than adding fake time.
"""
import copy
import json
import math
from pathlib import Path
from build_visual_scripts import methods
from visual_tables import TABLES

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'elearning_native/vtc'
BASE = '20261006-vtc-v3-105h'
VERSION = '20261007-vtc-v4-visuals'
ILLUSTRATED_PAGES = {
    17:'A.01',47:'A.02',48:'A.11',50:'A.12',51:'A.12',
    73:'B.01',74:'B.02',98:'B.10',107:'B.12',108:'B.12',112:'B.04',113:'B.06',
    167:'C.12',168:'C.12',174:'C.02',175:'C.05',176:'C.08',
    295:'F.03',296:'F.03',297:'F.03',
}


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def assets(value):
    if isinstance(value, str) and value.startswith('media/vtc/'):
        yield value
    elif isinstance(value,dict):
        for item in value.values():
            yield from assets(item)
    elif isinstance(value,list):
        for item in value:
            yield from assets(item)


def build(require_videos=True):
    steps=methods()
    manifest=json.loads((OUT/'manifest.json').read_text())
    videos=json.loads((OUT/'video_manifest_v4.json').read_text()) if (OUT/'video_manifest_v4.json').exists() else {}
    if require_videos:
        assert set(videos)==set('ABCDEFGH'), 'All eight verified videos are required before publishing'
        assert min(v['duration_seconds'] for v in videos.values())>=300
    manifest['version']=VERSION
    manifest['visual_edition_on']='2026-10-07'
    manifest['visual_method_count']=96
    manifest['comparison_table_count']=len(TABLES)
    manifest['inline_manual_figure_count']=len(ILLUSTRATED_PAGES)
    manifest['animated_video_count']=len(videos) if require_videos else 0
    manifest['exam_versions']=list(dict.fromkeys([*manifest['exam_versions'],BASE,VERSION]))
    for module in manifest['modules']:
        letter=module['letter'];cid=module['id']
        course=json.loads((OUT/'courses'/cid/(BASE+'.json')).read_text())
        course['version']=VERSION
        course['source']['visual_edition_on']='2026-10-07'
        illustrations=course['sections'][-1]['activities'][1]['vtc']['supplements']
        for section in course['sections'][:12]:
            lesson=section['activities'][0]['vtc'];ref=lesson['ref']
            lesson['visual_steps']=steps[ref]
            lesson['deepening']['method']=[s['title']+' : '+s['text'] for s in steps[ref]]
            if ref in TABLES:
                lesson['visual_table']=TABLES[ref]
            lesson['inline_figures']=[copy.deepcopy(p) for p in illustrations if ILLUSTRATED_PAGES.get(p['page'])==ref]
        if require_videos:
            v=videos[letter];recap,extra=course['sections'][-1]['activities']
            minute=math.ceil(v['duration_seconds']/60)
            assert 5<=minute<=15
            oldvideo=recap['blocks'][0]['video']
            recap['blocks'][0]['video']={**copy.deepcopy(v),'id':oldvideo['id'],'title':oldvideo['title'],'required':True}
            recap['planned_minutes']=minute
            extra['planned_minutes']=20-minute
            recap['title']='Comprendre en vidéo · les douze notions'
            recap['vtc'].update(transcript=v['transcript'],audio=True,course_only=True,video_minutes=minute)
        course.pop('assets',None)
        course['assets']=sorted(set(assets(course)))
        course['counts'].update(assets=len(course['assets']),visual_methods=12,comparison_tables=sum(r.startswith(letter+'.') for r in TABLES))
        assert sum(a['planned_minutes'] for s in course['sections'] for a in s['activities'])==module['planned_minutes']
        # Preparation may be run for local review; it never changes the manifest.
        destination=(OUT/'courses'/cid/(VERSION+'.json')) if require_videos else ROOT.parent/'vtc-review'/cid/'course.json'
        save(destination,course)
        module['previous_versions']=list(dict.fromkeys([*module.get('previous_versions',[]),BASE]))
        module['version']=VERSION;module['counts']=copy.deepcopy(course['counts'])
        for suffix in [letter.lower()]:
            exam=json.loads((OUT/'exams'/BASE/f'vtc-{suffix}.json').read_text());exam['version']=VERSION
            if require_videos:save(OUT/'exams'/VERSION/f'vtc-{suffix}.json',exam)
    if require_videos:
        exam=json.loads((OUT/'exams'/BASE/'vtc-final.json').read_text());exam['version']=VERSION
        save(OUT/'exams'/VERSION/'vtc-final.json',exam)
        manifest['video_minutes']=round(sum(v['duration_seconds'] for v in videos.values())/60,1)
        manifest['video_min_seconds']=min(v['duration_seconds'] for v in videos.values())
        save(OUT/'manifest.json',manifest)
        programme=json.loads((OUT/'programme_105.json').read_text());programme['version']=VERSION
        save(OUT/'programme_105.json',programme)
    print(VERSION, '96 methods,',len(TABLES),'tables,',len(videos),'videos', 'PUBLISHED LOCALLY' if require_videos else 'REVIEW ONLY')


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--review-only',action='store_true')
    build(not parser.parse_args().review_only)
