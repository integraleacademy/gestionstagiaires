"""Build the immutable 2026-10-04 edition without changing assigned v1 courses."""
import copy, hashlib, json, random, shutil
from pathlib import Path
from collections import defaultdict
from aps62_editorial import MODULES, records
from aps62_visuals import BOARDS, CASES
ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'elearning_native/aps62'
VERSION='20261004-aps62-v2'
OLD='20261003-aps62-v1'
SOURCES={
 'cadre':['CSI, livre VI','https://www.legifrance.gouv.fr/codes/section_lc/LEGITEXT000025503132/LEGISCTA000025506179/'],
 'defense':['Code pénal, article 122-5','https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000006417218'],
 'penal':['Code pénal','https://www.legifrance.gouv.fr/codes/texte_lc/LEGITEXT000006070719/'],
 'flagrance':['CPP, article 73','https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000029000766'],
 'controle':['CSI, article L613-2 (édition août 2026)','https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000054725427'],
 'donnees':['CNIL, vidéoprotection au travail','https://www.cnil.fr/fr/la-videosurveillance-videoprotection-au-travail'],
 'deonto':['Code de déontologie de la sécurité privée','https://www.legifrance.gouv.fr/codes/section_lc/LEGITEXT000025503132/LEGISCTA000029656360/'],
 'egalite':['Code pénal, article 225-1','https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000045391831'],
 'risques':['INRS, évaluation des risques','https://www.inrs.fr/demarche/evaluation-risques-professionnels/ce-qu-il-faut-retenir'],
 'coactivite':['INRS, entreprises extérieures','https://www.inrs.fr/risques/entreprises-exterieures/ce-qu-il-faut-retenir.html'],
 'elec':['INRS, prévention du risque électrique','https://www.inrs.fr/risques/electriques/prevention-risque-electrique'],
 'habilitation':['INRS, habilitation électrique','https://www.inrs.fr/risques/electriques/habilitation-electrique'],
 'vigi':['SGDSN, plan Vigipirate actualisé','https://www.sgdsn.gouv.fr/vigipirate'],
 'attaque':['Consignes publiques en cas d’attaque','https://www.info.gouv.fr/risques/reagir-en-cas-dattaque-terroriste'],
}
SOURCE_KEYS=['cadre deonto','penal defense','flagrance deonto','donnees controle','egalite deonto','deonto donnees','deonto defense','deonto donnees','cadre deonto','risques coactivite','elec habilitation','vigi attaque','donnees deonto','flagrance defense','controle cadre']

def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')

def build_exams():
    banks=defaultdict(list)
    for path in sorted((ROOT/'scripts').glob('aps62_exam_questions*.txt')):
        code=None
        for line in path.read_text().splitlines():
            if line.startswith('['): code=line[1:-1]
            elif line and not line.startswith('#'):
                parts=[s.strip() for s in line.split('|')]
                assert len(parts)==5 and code, (path,line)
                banks[code].append(parts)
    all_questions=[]
    for index,(code,title,*_) in enumerate(MODULES):
        assert len(banks[code])==30,(code,len(banks[code]))
        questions=[]
        for n,(prompt,answer,wrong1,wrong2,explanation) in enumerate(banks[code],1):
            qid=f'aps62-q-{code}-{n:02}'
            choices=[answer,wrong1,wrong2]
            random.Random(qid).shuffle(choices)
            assert len(set(choices))==3
            options=[{'id':str(i+1),'text':text} for i,text in enumerate(choices)]
            questions.append(dict(id=qid,prompt=prompt,options=options,answer=str(choices.index(answer)+1),explanation=explanation,module=f'{code} · {title}',sources=[SOURCES[k] for k in SOURCE_KEYS[index].split()]))
        write(DATA/'exams'/VERSION/f'module-{code}.json',dict(id=f'module-{code}',version=VERSION,title=title,pass_percent=75,questions=questions,reviewed_on='2026-10-04'))
        all_questions.extend(questions)
    assert len({q['prompt'] for q in all_questions})==450
    # Balanced synthesis: 6 or 7 questions per module, 100 in total.
    final=[]
    for index,(code,*_) in enumerate(MODULES):
        subset=[q for q in all_questions if q['id'].startswith(f'aps62-q-{code}-')]
        random.Random('aps62-final-'+code).shuffle(subset)
        final.extend(copy.deepcopy(subset[:7 if index<10 else 6]))
    random.Random('aps62-final-v2').shuffle(final)
    assert len(final)==100
    write(DATA/'exams'/VERSION/'final.json',dict(id='final',version=VERSION,title='Examen blanc final APS',pass_percent=75,questions=final,reviewed_on='2026-10-04'))

