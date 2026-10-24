"""Adapt the established APS models without replacing their design or appendices."""
from copy import deepcopy
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from lxml import etree

ROOT = Path(__file__).resolve().parents[1] / 'templates_word'
NS = {'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
      'a':'http://schemas.openxmlformats.org/drawingml/2006/main',
      'r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
W = '{'+NS['w']+'}'


def load(name):
    with ZipFile(ROOT/name) as z:
        parts={i.filename:z.read(i) for i in z.infolist()}
    return parts, etree.fromstring(parts['word/document.xml'])


def save(parts,tree,name):
    parts['word/document.xml']=etree.tostring(tree,xml_declaration=True,encoding='UTF-8',standalone=True)
    with ZipFile(ROOT/name,'w',ZIP_DEFLATED) as z:
        for path,data in parts.items():z.writestr(path,data)


def text(p): return ''.join(p.xpath('.//w:t/text()',namespaces=NS))


def put(p,value):
    """Keep paragraph properties and the first run's typography; preserve explicit line breaks."""
    props=p.find(W+'pPr')
    runs=p.findall(W+'r'); rp=next((r.find(W+'rPr') for r in runs if r.find(W+'rPr') is not None),None)
    for child in list(p):
        if child is not props:p.remove(child)
    r=etree.SubElement(p,W+'r')
    if rp is not None:r.append(deepcopy(rp))
    for i,line in enumerate(value.split('\n')):
        if i:etree.SubElement(r,W+'br')
        t=etree.SubElement(r,W+'t');t.set('{http://www.w3.org/XML/1998/namespace}space','preserve');t.text=line


def remove(p):
    parent=p.getparent()
    if parent.tag==W+'tc' and len(parent.findall(W+'p'))==1:put(p,'')
    else:parent.remove(p)


def attestation_afc(source,target):
    parts,tree=load(source)
    for p in tree.xpath('//w:p',namespaces=NS):
        t=text(p)
        if 'Titre à Finalité Professionnelle (TFP) Agent de Prévention et de Sécurité (APS)' in t:
            put(p,'{{ formation_nom }}')
        elif t=='175 heures':put(p,'{{ afc_document_duration }}')
        elif t=='Présentiel + Distanciel':put(p,'Présentiel')
        elif t.startswith('Distanciel + Intégrale Academy'):put(p,t.replace('Distanciel + ',''))
        elif t.startswith('Rappel : La formation APS'):put(p,'Rappel : le suivi du parcours et la présentation aux examens restent soumis au respect des obligations administratives, pédagogiques et réglementaires applicables.')
    save(parts,tree,target)


def attestations_a3p():
    for name,accent,light in [('attestationfina3p.docx','24715B','EDF6F2'),('attestationconducteura3p.docx','2D5B88','EEF3FA'),('attestationstua3p.docx','A9573C','FAF1EB')]:
        parts,tree=load(name)
        for e in tree.iter():
            for attr,value in list(e.attrib.items()):
                if value=='B58A1C':e.set(attr,accent)
                elif value=='F7F2E7':e.set(attr,light)
        for p in list(tree.xpath('//w:p',namespaces=NS)):
            t=text(p)
            if t.startswith('Cette attestation constate le suivi du module'):remove(p)
            elif '{{ nom_complet }}A suivi' in t:put(p,t.replace('{{ nom_complet }}A suivi','{{ nom_complet }}\nA suivi'))
            elif 'DE SECOURISME TACTIQUED’URGENCE' in t:put(p,'DE SECOURISME TACTIQUE\nD’URGENCE (STU)')
        save(parts,tree,name)


def convention():
    parts,tree=load('conventionaps.docx');ps=tree.xpath('//w:p',namespaces=NS)
    changes={
      1:'Convention de formation professionnelle',
      2:'Parcours AFC - Action de formation conventionnée France Travail',
      19:'Et le stagiaire : {{ nom_complet }}, {{ adresse }}, {{ code_postal }} {{ ville }}',
      23:'En exécution de la présente convention, l’organisme de formation s’engage à organiser l’action de formation intitulée :',
      25:'{{ formation_nom }}',
      29:'Qualifications visées : TFP APS, SSIAP 1, SST et formation à l’habilitation électrique.',
      30:'Objectif général de la formation : acquérir les compétences nécessaires aux métiers de la sécurité et préparer les qualifications du parcours.',
      32:'Le parcours AFC associe la prévention et la sécurité privée (APS), la sécurité incendie et l’assistance à personnes (SSIAP 1), le sauvetage secourisme du travail (SST) et la prévention du risque électrique. Il comprend les enseignements et évaluations prévus au programme individuel de formation.',
      36:'Durée individuelle du parcours : {{ afc_total_duration }}. Le détail des séquences et les dates d’examen figurent au programme et au planning individuel.',
      40:'Certification APS : RNCP 36648. Les autres qualifications sont délivrées selon les conditions propres à chaque composante du parcours.',
      43:'• Satisfaire aux prérequis administratifs, linguistiques et médicaux des formations du parcours, tels que précisés dans les programmes remis au stagiaire.',
      48:'L’action de formation se déroulera {{ periode_formation }}, selon le planning individuel remis au stagiaire.',
      50:'Modalités d’organisation de la formation : formation en présentiel.',
      51:'Le parcours comprend les composantes suivantes :',
      52:'• Formation professionnelle APS + SSIAP 1 + SST + habilitation électrique : {{ afc_formation_hours }} heures.',
      53:'• Préparation à l’après-formation : {{ afc_preparation_hours }} heures ; soutien personnalisé : {{ afc_soutien_hours }} heures.',
      54:'• Remise à niveau (RAN) selon le positionnement : {{ afc_ran_duration }}. Durée totale individualisée : {{ afc_total_duration }}.',
      55:'Les programmes et le planning individuel de l’action figurent en annexe de la présente convention.',
      58:'Les intervenants sont les formateurs qualifiés désignés par Intégrale Academy pour les séquences APS, SSIAP 1, SST et habilitation électrique.',
      60:'Qualifications des intervenants : qualifications et habilitations requises pour les matières et les évaluations qu’ils encadrent.',
      79:'Moyens techniques - formation en présentiel :',
      119:'Assurer la surveillance, la prévention et la sécurité des personnes et des biens dans le cadre de la sécurité privée.',
      120:'Prévenir les risques d’incendie, mettre en œuvre les mesures de sécurité incendie et porter assistance aux personnes.',
      121:'Porter secours dans le cadre du SST et prévenir les risques professionnels.',
      122:'Identifier le risque électrique et appliquer les consignes et mesures de prévention correspondant au programme de formation.',
      147:'Les examens APS et SSIAP 1 ainsi que les évaluations SST et d’habilitation électrique sont organisés conformément aux référentiels applicables. Dates d’examen : APS le {{ date_examen_aps }} ; SSIAP 1 le {{ date_examen_ssiap }}. Les horaires et autres évaluations sont précisés au planning.',
      151:'Sous réserve de la réussite aux évaluations et du respect des conditions propres à chaque dispositif, les qualifications visées sont :',
      152:'TFP APS - SSIAP 1 - SST - Formation à l’habilitation électrique.\nUne attestation de fin de formation est remise au stagiaire. L’habilitation électrique est délivrée par l’employeur.',
      154:'Article 7 - Admission et renoncement',
      155:'L’entrée en formation est organisée dans le cadre de l’admission au parcours AFC et du programme individuel de formation. En cas de renoncement, le stagiaire en informe sans délai Intégrale Academy et son conseiller France Travail afin d’examiner les suites de son parcours.',
      157:'FINANCEUR',158:'France Travail',159:'DISPOSITIF',160:'Marché AFC',161:'RESTE À CHARGE',162:'0 €',
      164:'La formation est prise en charge dans le cadre d’un marché France Travail - Action de formation conventionnée (AFC). Référence du dispositif : {{ reference_marche_afc }}. Aucun frais pédagogique n’est dû par le stagiaire.',
      166:'Financement pédagogique',167:'France Travail',168:'Prise en charge dans le cadre du marché AFC.',
      169:'Compte personnel de formation',170:'Non mobilisé',171:'Aucun montant n’est prélevé sur le CPF du stagiaire au titre de cette convention.',
      172:'Participation personnelle',173:'0 €',174:'Aucun paiement demandé au stagiaire.',
      176:'Les conditions de prise en charge et de règlement entre les organismes concernés relèvent du marché France Travail. Une modification de prise en charge ne crée pas de dette de frais pédagogiques à la charge du stagiaire.',
      178:'Engagement du stagiaire',179:'Le stagiaire s’engage à suivre les enseignements, respecter le planning et le règlement intérieur, signer les émargements et participer aux évaluations prévues au parcours.',
      181:'Aucun acompte, échéancier ou règlement de frais pédagogiques n’est demandé au stagiaire.',
      182:'Article 9 - Interruption de stage',
      184:'En cas d’absence, d’interruption ou d’abandon, le stagiaire prévient sans délai le centre et son conseiller France Travail. Les circonstances et les possibilités de poursuite ou de report sont examinées selon les règles du dispositif.',
      191:'En cas de force majeure, le centre et France Travail examinent la situation et les possibilités de report ou d’interruption du parcours. Aucune pénalité ni facturation de frais pédagogiques n’est due par le stagiaire.',
      193:'En cas d’annulation ou d’interruption du fait de l’organisme de formation, le stagiaire est informé des suites proposées en lien avec France Travail.',
      198:'Si l’autorisation préalable CNAPS requise n’est pas obtenue avant l’entrée en formation, le centre examine avec le stagiaire et France Travail les possibilités de report ou d’annulation de l’entrée dans le parcours.',
      202:'En cas d’échec à une évaluation ou à un examen, les possibilités de rattrapage et de nouvelle présentation sont étudiées avec l’équipe pédagogique et France Travail, selon les référentiels et les conditions du marché.',
      208:'En cas de difficulté ou de différend, le stagiaire et l’organisme de formation recherchent d’abord une solution amiable, en lien avec France Travail lorsque la situation concerne le parcours AFC. À défaut, le litige relève des juridictions compétentes.',
      209:'Signature de la convention de formation',
      257:'L’organisme de formation informe France Travail des absences et incidents affectant le parcours. Tout événement non justifié peut faire l’objet des mesures prévues au règlement intérieur et au dispositif AFC.'
    }
    for index,value in changes.items():put(ps[index],value)
    # Article 9 occupied the tail of a payment paragraph in the APS source.
    for child in list(ps[182]):
        if child.tag==W+'pPr':ps[182].remove(child)
    heading=ps[201].find(W+'pPr')
    if heading is not None:ps[182].insert(0,deepcopy(heading))
    if ps[182].find(W+'pPr/'+W+'pageBreakBefore') is None:
        etree.SubElement(ps[182].find(W+'pPr'),W+'pageBreakBefore')
    for run in ps[182].findall(W+'r'):
        rp=run.find(W+'rPr')
        if rp is not None:run.remove(rp)
        source=ps[201].find('.//'+W+'rPr')
        if source is not None:run.insert(0,deepcopy(source))
    # Keep the original page break before Article 10 and the complete signature block.
    deleted=set(range(74,79))|set(range(84,117))|set(range(130,142))|set(range(186,191))|{194,195,199,200,203,204,205}
    for i in sorted(deleted,reverse=True):remove(ps[i])
    for p in tree.xpath('//w:p',namespaces=NS):
        t=text(p)
        if 'présent contrat' in t:put(p,t.replace('présent contrat','présente convention'))
    save(parts,tree,'conventionafc.docx')


def convocation():
    parts,tree=load('convocationafc.docx');ps=tree.xpath('//w:p',namespaces=NS)
    # Work from the already customized call-up, keeping signatures and the access map.
    changes={
      0:'CONVOCATION EN FORMATION',
      1:'Parcours AFC\nAPS + SSIAP 1 + SST + Habilitation électrique',
      11:'Document officiel de convocation au parcours AFC',
      13:'PARCOURS AFC',
      16:'{{ nom_complet }}\n{{ code_postal }} {{ ville }}',
      20:'Votre période individuelle de formation : {{ periode_formation }}.\n\nPrésentez-vous le {{ date_convocation }} à {{ heure_convocation }} au centre de formation.\n\nLe parcours comprend APS, SSIAP 1, SST et formation à l’habilitation électrique. Les horaires figurent au planning individuel remis par le centre.',
      25:'Parcours AFC',
      28:'Intégrale Academy\n54 chemin du Carreou\n83480 PUGET-SUR-ARGENS',
      30:'En cas d’indisponibilité ou de renoncement, merci de nous avertir dès que possible au 04 22 47 07 68 ou par email à ecole@integraleacademy.com.',
      42:'{{ nom_complet }}\n{{ code_postal }} {{ ville }}',
      52:'Intégrale Academy\n54 chemin du Carreou\n83480 PUGET-SUR-ARGENS',
      56:'Intégrale Academy\n54 chemin du Carreou\n83480 PUGET-SUR-ARGENS',
      59:'Examen APS : chemise blanche, veste noire, pantalon noir, chaussures noires et cravate de sécurité.\n\nExamen SSIAP 1 : tenue correcte, pantalon et chaussures fermées, adaptés aux épreuves pratiques.',
      78:'En cas de documents manquants, non conformes ou transmis hors délai, contactez immédiatement le centre. L’entrée en formation ou l’accès aux épreuves peut être reporté ou refusé si les prérequis ne sont pas réunis.'
    }
    for i,value in changes.items():put(ps[i],value)
    # The SSIAP badge (rId8) is not the Academy letterhead.
    for drawing in list(tree.xpath('//w:drawing[.//a:blip[@r:embed="rId8"]]',namespaces=NS)):
        drawing.getparent().remove(drawing)
    parts.pop('word/media/image1.png',None)
    rel=etree.fromstring(parts['word/_rels/document.xml.rels'])
    for e in list(rel):
        if e.get('Id')=='rId8':rel.remove(e)
    parts['word/_rels/document.xml.rels']=etree.tostring(rel,xml_declaration=True,encoding='UTF-8',standalone=True)
    # Explicit, non-fixed row heights and comfortable paragraph spacing.
    for height in tree.xpath('//w:trHeight',namespaces=NS):height.getparent().remove(height)
    for p in tree.xpath('//w:p',namespaces=NS):
        if not text(p):continue
        prop=p.find(W+'pPr')
        if prop is None:prop=etree.Element(W+'pPr');p.insert(0,prop)
        sp=prop.find(W+'spacing')
        if sp is None:sp=etree.SubElement(prop,W+'spacing')
        sp.set(W+'after','130');sp.set(W+'line','260');sp.set(W+'lineRule','auto')
    save(parts,tree,'convocationafc.docx')


if __name__=='__main__':
    convention()
    attestation_afc('attestationentreeaps.docx','attestationentreeafc.docx')
    attestation_afc('attestationfinaps.docx','attestationfinafc.docx')
    attestations_a3p()
    convocation()
