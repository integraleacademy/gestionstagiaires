"""Reviewed sequence summaries; one Academy capsule per sequence."""
import json
from pathlib import Path
from urllib.parse import urlparse, parse_qs
ROOT=Path(__file__).resolve().parent
MAP=json.loads((ROOT/'course_map.json').read_text())
VIDEOS=[]
def add(m,s,title,icon,hook,rules,case,options,answer,actions,recap,lines):
    section=MAP[m-1]['sections'][s-1]
    # The synthesis sits in the third content activity, immediately before the question.
    url=section['activities'][2]['url']; p=urlparse(url); q=parse_qs(p.query)
    VIDEOS.append(dict(module=m,sequence=s,section_title=section['title'],title=title,icon=icon,
       course_id=p.path.split('/')[4],course_version=q['version'][0],activity_id=q['activity'][0],
       id=f'aps-m{m}-s{s:02}-20260925', scenes=[
        dict(kind='hero',label='LES ESSENTIELS APS',headline=hook,lines=lines[0]),
        dict(kind='rules',label='COMPRENDRE',headline='Trois repères.',items=rules,lines=lines[1]),
        dict(kind='case',label='MISE EN SITUATION',headline=case,items=options,lines=lines[2],pause=5),
        dict(kind='answer',label='LE BON RÉFLEXE',headline=answer,items=actions,lines=lines[3]),
        dict(kind='recap',label='À RETENIR',headline=recap,lines=lines[4])]))

add(1,2,'Le Livre VI : votre cadre de travail','book','Un métier.\nUn cadre légal.',
 ['Les activités réglementées','Les conditions d’exercice','La déontologie et le contrôle'],
 'Une consigne peut-elle\ntout autoriser ?', ['A · Oui, si elle est écrite.','B · Non, la loi reste la limite.'],
 'La loi fixe la limite.', ['Vérifier le cadre','Demander une clarification','Refuser un acte illégal'],
 'Identifier.\nVérifier.\nAgir dans le cadre.',[
 ['Le Livre six du Code de la sécurité intérieure encadre les activités privées de sécurité. Il donne les repères pour savoir qui peut exercer et dans quelles conditions.'],
 ['Il définit les activités réglementées, les conditions applicables aux professionnels, puis les obligations et les contrôles.','Le CNAPS délivre des autorisations et contrôle la profession. L’employeur organise la mission, sans pouvoir vous donner des pouvoirs de police.'],
 ['Votre responsable vous remet une consigne écrite qui demande un acte illégal. Devez-vous l’appliquer ? Prenez quelques secondes.'],
 ['La réponse B. Une consigne ne rend pas un acte illégal autorisé.','Demandez une clarification, refusez l’acte manifestement illégal et rendez compte par les voies prévues.'],
 ['Votre méthode : identifier la mission, vérifier le cadre, puis agir dans les limites de la loi.']])
add(1,3,'Se former, puis être autorisé à exercer','badge','Se former.\nPuis exercer.',
 ['Accès à la formation','Aptitude et moralité','Carte adaptée et valide'],
 'Diplôme obtenu :\npuis-je prendre le poste ?', ['A · Oui, le diplôme suffit.','B · Il faut vérifier le droit d’exercer.'],
 'Le diplôme ne suffit pas.', ['Vérifier la carte','Contrôler l’activité autorisée','Anticiper le renouvellement'],
 'Formation.\nAutorisation.\nVérification.',[
 ['Entrer en formation et exercer une activité de sécurité privée sont deux étapes différentes. Ne confondez pas leurs justificatifs.'],
 ['Avant la formation, une autorisation du CNAPS est en principe nécessaire, sauf situation prévue par les textes.','L’aptitude professionnelle et la moralité sont examinées. Pour exercer, la carte professionnelle doit être valide et correspondre à l’activité.'],
 ['Vous venez d’obtenir votre diplôme. Une entreprise propose une mission dès demain, mais votre carte n’est pas encore délivrée. Pouvez-vous commencer ?'],
 ['La réponse B. Le diplôme ne remplace pas la carte professionnelle requise pour le poste.','Vérifiez votre situation avec l’employeur et le CNAPS. Une autorisation provisoire destinée à la formation ne permet pas d’être affecté à une mission réglementée.'],
 ['Retenez trois étapes : se former, obtenir le droit d’exercer, puis vérifier sa validité avant l’affectation.']])
