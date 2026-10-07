"""Import the five supplied individual papers; keys below are pedagogical, not official."""
from pathlib import Path
import argparse, hashlib, json, re
from pypdf import PdfReader

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'elearning_native/vtc/annales'
META={
 'A':('SUJET-T3P-VTC-MARS-2023.pdf','T3P',15,45),
 'B':('SUJET-GESTION-VTC-MARS-2023.pdf','Gestion',18,45),
 'C':('SUJET-SECURITE-ROUTIERE-VTC-MARS-2025.pdf','Sécurité routière',20,30),
 'D':('SUJET-FRANCAIS-VTC-MARS-2023.pdf','Français',10,30),
 'E':('SUJET-DANGLAIS-VTC-MARS-2023.pdf','Anglais',20,30),
}

def extract(pdf, text_path=None):
 # Plain extraction preserves word spacing across the text fragments in these
 # PDFs. pypdf 5 layout mode inserts huge gaps *inside* words; collapsing such
 # gaps afterward would still leave misspellings (e.g. "décid ées").
 if text_path is not None:
  parts=re.split(r'^--- PAGE (\d+) ---\s*$',text_path.read_text(),flags=re.M)
  pages=[(int(parts[i]),parts[i+1]) for i in range(1,len(parts),2)]
  if not pages:raise ValueError('Le texte doit conserver les marqueurs --- PAGE N ---.')
 else:
  pages=[(i,page.extract_text(extraction_mode='plain') or '')
         for i,page in enumerate(PdfReader(pdf).pages,1)]
 questions=[]; started=False; current=None; option=None
 for page_no,text in pages:
  if not started:
   if 'Feuille de questionnaire' not in text: continue
   text=text.split('Feuille de questionnaire',1)[1];started=True
  for line in text.splitlines():
   t=re.sub(r'\s+',' ',line.strip())
   if not t or re.search(r'©Evalbox|Référence:|Reference:|CHECK ASSEN|Date de l.examen|#0000|15/03/2023|28 mars 2023|Copie #|Informations:|Ne pas répondre ici|Sélectionner la ou les|Téléphone interdit|Feuille de questionnaire',t):continue
   m=re.match(r'^\s*(\d{1,2})(?:\s+(.*))?\s*$',line)
   if m and int(m[1]) in range(1,21):
    if current:questions.append(current)
    current={'number':int(m[1]),'page':page_no,'prompt':re.sub(r'\s+',' ',(m[2] or '').strip()),'options':[]};option=None;continue
   if current is None:continue
   m=re.match(r'^([A-D])\s*-\s*(.*)',t)
   if m:
    option={'id':m[1].lower(),'text':m[2]};current['options'].append(option)
   elif t.startswith('Question ouverte:'):
    current['original_kind']='qrc';option=None
   elif option is not None:option['text']+=' '+t
   else:current['prompt']+=' '+t
  # questions may continue on the next page; page of beginning is retained
 if current:questions.append(current)
 return questions


def main(source, text_dir=None):
 for module,(filename,title,expected,minutes) in META.items():
  pdf=source/filename
  questions=extract(pdf, text_dir/(Path(filename).stem+'.txt') if text_dir else None)
  assert [q['number'] for q in questions]==list(range(1,expected+1)),(module,[(q['number'],q['prompt'][:40]) for q in questions])
  annotations=json.loads((Path(__file__).parent/f'recent-{module.lower()}.json').read_text())
  context=''
  if module=='D':
   item=questions[4]
   context,_,end=item['prompt'].rpartition('Que veut dire ambiance')
   item['prompt']='Que veut dire ambiance'+end
  for q,meta in zip(questions,annotations):
   assert meta['number']==q['number']
   q.setdefault('original_kind','qcm')
   q.update(meta)
   q['id']=f'annales-2023-{module.lower()}-{q["number"]:02d}'
   q.setdefault('kind','multiple' if q['original_kind']=='qcm' else 'single')
   q.setdefault('status','active');q.setdefault('update_note','');q.setdefault('sources',[])
   q['correction_origin']='pedagogical'
   q.setdefault('learning_points',[q['explanation']])
   if q['original_kind']=='qrc':
    q['adaptation_note']='Question ouverte du sujet original, adaptée en choix pédagogiques pour répondre sans rédaction.'
    q['original_answer_origin']='pedagogical'
   if module=='D':q['context']=context.strip()
  document={'id':f'sujet-2023-{module.lower()}','title':f'28 mars 2023 · {title}','year':2023,
    'source_filename':filename,'source_sha256':hashlib.sha256(pdf.read_bytes()).hexdigest(),
    'sections':[{'id':f'annales-2023-{module.lower()}','module':module,'title':title+' · mars 2023','minutes':minutes,'questions':questions}]}
  if module=='C':
   document['source_note']='Le fichier porte « MARS-2025 », mais toutes les pages du sujet indiquent le 28 mars 2023. Le classement reprend la date imprimée dans le document.'
   image_dir=ROOT/'elearning_native/vtc/assets/media/vtc/annales';image_dir.mkdir(parents=True,exist_ok=True)
   r=PdfReader(pdf)
   for qno,pageno,imgno,name in [(1,1,0,'2023-c-01.jpg'),(6,2,0,'2023-c-06.jpg')]:
    (image_dir/name).write_bytes(r.pages[pageno].images[imgno].data)
    questions[qno-1]['image']='media/vtc/annales/'+name
  OUT.mkdir(parents=True,exist_ok=True)
  (OUT/(document['id']+'.json')).write_text(json.dumps(document,ensure_ascii=False,indent=2)+'\n')
  print(module,len(questions),'questions')

if __name__=='__main__':
 parser=argparse.ArgumentParser()
 parser.add_argument('source',type=Path)
 parser.add_argument('--text-dir',type=Path,help='Textes contrôlés, avec marqueurs de pages PDF.')
 args=parser.parse_args();main(args.source,args.text_dir)
