"""Authoring helpers. Answer keys never reach the learner before marking."""
import hashlib, random

def question(ref, context, prompt, good, bad1, bad2, explanation, **extra):
    assert len({good,bad1,bad2}) == 3, (ref,prompt)
    seed=hashlib.sha256((ref+context+prompt).encode()).hexdigest()[:18]
    opts=[{'id':hashlib.sha256((seed+str(i)).encode()).hexdigest()[:10],'text':t} for i,t in enumerate([good,bad1,bad2])]
    answer=opts[0]['id'];random.Random(seed).shuffle(opts)
    return {'id':'q-'+seed,'kind':'single','competency':ref,'context':context,'stage':'Analyser et décider',
            'prompt':prompt,'options':opts,'answer':answer,'explanation':explanation,
            'coaching':'Reprenez les faits du dossier, identifiez ce qui est demandé et vérifiez la limite de votre réponse. '+explanation,
            'consequences':{opt['id']:('Votre choix permet de poursuivre sur une base cohérente.' if opt['id']==answer else 'Ce choix ne résout pas correctement la situation. Voici le point à reprendre avant de poursuivre.') for opt in opts},**extra}

def sorting(ref, title, context, categories, rows, why):
    seed=hashlib.sha256((ref+title+context).encode()).hexdigest()[:18]
    options=[{'id':f'c{i}','text':c} for i,c in enumerate(categories)]
    return {'id':'s-'+seed,'kind':'sort','stage':'Contrôler les éléments','competency':ref,
            'context':context,'prompt':title,'options':options,
            'rows':[{'id':f'r{i}','text':text,'answer':f'c{cat}'} for i,(text,cat) in enumerate(rows)],
            'explanation':why,'coaching':why}

def order(ref, context, steps):
    seed=hashlib.sha256((ref+context).encode()).hexdigest()[:18]
    rows=[{'id':f'r{i}','text':text,'answer':f'p{i}'} for i,text in enumerate(steps)]
    random.Random(seed).shuffle(rows)
    return {'id':'o-'+seed,'kind':'order','competency':ref,'stage':'Construire la méthode','context':context,
            'prompt':'Retrouvez l’ordre des opérations dans cette procédure pédagogique.',
            'options':[{'id':f'p{i}','text':f'Étape {i+1}'} for i in range(len(steps))],'rows':rows,
            'explanation':' → '.join(steps),'coaching':'Le repérage des faits précède le choix ; la vérification du résultat clôt la procédure.'}

def topic(title, paragraphs, example, method, pitfall):
    return {'title':title,'paragraphs':paragraphs,'example':example,'method':method,'pitfall':pitfall}

def money(value):
    return f'{value:.2f} €'.replace('.',',')

def numbers(ref, context, prompt, correct, wrong1, wrong2, explanation, unit=' €', **extra):
    def fmt(x):return f'{x:.2f}'.replace('.',',')+unit
    return question(ref,context,prompt,fmt(correct),fmt(wrong1),fmt(wrong2),explanation,**extra)