add(1,4,'Exercice exclusif et service interne','building','Une mission\nbien délimitée.',
 ['Le périmètre de la prestation','Le statut du service interne','Les obligations des agents'],
 'Quitter le contrôle d’accès\npour tenir la caisse ?', ['A · Clarifier la demande avant d’agir.','B · Partir immédiatement.'],
 'Préserver la mission.', ['Expliquer le risque','Contacter le responsable','Organiser une solution conforme'],
 'Mission claire.\nPoste assuré.\nCadre vérifié.',[
 ['Une prestation de sécurité doit rester dans son périmètre. La facilité du moment ne justifie pas de mélanger les fonctions.'],
 ['Le principe d’exclusivité encadre les activités des entreprises de sécurité.','Un service interne protège sa propre entreprise et bénéficie de règles particulières. Cela ne supprime ni les obligations des agents ni les titres requis.'],
 ['Vous surveillez un accès. Le client vous demande d’abandonner ce poste pour tenir une caisse. Quel réflexe choisissez-vous ?'],
 ['La réponse A. Expliquez que le poste doit rester assuré et contactez votre responsable.','Il faut vérifier le cadre de la mission, le statut du service et organiser une solution conforme. Une demande du client ne suffit pas à modifier toutes vos obligations.'],
 ['Avant de changer de tâche : vérifiez votre mission, maintenez la sécurité du poste et faites clarifier la demande.']])
add(1,5,'Neutralité et égalité de traitement','balance','Des faits.\nPas des préjugés.',
 ['Des critères objectifs','Une règle explicable','Une attitude respectueuse'],
 'Deux visiteurs sans badge.\nVous connaissez l’un d’eux.', ['A · Vous laissez passer votre connaissance.','B · Vous vérifiez les autorisations des deux.'],
 'Appliquer les mêmes critères.', ['Expliquer la règle','Vérifier les autorisations','Décider sur des éléments objectifs'],
 'Observer les faits.\nExpliquer la règle.\nRespecter chacun.',[
 ['Une décision de sécurité doit pouvoir s’expliquer par des faits. Votre sympathie, vos opinions et les préjugés ne sont pas des critères professionnels.'],
 ['Appuyez-vous sur l’autorisation d’accès, la consigne applicable et les risques constatés.','Parlez calmement. Respectez la dignité de chacun et écartez les critères discriminatoires.'],
 ['Deux visiteurs arrivent sans badge. Vous connaissez personnellement l’un d’eux. Lequel de ces comportements respecte la neutralité ?'],
 ['La réponse B : vérifiez les autorisations des deux personnes selon les mêmes critères.','Le résultat peut différer si leurs autorisations sont différentes. Ce sont les éléments objectifs qui justifient votre décision, jamais une préférence personnelle.'],
 ['La bonne posture : observer les faits, expliquer la règle et respecter chaque personne.']])
add(1,6,'Tenue et identification professionnelle','badge','Identifiable.\nSans confusion.',
 ['Une tenue conforme','Une identification visible','Aucune imitation d’autorité'],
 'Un écusson évoque la police.\n« C’est plus dissuasif », dit-on.', ['A · Faire corriger la présentation.','B · Le conserver pour impressionner.'],
 'Affirmer votre rôle réel.', ['Signaler l’élément ambigu','Utiliser la tenue conforme','Se présenter comme agent de sécurité'],
 'Sécurité privée.\nRôle lisible.\nIdentification claire.',[
 ['Votre tenue doit permettre de comprendre immédiatement votre rôle : vous êtes un professionnel de la sécurité privée.'],
 ['Les marquages et l’identification doivent respecter les règles applicables à votre activité.','Ni la tenue ni les insignes ne doivent créer de confusion avec la police, la gendarmerie ou une autre autorité publique.'],
 ['On vous propose un écusson ressemblant à celui de la police, sous prétexte d’être plus dissuasif. Que faites-vous ?'],
 ['La réponse A. Faites corriger cet élément et utilisez une présentation conforme.','Au contact du public, annoncez votre fonction réelle. Votre uniforme vous identifie ; il ne vous attribue aucun pouvoir de police.'],
 ['Avant la prise de poste, vérifiez la tenue, la visibilité de l’identification et l’absence de confusion avec un service public.']])
