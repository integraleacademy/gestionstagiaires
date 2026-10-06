"""Rebalance APS around its subjects, not a journal in every dossier.

Previous editions are immutable. The module budgets remain pedagogical targets;
activity allocations are indicative and are not measured learner durations.
"""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from scripts.build_aps62_v3 import single, review, write
from scripts.aps62_v4.casefiles import CASEFILES, JOURNALS

ROOT = REPO / 'elearning_native/aps62'
SOURCE = REPO / 'scripts/aps62_v4'
OLD = '20261006-aps62-v3'
VERSION = '20261006-aps62-v4'


def make_practice(key, data, scenario, journal=False):
    exercises = []
    for i, item in enumerate(data['questions']):
        ex = single(key, 'choix-' + str(i + 1), item['prompt'], item['correct'],
                    item['wrong'], item['explanation'])
        skill = ('time' if i == 0 and key.endswith('08-03') else 'journal' if journal else 'decision')
        ex['remediation'] = review(scenario, skill)
        exercises.append(ex)
    if data.get('classification'):
        ex = copy.deepcopy(data['classification'])
        ex['id'] = 'classement'
        ex['remediation'] = review(scenario, 'document')
        exercises.append(ex)
    return dict(revision=VERSION, title=data['title'], journal=journal,
                documents=copy.deepcopy(data['documents']), exercises=exercises)


def activity(section, suffix, data, scenario, minutes):
    return dict(id=section['id'] + '-' + suffix, title=data['title'], type='content', scored=False,
        planned_minutes=minutes, blocks=[], practice=make_practice(section['id'], data, scenario, suffix == 'journal'),
        academy=dict(kind='journal' if suffix == 'journal' else 'documents',
            dossier=section['activities'][0]['academy']['dossier'], title=data['title'],
            case=data['brief'], edition='2026-10-06'))


