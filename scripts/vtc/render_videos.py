"""Build eight visual revision capsules entirely locally.

No text or image is sent to a speech service. The current edition is silent,
with timed explanations burnt into the video and an accessible transcript.
Build-time dependencies: Pillow and ffmpeg.
"""
import concurrent.futures, json, os, re, subprocess, textwrap
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'elearning_native/vtc'
MEDIA=OUT/'assets/media/vtc'
WORK=Path(os.environ.get('VTC_VIDEO_WORK',str(ROOT.parent/'vtc-video-local')))
WORK.mkdir(exist_ok=True)
FONT='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
BOLD='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'

def draw_text(draw, content, x, y, width, size, color, bold=False):
    font=ImageFont.truetype(BOLD if bold else FONT,size)
    lines=[];line=''
    for word in content.split():
        trial=(line+' '+word).strip()
        if draw.textlength(trial,font=font)>width and line:
            lines.append(line);line=word
        else:line=trial
    if line:lines.append(line)
    for line in lines:
        draw.text((x,y),line,font=font,fill=color);y+=int(size*1.35)
    return y

def timestamp(value):
    ms=round(value*1000);h,ms=divmod(ms,3600000);m,ms=divmod(ms,60000);s,ms=divmod(ms,1000)
    return f'{h:02}:{m:02}:{s:02}.{ms:03}'

def frame(module,number,q,caption,show_answer):
    im=Image.new('RGB',(1280,720),'#f8f5fd');d=ImageDraw.Draw(im)
    d.rectangle((0,0,1280,10),fill='#7045bd')
    draw_text(d,'INTÉGRALE ACADEMY  /  CHAUFFEUR VTC',45,29,930,17,'#513283',True)
    draw_text(d,'MODULE '+module['letter']+' · '+str(number+1)+'/4',1050,29,200,17,'#513283')
    draw_text(d,module['title'],45,78,705,29,'#241a38',True)
    draw_text(d,'UNE SITUATION, UNE DÉCISION',45,174,730,16,'#7045bd',True)
    y=draw_text(d,q['prompt'],45,212,705,23,'#241a38')
    if show_answer:
        y=max(y+22,335)
        d.rounded_rectangle((45,y,755,550),16,fill='#ede4fa')
        draw_text(d,'LE BON RÉFLEXE',65,y+15,660,15,'#7045bd',True)
        end=draw_text(d,q['answer_text'],65,y+47,664,22,'#452c69',True)
        assert end<=550,(module['letter'],number,end)
    else:
        draw_text(d,'Que choisiriez-vous ?\nFaites une pause pour réfléchir.',45,max(y+35,380),690,24,'#7045bd',True)
    pic=ImageOps.fit(Image.open(OUT/'assets'/module['image']).convert('RGB'),(435,446),centering=(.5,.4))
    im.paste(pic,(800,84))
    for i in range(4):d.rounded_rectangle((45+i*299,570,330+i*299,575),2,fill='#7045bd' if i<=number else '#d9cee9')
    d.rectangle((0,590,1280,720),fill='#171021')
    end=draw_text(d,caption,65,607,1150,24,'white')
    assert end<714,(module['letter'],number,caption,end)
    return im

def split_explanation(content):
    words=content.split(); chunks=[]
    while words:
        n=min(24,len(words));chunks.append(' '.join(words[:n]));words=words[n:]
    return chunks

def render(module,questions):
    letter=module['letter'];folder=WORK/letter;folder.mkdir(exist_ok=True)
    chunks=[next(q for q in questions if q['ref']==letter+f'.{n:02}') for n in [1,4,8,12]]
    cues=[];offset=0;paths=[]
    for i,q in enumerate(chunks):
        captions=[('Lisez la situation. Choisissez mentalement votre réponse avant de poursuivre.',False,10)]
        captions.extend((caption,True,max(7,len(caption.split())*.43+1.5)) for caption in split_explanation(q['answer_text']+'. '+q['explanation']))
        for caption,show,seconds in captions:
            im=frame(module,i,q,caption,show)
            path=folder/f'{len(paths):02}.png';im.save(path)
            if not paths:im.save(MEDIA/f'capsule-{letter.lower()}.jpg',quality=88)
            paths.append((path,seconds));cues.append({'start':offset,'end':offset+seconds,'text':caption});offset+=seconds
    concat=folder/'frames.txt'
    concat.write_text(''.join(f"file '{p}'\nduration {seconds:.3f}\n" for p,seconds in paths)+f"file '{paths[-1][0]}'\n")
    target=MEDIA/f'capsule-{letter.lower()}.mp4'
    subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-f','concat','-safe','0','-i',str(concat),'-t',str(offset),'-vf','fps=12,format=yuv420p','-c:v','libx264','-preset','veryfast','-crf','27','-tune','stillimage','-threads','2','-an','-movflags','+faststart',str(target)],check=True)
    duration=float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','default=noprint_wrappers=1:nokey=1',str(target)],text=True))
    (MEDIA/f'capsule-{letter.lower()}.vtt').write_text('WEBVTT\n\n'+''.join(f"{timestamp(c['start'])} --> {timestamp(c['end'])}\n{c['text']}\n\n" for c in cues))
    print('VTC',letter,round(duration,1),'seconds — visual / no audio',flush=True)
    return letter,{'src':f'media/vtc/capsule-{letter.lower()}.mp4','poster':f'media/vtc/capsule-{letter.lower()}.jpg',
      'captions':f'media/vtc/capsule-{letter.lower()}.vtt','duration_seconds':duration,
      'transcript':'\n\n'.join(q['prompt']+' '+q['answer_text']+'. '+q['explanation'] for q in chunks),
      'voice':None,'audio':False,'burned_captions':True}

def main():
    bank=json.loads((OUT/'manual_bank.json').read_text());questions=[]
    for row in (ROOT/'scripts/vtc/questions.txt').read_text().splitlines():
        if not row or row.startswith('#'):continue
        ref,prompt,answer,_,_,reason=row.split('|')
        questions.append({'ref':ref,'prompt':prompt,'answer_text':answer,'explanation':reason})
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        manifest=dict(pool.map(lambda module:render(module,questions),bank['modules']))
    (OUT/'video_manifest.json').write_text(json.dumps(dict(sorted(manifest.items())),ensure_ascii=False,indent=2))
    print('DONE',len(manifest),'visual capsules',flush=True)
if __name__=='__main__':main()