add(1,7,'Armement : respecter le cadre autorisé','shield','Une arme ?\nJamais par initiative.',
 ['Des autorisations précises','Une formation adaptée','Des règles de port et d’usage'],
 'Une ronde vous inquiète.\nVous avez une arme personnelle.', ['A · Vous l’emportez par précaution.','B · Vous signalez le risque au responsable.'],
 'Signaler, sans improviser.', ['Alerter le responsable','Adapter l’organisation','Respecter le cadre autorisé'],
 'Autorisation.\nFormation.\nResponsabilité.',[
 ['Être agent de sécurité ne donne pas, à lui seul, le droit de porter une arme pendant une mission.'],
 ['Le cadre dépend de l’activité, de la catégorie d’arme et des autorisations requises.','Il impose des compétences adaptées et des règles de stockage, de transport, de port et de traçabilité. Une autorisation de port n’autorise pas tout usage.'],
 ['Une ronde vous inquiète. Vous envisagez d’emporter une arme personnelle pour vous rassurer. Quel est le bon réflexe ?'],
 ['La réponse B. Signalez le risque et faites adapter l’organisation de la mission.','N’improvisez aucun armement. L’usage éventuel d’une arme reste soumis à des conditions légales strictes et engage votre responsabilité.'],
 ['Retenez : une mission préparée, un cadre autorisé et aucune initiative personnelle d’armement.']])
add(1,8,'Contrôles, consignes et responsabilités','clipboard','Être conforme.\nRendre compte.',
 ['Des titres valides','Des pratiques conformes','Une traçabilité sincère'],
 'On vous demande d’effacer\nun incident du rapport.', ['A · Refuser la falsification et signaler.','B · Effacer puisque le responsable demande.'],
 'Préserver les faits.', ['Conserver une trace fidèle','Signaler la demande','Corriger sans falsifier'],
 'Vérifier.\nTracer.\nAssumer ses actes.',[
 ['Le contrôle de la profession ne porte pas seulement sur les documents. Les pratiques sur le terrain doivent aussi respecter les règles.'],
 ['Le CNAPS contrôle les professionnels et peut engager des procédures disciplinaires.','Un même fait peut aussi relever de la justice pénale. Les responsabilités dépendent des actes commis et des textes applicables.'],
 ['Après un incident, un responsable vous demande d’effacer les faits gênants de la main courante. Quelle conduite choisissez-vous ?'],
 ['La réponse A. Refusez de falsifier le rapport et signalez la demande par la voie appropriée.','Une correction doit rester identifiable et fidèle aux faits. Conservez une trace professionnelle de ce que vous avez observé et réalisé.'],
 ['Des titres valides, une pratique conforme et un compte rendu sincère : trois repères essentiels pour exercer.']])
add(2,1,'Infraction et responsabilité personnelle','book','Comprendre les faits.\nRépondre de ses actes.',
 ['Un comportement interdit','Une qualification prévue par les textes','Une responsabilité personnelle'],
 'Un collègue propose\nde cacher une erreur.', ['A · Vous acceptez par solidarité.','B · Vous relatez précisément les faits.'],
 'Rester factuel.', ['Décrire ce qui s’est passé','Distinguer faits et suppositions','Transmettre sans dissimuler'],
 'Les faits d’abord.\nLa loi comme cadre.\nVos actes vous engagent.',[
 ['Une infraction est un comportement interdit par un texte pénal. Les contraventions, les délits et les crimes sont les trois catégories à connaître.'],
 ['La qualification dépend des textes et des circonstances, pas seulement de votre impression de gravité.','Chacun répond de ses propres actes. L’intention compte, mais une imprudence peut aussi engager une responsabilité lorsque la loi le prévoit.'],
 ['Après une erreur ayant causé un dommage, un collègue vous propose de modifier le récit pour protéger l’équipe. Que faites-vous ?'],
 ['La réponse B. Décrivez précisément les faits, sans les cacher ni accuser sans preuve.','Signalez ce que vous savez, distinguez ce que vous avez vu de ce qu’on vous a rapporté et suivez la procédure.'],
 ['L’ordre d’un collègue ou d’un responsable n’efface pas votre responsabilité personnelle.']])