def main():
    videos=json.loads((DATA/'video_manifest_v2.json').read_text());assert len(videos)==62
    assert all(v['voice']=='fr-FR-HenriNeural' and v['burned_captions'] for v in videos.values())
    manifest=json.loads((DATA/'manifest.json').read_text());manifest['version']=VERSION;manifest['exam_versions']=[VERSION]
    manifest['mock_questions']=450;manifest['final_questions']=100;manifest['illustrations']=15
    rows=records()
    for module in manifest['modules']:
        code=module['number'];course=json.loads((DATA/'courses'/module['id']/(OLD+'.json')).read_text())
        course['version']=VERSION;course['source']['reviewed_on']='2026-10-04';course['mock_exam_id']='module-'+code
        course['mock_exam_questions']=30;course['voice']='fr-FR-HenriNeural';course['illustration']=f'images/aps62/module-{code}.webp'
        public=ROOT/'static/images/aps62';public.mkdir(exist_ok=True)
        shutil.copyfile(DATA/'assets/media/aps62/v2'/f'module-{code}.webp',public/f'module-{code}.webp')
        for n,section in enumerate(course['sections'],1):
            sid=f'aps62-{code}-{n:02}';row=rows[code][n-1]
            for activity in section['activities']:
                academy=activity.get('academy',{})
                academy['edition']='2026-10-04'
                if academy.get('kind')=='lesson':
                    academy['image']=f'media/aps62/v2/module-{code}.webp'
                    academy['image_alt']=f'Scène professionnelle illustrée : {module["title"]}'
                    if n==1:
                        board_title,steps=BOARDS[code]
                        academy['visual_board']={'title':board_title,'steps':[dict(label=k,text=v) for k,v in steps]}
                        title,case,task,model=CASES[code]
                        academy['extra_case']=dict(title=title,case=case,task=task,model=model)
                    items=[{'text':row['case'],'category':'fait'},{'text':row['good'],'category':'adapte'},{'text':row['bad'],'category':'ecarter'}]
                    random.Random(sid).shuffle(items)
                    academy['sorting']=items
                if academy.get('kind')=='memory':
                    academy['voice']='fr-FR-HenriNeural';academy['transcript']=videos[sid]['transcript']
                for block in activity.get('blocks',[]):
                    if block.get('video'):
                        block['video'].update(videos[sid])
        # Retain referenced manual pages; remove v1 video/scene references from this new edition only.
        used=set()
        def collect(value):
            if isinstance(value,str) and value.startswith('media/aps62/'):used.add(value)
            elif isinstance(value,dict):
                for k,v in value.items():
                    if k!='assets':collect(v)
            elif isinstance(value,list):
                for v in value:collect(v)
        collect(course);course['assets']=sorted(used)
        assert all((DATA/'assets'/p).is_file() for p in used)
        write(DATA/'courses'/module['id']/(VERSION+'.json'),course)
        module['version']=VERSION;module['previous_versions']=[OLD];module['exam_questions']=30
    build_exams();write(DATA/'manifest.json',manifest)
    print('Built 15 modules, 62 dossiers, 62 Henri videos, 450 module questions, 100 final questions; v1 preserved.')

if __name__=='__main__':main()
