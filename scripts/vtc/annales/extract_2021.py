"""Extract text and marked answer keys from the supplied 2021 PDF locally.

The source is private and is never copied into the repository. CLI: PDF TEXT OUT.
Answer icons are identified by their yellow pixels, not by guessed question keys.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

import pdfplumber
from pypdf import PdfReader


def extract(pdf_path, text_path):
    text = Path(text_path).read_text()
    pages = re.split(r'--- PAGE (\d+) ---\n', text)[1:]
    sections = [('A', 2, 3), ('B', 4, 5), ('C', 6, 8), ('D', 9, 10), ('E', 11, 13), ('F', 14, 15), ('G', 16, 16)]
    reader = PdfReader(pdf_path)
    extracted = []
    with pdfplumber.open(pdf_path) as pdf:
        for module, first, last in sections:
            lines = []
            keys = {}
            current_n = None
            previous_letter = None
            for pnum in range(first, last + 1):
                page = pdf.pages[pnum-1]
                words = page.extract_words()
                markers = sorted([w for w in words if w['text'].isdigit() and 14 <= w['x0'] <= 18 and 30 < w['top'] < 800], key=lambda w:w['top'])
                icons = {im.name.split('.')[0]: im.image.convert('RGB') for im in reader.pages[pnum-1].images if im.image.width == 16}
                correct_names = {name for name, im in icons.items() if sum(r>180 and g>140 and b<120 for r,g,b in im.getdata())>15}
                for icon in sorted(page.images, key=lambda x:x['top']):
                    if icon['x0']>35 or icon['srcsize']!=(16,16): continue
                    for m in markers:
                        if m['top']<icon['top']: current_n=int(m['text'])
                    if icon['name'] in correct_names:
                        letter = min([w for w in words if re.fullmatch('[A-D]',w['text']) and w['x0']<18], key=lambda w:abs(w['top']-icon['top']-4), default=None)
                        option = letter['text'].lower() if letter and abs(letter['top']-icon['top']-4)<2 else previous_letter
                        assert option, (pnum, icon)
                        keys.setdefault(current_n,[]).append(option)
                letters = [w for w in words if re.fullmatch('[A-D]', w['text']) and w['x0']<18]
                if letters: previous_letter = max(letters,key=lambda w:w['top'])['text'].lower()
                if markers: current_n=int(markers[-1]['text'])
                ptext = pages[pages.index(str(pnum))+1]
                # Remove page furniture and exam/candidate reference headers.
                skip_header = pnum == first
                for line in ptext.splitlines():
                    if skip_header:
                        if 'Attention, l' in line: skip_header=False
                        continue
                    if re.match(r'\s*(?:Evalbox|©Evalbox)',line): continue
                    if not line.strip(): continue
                    lines.append((pnum,line))
            qs=[]; active=None
            for pn,line in lines:
                m=re.match(r'^\s{0,3}(\d{1,2})(?:\s+(.*))?$',line)
                if m and int(m[1])==len(qs)+1:
                    active={'number':int(m[1]),'page':pn,'lines':[m[2] or '']}; qs.append(active)
                elif active: active['lines'].append(line)
            for q in qs:
                raw='\n'.join(q.pop('lines'))
                point=re.search(r'\(0 point / (\d+)\)',raw)
                q['points']=int(point[1]) if point else 1
                raw=re.split(r'\s*\(0 point /',raw)[0].strip()
                if 'Indication/Right answer :' in raw:
                    prompt,answer=raw.split('Indication/Right answer :',1)
                    q.update(prompt=' '.join(prompt.split()), original_kind='qrc', original_answer=' '.join(answer.split()), answers=['a'])
                else:
                    parts=re.split(r'^([A-D])(?: {2,}|$)',raw,flags=re.M)
                    q.update(prompt=' '.join(parts[0].split()), original_kind='qcm',options=[{'id':parts[i].lower(),'text':' '.join(parts[i+1].split())} for i in range(1,len(parts),2)],answers=keys.get(q['number'],[]))
                q['id']=f'annales-2021-{module.lower()}-{q["number"]:02}'
            extracted.append({'id':f'annales-2021-{module.lower()}','module':module,'questions':qs})
    return {'id':'annales-2021','title':'Annales VTC 2021','year':2021,'source_filename':Path(pdf_path).name,'source_sha256':hashlib.sha256(Path(pdf_path).read_bytes()).hexdigest(),'sections':extracted}


if __name__ == '__main__':
    Path(sys.argv[3]).write_text(json.dumps(extract(sys.argv[1],sys.argv[2]),ensure_ascii=False,indent=2)+'\n')