add(2,2,'La légitime défense et ses limites','balance','Se protéger.\nSans punir.',
 ['Une atteinte injustifiée','Une défense au même moment','Une réponse nécessaire et proportionnée'],
 'L’agression est terminée.\nLa personne s’éloigne.', ['A · Vous la poursuivez pour la punir.','B · Vous cessez la riposte et alertez.'],
 'La défense n’est pas la vengeance.', ['Faire cesser la riposte','Se mettre en sécurité','Alerter et rendre compte'],
 'Nécessaire.\nSimultanée.\nProportionnée.',[
 ['La légitime défense vise à protéger une personne contre une atteinte injustifiée. Elle ne donne pas le droit de punir l’agresseur.'],
 ['La réaction doit intervenir au moment de l’atteinte, être nécessaire et rester proportionnée à sa gravité.','Pour défendre seulement un bien, les conditions sont strictes : l’acte doit être strictement nécessaire et ne peut pas être un homicide volontaire.'],
 ['L’agression vient de cesser et la personne s’éloigne. Pouvez-vous la poursuivre pour lui donner une leçon ?'],
 ['La réponse B. Une riposte punitive après la fin de l’attaque n’est pas de la légitime défense.','Mettez-vous en sécurité, alertez les services compétents et rendez compte des faits.'],
 ['Retenez les trois critères ensemble : une réaction nécessaire, simultanée et proportionnée.']])
add(2,3,'L’état de nécessité','shield','Face au danger.\nSauvegarder.',
 ['Un danger actuel ou imminent','Un acte nécessaire','Des moyens proportionnés'],
 'Un danger menace une personne.\nExiste-t-il une solution moins dommageable ?', ['A · Vérifier les moyens utiles et sûrs.','B · Toute action devient automatiquement permise.'],
 'Choisir une réponse nécessaire.', ['Identifier le danger','Retenir le moyen adapté','Alerter et expliquer les faits'],
 'Danger réel.\nActe nécessaire.\nMoyens proportionnés.',[
 ['L’état de nécessité peut justifier un acte accompli pour sauvegarder une personne ou un bien face à un danger actuel ou imminent.'],
 ['Le danger doit être réel et proche. L’acte doit être nécessaire à la sauvegarde.','Les moyens employés ne doivent pas être disproportionnés par rapport à la menace. Une simple commodité ne suffit pas.'],
 ['Une personne est menacée par un danger immédiat. Avant une action dommageable, faut-il rechercher une solution utile, plus sûre et moins dommageable ?'],
 ['La réponse A. L’urgence ne rend pas automatiquement tous les moyens autorisés.','Choisissez une action adaptée, sans exposition inutile, alertez les secours et décrivez ensuite le danger et les raisons de votre décision.'],
 ['Trois questions : quel danger, pourquoi cet acte, et les moyens étaient-ils proportionnés ?']])
add(2,4,'Protéger les personnes et respecter les libertés','balance','Protéger.\nRespecter les droits.',
 ['L’intégrité physique','La dignité de chacun','La liberté d’aller et venir'],
 'Un visiteur refuse d’attendre.\nPeut-on l’enfermer pour obtenir son nom ?', ['A · Oui, pour faciliter le rapport.','B · Non, cette raison ne le permet pas.'],
 'Une consigne ne crée pas un pouvoir.', ['Expliquer calmement','Éviter toute contrainte injustifiée','Contacter les autorités si nécessaire'],
 'Respect.\nNécessité.\nCadre légal.',[
 ['Toute personne conserve ses droits, même lorsqu’elle est soupçonnée d’une infraction. Votre mission n’autorise ni humiliation ni violence injustifiée.'],
 ['Protégez l’intégrité physique et la dignité. N’entravez pas l’accès aux secours.','Une restriction de liberté exige un fondement légal précis. Une consigne interne ne crée pas un pouvoir général de retenir quelqu’un.'],
 ['Un visiteur souhaite repartir. Vous voulez l’enfermer dans un bureau pour obtenir son identité et terminer votre rapport. Est-ce permis pour cette seule raison ?'],
 ['La réponse B. La facilité administrative ne justifie pas une privation de liberté.','Expliquez la situation et contactez les autorités compétentes si nécessaire. Toute mesure de contrainte doit avoir un fondement légal et rester dans ses limites.'],
 ['Une intervention professionnelle protège la sécurité tout en respectant les droits des personnes.']])
