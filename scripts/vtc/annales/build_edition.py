"""Build the immutable edition from reviewed teaching notes and improved exercises."""
import copy
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from elearning_native import annales
from improve_pedagogy import improve_course
from refresh_rules import refresh_course
from exams_independent import build_exams
BASE='20261007-vtc-v4-visuals'
VERSION='20261007-vtc-v5-annales'
OUT=ROOT/'elearning_native/vtc'

def save(path,data):
 path.parent.mkdir(parents=True,exist_ok=True)
 path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')

def build():
 total=annales.validate_bank();documents=annales.sources()
 manifest=json.loads((OUT/'manifest.json').read_text())
 report={'version':VERSION,'reviewed_on':'2026-10-07','source_count':len(documents),'question_count':total,'modules':[],'questions':[]}
 all_refs={lesson['ref'] for m in manifest['modules'] for lesson in m['lessons']}
 for doc in documents:
  for section in doc['sections']:
   for q in section['questions']:
    assert set(q['lesson_refs'])<=all_refs,q['id']
    if q.get('image'):assert (OUT/'assets'/q['image']).is_file(),q['id']
    report['questions'].append({k:copy.deepcopy(q[k]) for k in ('id','number','page','prompt','lesson_refs','status','correction_origin','update_note')}|{'source':doc['source_filename'],'section_id':section['id']})
 notes_count=0
 for module in manifest['modules']:
  cid=module['id'];course=json.loads((OUT/'courses'/cid/(BASE+'.json')).read_text())
  course['version']=VERSION;course['source']['annales_edition_on']='2026-10-07'
  changes=improve_course(course);changes['rule_edits']=refresh_course(course)
  covered=[]
  for section in course['sections']:
   for a in section['activities']:
    lesson=a.get('vtc',{})
    if lesson.get('kind')=='lesson':
     notes=annales.lesson_notes(lesson['ref'])
     if notes:
      lesson['annales_notes']=notes;covered.append(lesson['ref']);notes_count+=len(notes)
  course['counts']['annales_lessons']=len(covered)
  course['duration_note']='105 h pour l’ensemble du programme prévisionnel, à calibrer avec un groupe pilote. Les compléments et reprises ne créent pas de temps actif fictif.'
  assert sum(a['planned_minutes'] for s in course['sections'] for a in s['activities'])==course['planned_minutes']
  save(OUT/'courses'/cid/(VERSION+'.json'),course)
  module['previous_versions']=list(dict.fromkeys([*module.get('previous_versions',[]),BASE]))
  module['version']=VERSION;module['counts']=copy.deepcopy(course['counts'])
  report['modules'].append({'id':cid,'letter':module['letter'],'covered_lessons':covered,**changes})
 manifest.update(version=VERSION,reviewed_on='2026-10-07',annales_question_count=total,annales_source_count=len(documents),annales_section_count=sum(len(d['sections']) for d in documents),annales_active_count=sum(q['status']=='active' for q in report['questions']),annales_lesson_count=sum(len(m['covered_lessons']) for m in report['modules']))
 manifest['exam_versions']=list(dict.fromkeys([*manifest['exam_versions'],VERSION]))
 for key in ('exercises','decisions'):manifest[key[:-1]+'_count']=sum(m['counts'][key] for m in manifest['modules'])
 # Rebuilt independently of lesson/workshop prompts; old exam editions stay byte-identical.
 for exam_id in [m['mock_exam_id'] for m in manifest['modules']]+[manifest['final_exam_id']]:
  previous=json.loads((OUT/'exams'/BASE/(exam_id+'.json')).read_text())
  exam=build_exams(previous,documents,VERSION)
  assert len(exam['questions'])==(100 if exam_id=='vtc-final' else 30),(exam_id,len(exam['questions']))
  save(OUT/'exams'/VERSION/(exam_id+'.json'),exam)
 programme=json.loads((OUT/'programme_105.json').read_text());programme['version']=VERSION
 assert programme['validation']['real_learners_tested']==0
 programme['validation']['content_revision_note']='Les doublons de dossiers ont été retirés et les notions des annales ajoutées. Les 105 heures restent un objectif prévisionnel ; aucune mesure apprenant ne justifie encore cette durée.'
 save(OUT/'programme_105.json',programme)
 report.update(active_count=manifest['annales_active_count'],historical_count=total-manifest['annales_active_count'],covered_lesson_count=manifest['annales_lesson_count'],teaching_note_count=notes_count)
 save(OUT/'annales_coverage.json',report);save(OUT/'manifest.json',manifest)
 print(json.dumps({k:v for k,v in report.items() if k not in ('modules','questions')},ensure_ascii=False))
 print('Exercises:',manifest['exercise_count'],'duplicates removed:',sum(m['removed_duplicates'] for m in report['modules']))
if __name__=='__main__':build()