def build():
    scenarios = {r[0]: r for line in (REPO/'scripts/aps62_v3/scenarios.txt').read_text().splitlines()
                 if line and not line.startswith('#') for r in [line.split('|')]}
    focuses = {r[0]: r for line in (SOURCE/'focus.txt').read_text().splitlines()
               if line and not line.startswith('#') for r in [line.split('|')]}
    assert len(focuses) == 62 and all(len(r) == 9 for r in focuses.values())
    manifest = json.loads((ROOT/'manifest.json').read_text())
    activities_total = workshops_total = 0
    allocation = []
    for item in manifest['modules']:
        course = json.loads((ROOT/'courses'/item['id']/(OLD+'.json')).read_text())
        course['version'] = course['interaction_revision'] = VERSION
        special_minutes = (14 if item['number'] in CASEFILES else 0) + sum(
            10 for key in JOURNALS if key.startswith(item['number'] + '-'))
        # The former 14 minutes of generic documents/journal per dossier now fund
        # subject-specific course comparisons and a small set of targeted studies.
        extra_minutes = course['planned_minutes'] - 46 * len(course['sections']) - special_minutes
        assert extra_minutes >= 0
        whole, remainder = divmod(extra_minutes, len(course['sections']))
        for index, section in enumerate(course['sections']):
            key = section['id'].removeprefix('aps62-')
            focus, scenario = focuses[key], scenarios[key]
            acts = [a for a in section['activities'] if a.get('academy', {}).get('kind') not in ('journal', 'documents')]
            assert len(acts) == 7
            lesson = acts[0]['academy']
            lesson['deepening'].insert(0, dict(title=focus[1], paragraphs=[focus[2], 'Exemple expliqué. ' + focus[3]]))
            lesson['edition'] = '2026-10-06'
            acts[0]['planned_minutes'] = 16 + whole + (index < remainder)
            # Keep actual observation and two successive decisions; drop the
            # repeated generic document/relief questions from all 62 missions.
            mission = acts[2]['practice']
            mission['exercises'] = mission['exercises'][:3]
            mission.update(revision=VERSION, title=scenario[1] + ' · la situation évolue')
            for ex in mission['exercises']:
                ex['branches'] = {o['id']: ex['explanation'] + (
                    ' Examinez la nouvelle information à l’étape suivante.' if o['id'] == ex['answer'] else
                    ' Réexaminez votre choix à partir de ces repères.') for o in ex['options']}
            # A genuinely new situation replaces both generic method questions.
            transfer = acts[5]['practice']
            check = single(key, 'application', focus[4], focus[5], [focus[6], focus[7]], focus[8])
            check['remediation'] = review(scenario, 'decision')
            transfer.update(revision=VERSION, title='Changer de contexte · ' + focus[1],
                            exercises=[transfer['exercises'][0], check])
            additions = []
            casefile = CASEFILES.get(item['number'])
            if casefile and casefile['section'] == key:
                additions.append(activity(section, 'etude', casefile, scenario, 14))
            if key in JOURNALS:
                additions.append(activity(section, 'journal', JOURNALS[key], scenario, 10))
            section['activities'] = acts[:6] + additions + acts[6:]
            lesson['pacing'] = [dict(label=a['title'], minutes=a['planned_minutes']) for a in section['activities']]
            lesson['pacing_note'] = 'Répartition indicative du travail : lecture, comparaison, choix et correction. Le rythme réel varie selon les acquis.'
        all_activities = [a for s in course['sections'] for a in s['activities']]
        assert sum(a['planned_minutes'] for a in all_activities) == course['planned_minutes']
        course['activity_order'] = [a['id'] for a in all_activities]
        course['counts'].update(activities=len(all_activities), workbooks=0,
            interactive_workshops=sum(bool(a.get('practice')) for a in all_activities),
            journal_workshops=sum(bool(a.get('practice', {}).get('journal')) for a in all_activities),
            document_studies=sum(a['id'].endswith('-etude') for a in all_activities))
        activities_total += len(all_activities)
        workshops_total += course['counts']['interactive_workshops']
        allocation.append(dict(module=item['number'], title=course['title'],
            target_minutes=course['planned_minutes'], journals=course['counts']['journal_workshops'],
            document_studies=course['counts']['document_studies'],
            sections=[dict(id=s['id'], minutes=sum(a['planned_minutes'] for a in s['activities']),
                           activities=[a['title'] for a in s['activities']]) for s in course['sections']]))
        write(ROOT/'courses'/item['id']/(VERSION+'.json'), course)
        item['previous_versions'] = list(dict.fromkeys([*item.get('previous_versions', []), OLD]))
        item.update(version=VERSION, activities=len(all_activities))
    for path in (ROOT/'exams'/OLD).glob('*.json'):
        exam = json.loads(path.read_text())
        exam['version'] = VERSION
        write(ROOT/'exams'/VERSION/path.name, exam)
    assert activities_total == 452 and workshops_total == 142
    manifest.update(version=VERSION, interaction_revision=VERSION, activity_count=activities_total,
        interactive_workshop_count=workshops_total,
        enrichment=dict(missions=62, document_analyses=14, journals=4,
            authored_course_explanations=62, new_transfer_situations=62, new_review_situations=62,
            decision_steps=186, authored_on='2026-10-06',
            timing_status='Objectif pédagogique de 62 h à éprouver avec des apprenants ; aucune durée réelle garantie.',
            source_sha256=hashlib.sha256((SOURCE/'focus.txt').read_bytes() + (SOURCE/'casefiles.py').read_bytes()).hexdigest()))
    manifest['exam_versions'] = list(dict.fromkeys([*manifest.get('exam_versions', []), VERSION]))
    write(ROOT/'manifest.json', manifest)
    regulatory = json.loads((ROOT/'regulatory_review.json').read_text())
    regulatory['edition'] = VERSION
    regulatory['operational_checks'] = [s.replace('Version 3 :', 'Édition actuelle :') for s in regulatory['operational_checks']]
    write(ROOT/'regulatory_review.json', regulatory)
    write(ROOT/'allocation_v4.json', dict(version=VERSION, timing_status=manifest['enrichment']['timing_status'], modules=allocation))
    print(f'{VERSION}: 452 activités, 142 ateliers, 14 études thématiques, 4 mains courantes, objectif 62 h.')


if __name__ == '__main__':
    build()