add(2,5,'Assister et donner une alerte utile','phone','Aider.\nSans créer un autre danger.',
 ['Protéger sans se mettre en péril','Déclencher les secours','Transmettre les faits utiles'],
 'Une personne s’effondre.\nVous constatez un danger à proximité.', ['A · Évaluer le danger et déclencher l’aide.','B · Rédiger d’abord la main courante.'],
 'L’aide ne doit pas attendre.', ['Évaluer et protéger','Alerter immédiatement','Guider les secours'],
 'Protéger.\nAlerter.\nAssister selon sa formation.',[
 ['Face à une personne en péril, l’inaction volontaire peut être sanctionnée si une assistance était possible sans risque pour vous ou pour les tiers.'],
 ['L’aide peut consister à agir personnellement ou à provoquer un secours.','Il faut aussi prévenir, lorsque c’est possible sans risque, un crime ou un délit contre l’intégrité corporelle. Votre sécurité et celle des tiers restent essentielles.'],
 ['Une personne s’effondre près d’une zone dangereuse. Commencez-vous par rédiger la main courante ou par évaluer la situation et déclencher l’aide ?'],
 ['La réponse A. Évaluez le danger, protégez si possible et alertez les secours.','Donnez le lieu exact, la situation observée et les risques présents. Suivez leurs instructions et réalisez seulement les gestes adaptés que vous maîtrisez.'],
 ['Le compte rendu vient après l’action urgente. Il ne remplace jamais une assistance possible.']])
add(2,6,'Rester dans son rôle : aucune usurpation','badge','Votre rôle réel.\nAucun pouvoir inventé.',
 ['Une présentation honnête','Des termes professionnels','Le recours aux autorités compétentes'],
 '« Vous êtes en garde à vue ! »\nUn collègue emploie cette formule.', ['A · Vous reprenez la formule pour l’aider.','B · Vous corrigez la confusion.'],
 'Nommer sa fonction réelle.', ['Se présenter clairement','Expliquer la consigne','Appeler les autorités si nécessaire'],
 'Agent de sécurité.\nMission privée.\nPouvoirs limités.',[
 ['Un agent de sécurité privée ne doit pas se présenter comme une autorité publique ni accomplir les actes réservés à celle-ci sans droit.'],
 ['N’inventez pas de qualité de policier, de pouvoir de verbalisation ou de placement en garde à vue.','Les mots, les insignes et le comportement doivent correspondre à votre fonction réelle.'],
 ['Un collègue annonce à un visiteur : vous êtes en garde à vue. Quelle est votre réaction professionnelle ?'],
 ['La réponse B. Corrigez la confusion et rappelez votre rôle réel.','Présentez-vous comme agent de sécurité du site. Expliquez la règle applicable et appelez les forces de l’ordre si la situation le nécessite. Ne prétendez pas exercer leurs pouvoirs.'],
 ['Une présentation claire protège le public, votre entreprise et votre responsabilité.']])
add(2,7,'Objets trouvés et appropriations frauduleuses','lock','Trouvé ne veut pas dire\nà vous.',
 ['Respecter le bien d’autrui','Éviter l’usage personnel','Assurer une remise traçable'],
 'Un portefeuille est oublié.\nPersonne ne semble le réclamer.', ['A · Vous appliquez la procédure des objets trouvés.','B · Vous le gardez à la fin du service.'],
 'Conserver pour restituer.', ['Sécuriser selon la procédure','Tracer la découverte','Remettre au service désigné'],
 'Aucun bénéfice personnel.\nUne trace.\nUne remise conforme.',[
 ['Le vol est la soustraction frauduleuse du bien d’autrui. Un objet trouvé ou laissé sans surveillance ne devient pas automatiquement votre propriété.'],
 ['Ne gardez pas un bien pour vous et ne détournez pas un objet qui vous a été confié.','Les qualifications pénales dépendent des faits. Une faible valeur ou une habitude du service ne suffit pas à rendre l’appropriation licite.'],
 ['Vous trouvez un portefeuille pendant une ronde. À la fin du service, personne ne l’a réclamé. Que faites-vous ?'],
 ['La réponse A. Appliquez la procédure des objets trouvés.','Sécurisez le bien, notez le lieu et l’heure de découverte, puis remettez-le au service désigné avec une trace. Ne l’utilisez pas et ne prélevez rien.'],
 ['La bonne conduite protège le bien, son propriétaire et la traçabilité de votre intervention.']])
add(2,8,'Protéger les outils et les données','screen','Un accès autorisé.\nUn usage professionnel.',
 ['Votre compte personnel','Le périmètre de votre mission','La préservation des traces'],
 'Une clé USB inconnue\nest retrouvée au poste.', ['A · Vous la branchez pour chercher le propriétaire.','B · Vous signalez sans la connecter.'],
 'Signaler sans explorer.', ['Ne pas brancher le support','Prévenir le service compétent','Conserver les éléments utiles'],
 'Ne pas contourner.\nNe pas altérer.\nSignaler.',[
 ['Les outils de contrôle d’accès, de vidéosurveillance et de main courante contiennent des données sensibles pour la sécurité du site.'],
 ['Utilisez votre propre compte, dans les limites de votre mission, sans partager votre mot de passe.','Un accès frauduleux, une entrave au système ou une modification frauduleuse de données peuvent constituer des infractions. Ne cherchez jamais à contourner une restriction.'],
 ['Une clé USB inconnue est retrouvée au poste. Faut-il la brancher pour rechercher son propriétaire ?'],
 ['La réponse B. Ne la connectez pas. Prévenez le service compétent et suivez la procédure.','En cas d’incident, notez les faits et l’heure. Ne supprimez pas les traces et ne lancez pas votre propre enquête informatique.'],
 ['Restez dans votre rôle : protéger, préserver et signaler.']])
add(2,9,'La justice pénale et votre rôle de témoin','court','Observer les faits.\nLa justice décide.',
 ['Contravention · tribunal de police','Délit · tribunal correctionnel','Crime · juridiction criminelle'],
 'Vous rédigez après un incident.\nQuelle formulation est utile ?', ['A · « J’ai vu cette personne prendre l’objet. »','B · « Cette personne est forcément coupable. »'],
 'Décrire sans préjuger.', ['Dater et localiser','Relater les faits observés','Distinguer les informations rapportées'],
 'Précision.\nObjectivité.\nTraçabilité.',[
 ['Votre compte rendu peut être utile à une procédure. Votre rôle consiste à relater les faits ; la justice apprécie les responsabilités.'],
 ['Les contraventions relèvent du tribunal de police, les délits du tribunal correctionnel.','Les crimes sont jugés par une cour d’assises ou une cour criminelle départementale selon les règles applicables. Le procureur décide des suites d’une enquête, et le tribunal juge lorsqu’il est saisi.'],
 ['Vous avez vu une personne prendre un objet. Dans votre rapport, décrivez-vous ce geste ou affirmez-vous qu’elle est forcément coupable ?'],
 ['La réponse A. Décrivez le geste observé, l’heure, le lieu et vos actions.','Séparez vos observations des propos rapportés. Préservez les éléments utiles selon la procédure, sans mener vous-même une enquête judiciaire.'],
 ['Un témoignage utile est précis, objectif et traçable.']])

def short_lines(text):
    """Keep natural sentence boundaries and the short subtitle cadence of the model."""
    import re
    result=[]
    for sentence in re.split(r'(?<=[.!?])\s+',text):
        words=sentence.split()
        while len(words)>24:
            candidates=[i+1 for i,w in enumerate(words[:24]) if i>=8 and w.endswith((',', ';', ':'))]
            cut=candidates[-1] if candidates else 20
            result.append(' '.join(words[:cut]));words=words[cut:]
        if words:result.append(' '.join(words))
    return result

if __name__=='__main__':
    assert len(VIDEOS)==16
    for v in VIDEOS:
        v['voice']='fr-FR-HenriNeural'
        v['reference_style']='missions-limites-20260920'
        for scene in v['scenes']:
            scene['lines']=[part for line in scene['lines'] for part in short_lines(line)]
        v['scenes'].append(dict(kind='outro',label='',lines=[],pause=4))
    (ROOT/'series.json').write_text(json.dumps(VIDEOS,ensure_ascii=False,indent=2)+'\n')
    print(f'{len(VIDEOS)} capsules conformes au modèle de référence')
