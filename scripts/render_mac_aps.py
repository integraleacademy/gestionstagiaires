"""Produce five original, Henri-narrated MAC APS revision videos.

This build script is independent of the application and of the course loader.
Only fictional educational narration is sent to Microsoft's speech service.
It never turns video duration into regulatory training attendance.

Build dependencies: Python 3.12, edge-tts==7.2.8, Pillow, ffmpeg and ffprobe.
For a picture/caption-only correction retaining the published audio and learner
timeline, use scripts/resync_mac_aps.py. This authoring entry point re-synthesizes
narration and is reserved for a deliberate new recording.
Usage: python scripts/render_mac_aps.py --module 01
       python scripts/render_mac_aps.py --prepare-only
       python scripts/render_mac_aps.py --merge --verify
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "elearning_native/mac_aps"
ILLUSTRATIONS = RES / "assets/illustrations"
ASSETS = RES / "assets/media/mac-aps/v3"
WORK = Path(os.environ.get("MAC_APS_MEDIA_WORK", "/tmp/mac-aps-media"))
FONT = ROOT / "scripts/academy_videos/assets/Manrope-600.ttf"
BOLD = ROOT / "scripts/academy_videos/assets/Manrope-800.ttf"
VOICE = "fr-FR-HenriNeural"
RATE = "-2%"
REVISION = "20261013-mac-aps-v3"
W, H, FPS = 1280, 720, 25
NAVY, BLUE, GOLD = "#172b4d", "#235dd1", "#e9b647"
BG, MUTED, LIGHT = "#f5f8fd", "#536682", "#e4edfb"


def S(title, kind, nodes, text, note=""):
    return {"title": title, "kind": kind, "nodes": nodes, "text": text, "note": note}


MODULES = {
    "01": {
        "title": "Organiser les premiers secours",
        "subtitle": "Protéger, observer, alerter et préparer le relais",
        "scenes": [
            S("Une réponse préparée et coordonnée", "illustration", ["Repérer les moyens", "Alerter utilement", "Préparer le relais"],
              "Bienvenue dans cette synthèse du maintien et de l’actualisation des compétences de l’agent de prévention et de sécurité. Nous allons revoir l’organisation des premiers secours sur un site. L’objectif est de reconnaître une situation préoccupante, de protéger les personnes sans s’exposer, de transmettre une alerte exploitable et d’accueillir les secours. Cette vidéo accompagne les cours et les exercices. Les gestes de secours demandent un apprentissage et une évaluation avec un formateur qualifié. Regarder une vidéo ne valide pas une compétence pratique. Tout au long de cette séquence, distinguez ce que vous avez réellement observé, ce que vous avez fait et ce que vous devez transmettre au professionnel qui prend le relais."),
            S("Avant la prise de poste", "steps", ["Consignes de secours", "Moyens disponibles", "Accès des secours"],
              "Une intervention efficace commence avant l’accident. À la prise de poste, consultez les consignes de secours, vérifiez les moyens d’alerte et repérez le matériel disponible. Sachez où se trouvent la trousse de secours et le défibrillateur, comment les atteindre et qui peut vous aider. Identifiez l’adresse exacte du site, le nom des bâtiments, les accès utilisables et les obstacles éventuels. Un portail fermé ou une entrée mal indiquée peut retarder l’équipe de secours. Demandez aussi comment joindre les sauveteurs secouristes du travail présents. Si un moyen manque ou semble indisponible, signalez-le immédiatement selon la procédure. Une habitude personnelle ne remplace jamais une organisation connue et partagée par l’équipe.", "Le repérage se fait avant l’urgence."),
            S("Protéger sans créer une autre victime", "decision", ["Un danger persiste ?", "Se tenir hors du danger", "Faire sécuriser la zone"],
              "Face à un événement, commencez par observer l’environnement. La circulation, une installation électrique, un objet instable, une fumée ou un comportement violent peuvent menacer la victime et les intervenants. Vous ne devez pas vous engager dans une zone dangereuse simplement pour agir plus vite. Empêchez d’autres personnes de s’exposer dans la mesure de vos possibilités et demandez les moyens adaptés. Supprimer un danger n’a de sens que si cela peut être réalisé sans risque et dans votre champ de compétence. Si ce n’est pas possible, gardez vos distances et transmettez la nature du danger. Ne déplacez pas une victime par confort ou pour dégager la vue. Les décisions particulières se travaillent dans la formation pratique et avec les indications des secours.", "Votre propre sécurité conditionne l’aide possible."),
            S("Observer et décrire des faits", "columns", ["Ce que je vois", "Ce que j’entends", "Ce qui évolue"],
              "Une fois l’accès suffisamment sûr, recherchez les informations utiles sans poser de diagnostic. Une personne vous répond-elle ? Que vous dit-elle ? Quel événement venez-vous de constater ? Décrivez simplement les signes observés et leur évolution. Dire que la personne répond à vos questions mais semble très pâle donne une information concrète. Affirmer qu’elle fait une maladie précise sans compétence médicale peut orienter à tort les échanges. Écoutez la personne, rassurez-la et préservez autant que possible son intimité. Ne la filmez pas et ne diffusez aucune image sur un groupe de discussion. Si son état change, signalez-le immédiatement à l’interlocuteur des secours. Votre rôle est de fournir des faits fiables et de suivre les consignes reçues.", "Observation ne signifie pas diagnostic."),
            S("Une alerte que l’on peut exploiter", "steps", ["Où et comment entrer", "Quoi et combien", "Risques et actions"],
              "Lorsque vous appelez les secours, donnez d’abord une localisation précise et un numéro permettant de vous rappeler. Indiquez l’adresse, le bâtiment, l’étage si nécessaire et le meilleur accès. Présentez ensuite la situation observée, le nombre de personnes concernées, les dangers encore présents et les premières mesures prises. Parlez clairement et laissez l’opérateur poser ses questions. Le quinze permet de joindre l’aide médicale urgente ; le dix-huit les sapeurs-pompiers ; le cent douze constitue le numéro d’urgence européen. Utilisez le numéro prévu pour la situation et les consignes du site. Un appel interne au poste de sécurité ne doit pas retarder une alerte externe nécessaire. Ne raccrochez pas avant d’y avoir été invité et restez disponible.", "Localisation, situation, victimes, dangers, actions."),
            S("Distribuer les rôles clairement", "columns", ["Auprès de la personne", "Alerte et coordination", "Guidage des secours"],
              "Quand plusieurs agents ou témoins sont présents, donnez des missions précises. Une personne reste auprès de la victime si les conditions le permettent ; une autre transmet l’alerte ; une troisième va accueillir les secours au point convenu. Adressez-vous à une personne identifiée et demandez-lui de confirmer qu’elle a compris. Une consigne générale lancée à la foule risque de n’être suivie par personne. Le guidage doit conduire les intervenants jusqu’au bon lieu, avec les moyens d’accès nécessaires. Les autres agents maintiennent une circulation adaptée et éloignent les curieux sans entraver les secours. Vérifiez que les informations essentielles circulent entre les rôles. Si vous êtes seul, indiquez-le à l’opérateur : il vous aide à hiérarchiser les actions.", "Une mission, une personne, une confirmation."),
            S("Agir dans ses compétences", "layers", ["Gestes appris et actualisés", "Consignes de l’opérateur", "Surveillance et réévaluation"],
              "Les gestes doivent correspondre à votre formation actualisée, à l’état de la personne et aux instructions des secours. N’improvisez pas un traitement et ne proposez pas un médicament personnel. L’utilisation d’un défibrillateur s’accompagne des indications données par l’appareil et des gestes appris lors de la formation. Cette synthèse ne remplace pas leur démonstration ni leur entraînement. Pendant l’attente, restez attentif aux changements et transmettez-les. Une personne initialement capable de parler peut se dégrader ; l’alerte doit alors être mise à jour sans attendre l’arrivée des intervenants. Préservez la confidentialité et annoncez calmement ce que vous faites. La présence, l’écoute et une coordination stable sont utiles, même lorsqu’aucun geste technique ne relève immédiatement de votre rôle.", "L’entraînement pratique reste indispensable."),
            S("Cas : malaise dans le hall", "decision", ["Personne consciente, se sent mal", "Alerte médicale et protection", "Accès dégagé et surveillance"],
              "Prenons une situation fictive. Dans le hall, un visiteur vous indique qu’il se sent très mal. Il est conscient, répond à vos questions et demande à s’asseoir. L’environnement ne présente pas de danger immédiat. Vous sollicitez un collègue, restez auprès du visiteur et faites contacter les secours selon la situation. Vous transmettez l’adresse exacte, ce que dit la personne et ce que vous observez. Votre collègue prépare l’accès. Une autre personne propose de conduire elle-même le visiteur à l’hôpital pour gagner du temps. Vous ne substituez pas cette initiative à l’avis des secours : vous expliquez qu’une évaluation et des consignes adaptées sont en cours. Vous surveillez la situation et signalez tout changement à l’opérateur.", "Mettre la vidéo en pause : quelles informations transmettre ?"),
            S("Passer le relais et tirer les enseignements", "steps", ["Chronologie factuelle", "Transmission aux secours", "Retour sur l’organisation"],
              "À l’arrivée des intervenants, fournissez une transmission courte : l’événement constaté, les horaires utiles, les signes observés, les changements et les actions réalisées. Ne multipliez pas les interprétations. Suivez leurs demandes et facilitez leur intervention. Après l’événement, rédigez le compte rendu prévu, avec seulement les données nécessaires et dans les outils autorisés. Le retour d’expérience peut révéler une adresse imprécise, un portail difficile à ouvrir ou une répartition des rôles mal comprise. Ces éléments servent à améliorer l’organisation. Pour vérifier vos acquis, expliquez maintenant comment vous donneriez l’alerte depuis votre propre poste, qui guiderait les secours et quels risques pourraient gêner leur accès. Reprenez les exercices avec le formateur pour transformer ces repères en comportements maîtrisés.", "Un compte rendu utile prépare la prochaine intervention."),
        ],
    },
    "02": {
        "title": "Appliquer les principes de la République",
        "subtitle": "Respect des personnes, égalité et décisions professionnelles",
        "scenes": [
            S("Des principes dans les actes quotidiens", "illustration", ["Liberté", "Égalité", "Fraternité"],
              "Dans cette synthèse, nous allons relier les principes de la République aux situations quotidiennes de l’agent de prévention et de sécurité. Ces principes prennent une forme concrète dans l’accueil, l’application d’une consigne et la manière de rendre compte. Vous rencontrez des personnes aux parcours, aux convictions et aux besoins différents. Votre mission repose sur le respect de leur dignité et sur des décisions justifiables. Une tenue, un accent ou une opinion supposée ne constituent pas, à eux seuls, un comportement dangereux. Pour chaque situation, posez-vous trois questions : quel fait ai-je constaté, quelle règle légitime dois-je appliquer et comment l’expliquer sans humilier la personne ? C’est ce raisonnement que nous allons travailler."),
            S("Liberté : des limites définies par le droit", "columns", ["Libertés des personnes", "Règles applicables", "Limites de la mission"],
              "La liberté implique le respect des droits d’autrui et du cadre légal. Un agent privé n’a pas à autoriser les opinions des visiteurs ni à imposer ses propres convictions. Il applique les règles nécessaires à sa mission, dans les limites de ses pouvoirs. Si un visiteur critique l’établissement, cette critique ne suffit pas à justifier une mesure de sécurité. Vous recherchez un éventuel comportement concret qui nécessite une réponse : menace, obstruction d’un passage ou refus d’une règle d’accès licite, par exemple. La réponse doit porter sur ce comportement. Avant d’intervenir, vérifiez aussi que la consigne reçue est comprise et applicable au contexte. Un désaccord d’opinion ne doit pas devenir un conflit artificiel avec le service de sécurité.", "Répondre au comportement, pas à l’opinion supposée."),
            S("Égalité : des critères explicables", "steps", ["Critère objectif", "Règle cohérente", "Explication respectueuse"],
              "L’égalité demande des critères objectifs et un traitement cohérent de situations comparables. Si l’accès exige un titre valable, vous vérifiez ce titre selon la procédure prévue. Vous ne durcissez pas le contrôle parce qu’une personne paraît différente ou vous déplaît. Lorsque des situations sont différentes, une adaptation peut être nécessaire : expliquer plus lentement à une personne qui comprend mal le français ou proposer un chemin accessible ne signifie pas lui accorder un privilège arbitraire. L’objectif demeure l’accès au service dans des conditions sûres et respectueuses. Une décision solide doit pouvoir être expliquée à la personne concernée, à un collègue et au responsable. Si l’explication repose seulement sur une impression, revenez aux faits.", "Une adaptation utile permet un accueil équitable."),
            S("Fraternité et dignité dans la relation", "columns", ["Écouter sans juger", "Préserver la dignité", "Orienter vers une solution"],
              "La fraternité se traduit notamment par l’entraide et le respect de la personne. Dans votre mission, cela signifie écouter une demande, reconnaître une difficulté et orienter vers l’interlocuteur compétent. Vous pouvez rester ferme sur une règle tout en choisissant des mots respectueux. Évitez les moqueries, les commentaires sur le physique et les échanges humiliants devant le public. Une personne perdue, âgée ou en difficulté peut avoir besoin d’une explication supplémentaire. Proposez votre aide sans l’imposer et demandez-lui ce qui lui serait utile. Si une tension apparaît, préservez un espace de dialogue. Une posture professionnelle n’exige ni froideur systématique ni familiarité : elle combine une règle claire, une attitude calme et le respect de l’autonomie de chacun.", "Fermeté sur la règle, respect dans la relation."),
            S("Laïcité : connaître le contexte", "layers", ["Liberté de conscience", "Neutralité de l’État", "Cadre précis du lieu"],
              "La laïcité garantit la liberté de conscience et organise notamment la neutralité de l’État. Elle ne donne pas à un agent privé un pouvoir général d’interdire toute expression religieuse dans tout lieu. Les règles varient selon le cadre : service public, entreprise, établissement concerné et mission confiée. Il faut donc connaître le contexte et demander une clarification au responsable en cas de doute. Une consigne ne doit pas être inventée au contrôle d’accès. Vous n’engagez pas de débat religieux avec les visiteurs et vous n’interprétez pas un signe personnel comme un indice de danger. Si une règle particulière s’applique légalement à la situation, expliquez-la de façon précise et respectueuse, avec le relais prévu par l’organisation.", "Aucune interdiction générale inventée par l’agent."),
            S("Identifier une discrimination", "decision", ["Une différence de traitement", "Un critère protégé", "Une décision à vérifier"],
              "Une discrimination peut résulter d’une différence de traitement fondée sur un critère interdit dans une situation visée par le droit. Dans l’accueil et l’accès à un service, soyez notamment attentif aux décisions liées à l’origine, au sexe, à la religion, au handicap ou à l’état de santé. Ces exemples ne constituent pas la liste complète des critères protégés. Si un responsable vous demande de filtrer un public sur la base d’un stéréotype, ne transformez pas cette instruction en pratique habituelle. Demandez la règle précise et signalez le problème selon le circuit approprié. L’ancienneté d’une habitude ou la demande d’un client ne suffisent pas à la rendre légitime. Une trace factuelle des instructions et des faits facilite le traitement de la difficulté.", "Une habitude ne rend pas un critère légitime."),
            S("Handicap : demander avant d’aider", "steps", ["S’adresser à la personne", "Demander le besoin", "Adapter le parcours"],
              "Le handicap peut être visible ou invisible. Ne déduisez pas les capacités d’une personne de son apparence. Adressez-vous directement à elle, même lorsqu’un accompagnant est présent, et demandez comment vous pouvez faciliter le passage. Ne saisissez pas un fauteuil ou un équipement d’assistance sans accord. Une consigne doit rester intelligible : formulez une phrase à la fois, indiquez clairement le chemin et vérifiez la compréhension si nécessaire. Si un accès est indisponible, cherchez avec le responsable une solution adaptée au lieu de renvoyer automatiquement la personne. Préservez la confidentialité de ce qu’elle vous explique. Vous n’avez pas besoin d’un diagnostic médical détaillé pour reconnaître un besoin concret d’aide ou d’orientation.", "L’aide se propose et se coordonne avec la personne."),
            S("Cas : une instruction de filtrage injustifiée", "decision", ["Consigne fondée sur l’accent", "Demander un critère licite", "Alerter le responsable"],
              "Voici un cas fictif. À l’entrée d’un événement, un collègue vous conseille de contrôler systématiquement plus longtemps les personnes ayant un certain accent. Il affirme que cela a toujours été fait. Vous ne reprenez pas cette habitude. Vous appliquez les critères d’accès prévus à tous les visiteurs concernés et vous demandez au responsable de clarifier l’instruction problématique. Si un comportement précis pose difficulté, vous le décrivez indépendamment de l’origine supposée. Votre compte rendu mentionne les faits utiles et les paroles pertinentes, sans qualifier inutilement les personnes. Mettez la vidéo en pause et formulez une réponse professionnelle au collègue. Elle doit rappeler la règle objective, maintenir une coopération calme et permettre le signalement de l’écart.", "La décision doit rester indépendante des stéréotypes."),
            S("Justifier et rendre compte", "steps", ["Fait observé", "Règle appliquée", "Réponse et relais"],
              "Pour terminer, retenez une méthode simple : constatez les faits, identifiez la règle applicable, choisissez une réponse adaptée et préparez le relais. Un compte rendu indique ce qui s’est produit, les explications données et la suite apportée. Évitez les étiquettes comme personne bizarre ou public à problème. Elles n’aident pas à comprendre une situation et peuvent entretenir des préjugés. Lorsque vous doutez de la légalité d’une instruction, demandez une vérification au bon niveau. Votre professionnalisme se mesure aussi à cette capacité de recul. Pour poursuivre, prenez une règle de votre poste et expliquez comment vous l’appliqueriez à trois visiteurs ayant des besoins différents. La sécurité, la dignité et la cohérence des décisions doivent rester visibles dans chacune de vos réponses.", "Une décision professionnelle se comprend et se vérifie."),
        ],
    },
    "03": {
        "title": "Décider dans le cadre juridique",
        "subtitle": "Pouvoirs, limites, déontologie et transmissions",
        "scenes": [
            S("Une mission privée dans un cadre précis", "illustration", ["Mission définie", "Pouvoirs limités", "Responsabilité personnelle"],
              "Cette synthèse rappelle comment prendre une décision professionnelle dans le cadre juridique de la sécurité privée. L’expérience ne dispense pas de vérifier les règles : les pratiques, les textes et les situations de site peuvent évoluer. Votre mission est définie, vos pouvoirs sont limités et vos actes peuvent engager votre responsabilité. Le port d’une tenue ou d’une carte professionnelle ne vous transforme pas en policier. Une consigne du client ne peut pas créer un pouvoir que la loi ne prévoit pas. Nous allons examiner les conditions d’exercice, les limites de l’intervention, le respect de la personne et la qualité des transmissions. L’objectif est de savoir quand agir, quand s’abstenir et quand demander un relais compétent."),
            S("Vérifier les conditions d’exercice", "steps", ["Titre et situation à jour", "Mission autorisée", "Consignes comprises"],
              "Avant d’exercer, assurez-vous que votre situation professionnelle et les documents requis correspondent à l’activité réalisée. Le renouvellement de la carte professionnelle et le maintien des compétences sont des démarches distinctes de la simple consultation d’un cours. N’attendez pas la fin de validité pour signaler un problème à votre employeur. Sur le poste, vérifiez le périmètre de la mission, les horaires, les contacts utiles et les consignes particulières. Si une tâche nouvelle vous est demandée, examinez si elle relève réellement de votre activité et de votre formation. Une autorisation interne ne suffit pas à élargir une compétence réglementée. Lorsqu’une instruction est ambiguë, demandez une clarification avant qu’un incident rende la décision plus difficile.", "La carte et le poste doivent correspondre à l’activité."),
            S("Consigne et règle de droit", "layers", ["Le droit applicable", "Le cadre de la mission", "La consigne opérationnelle"],
              "Une consigne sert à organiser la mission, mais elle reste soumise au droit. Elle précise par exemple un circuit de ronde, une procédure d’accès ou un destinataire d’alerte. Elle ne peut pas autoriser une violence injustifiée, une discrimination ou une atteinte arbitraire à la vie privée. Lorsqu’un écart apparaît, ne vous contentez pas de dire que vous obéissiez aux ordres. Vérifiez les faits, demandez une explication et utilisez le circuit de signalement prévu. Cette démarche doit rester proportionnée à la situation : une urgence exige de protéger immédiatement les personnes, tandis qu’une procédure mal rédigée peut être clarifiée avant sa prochaine application. Conservez une trace utile des instructions reçues et des difficultés rencontrées.", "Une consigne organise ; elle ne crée pas un pouvoir."),
            S("Identifier sans contrôler comme la police", "columns", ["Vérification d’accès", "Consentement et procédure", "Relais des autorités"],
              "Dans certains accès, la procédure peut prévoir de présenter un justificatif ou de vérifier un nom sur une liste. Expliquez la finalité de cette vérification et appliquez la règle licite du site. Vous ne disposez pas pour autant d’un pouvoir général de contrôle d’identité comparable à celui des forces de l’ordre. Le refus d’une formalité d’accès se traite selon la procédure et le cadre applicable ; il n’autorise pas une contrainte arbitraire. Préservez aussi les documents confiés momentanément à l’accueil : évitez les copies et les rétentions inutiles. Si une situation dépasse votre mission, demandez l’intervention du responsable ou des autorités compétentes. Précisez toujours ce que vous avez réellement vérifié et ce que vous ignorez.", "Accès au site et contrôle d’identité sont distincts."),
            S("Intervention : nécessité et proportion", "decision", ["Une atteinte actuelle ?", "Une réponse nécessaire ?", "Une réponse proportionnée ?"],
              "La légitime défense répond à des conditions précises. Elle ne constitue pas une autorisation générale de régler un conflit par la force. Il faut notamment apprécier la réalité et l’actualité de l’atteinte injustifiée, la nécessité de la réponse et sa proportion. Une réaction de vengeance après les faits n’est pas une défense. La protection des biens obéit également à des règles particulières qui ne se confondent pas avec celles applicables à la protection des personnes. Dans la pratique, privilégiez la prévention, la mise à distance et le recours aux secours ou aux forces de l’ordre quand cela est adapté. Les techniques et les limites de l’intervention se travaillent avec un formateur ; une vidéo ne valide pas un geste.", "La réaction doit être justifiée par la situation réelle."),
            S("Flagrance : un cadre exceptionnel", "layers", ["Faits répondant aux conditions", "Remise à l’OPJ compétent", "Dignité et sécurité"],
              "L’article soixante-treize du code de procédure pénale prévoit, dans certaines situations de crime flagrant ou de délit flagrant puni d’emprisonnement, la possibilité pour toute personne d’appréhender l’auteur et de le conduire devant l’officier de police judiciaire le plus proche. Ce cadre ne vous donne pas un pouvoir général d’enquête, d’interrogatoire ou de sanction. Une simple suspicion ne suffit pas à transformer une personne en auteur constaté d’une infraction. La décision doit tenir compte des conditions légales et des risques. Sollicitez les forces de l’ordre et respectez la dignité ainsi que la sécurité des personnes. N’utilisez jamais cette référence pour justifier un enfermement de convenance ou obtenir des aveux. La procédure exacte se travaille lors de la formation encadrée.", "Aucune enquête ou sanction privée."),
            S("Déontologie et confidentialité", "columns", ["Comportement digne", "Données nécessaires", "Destinataires autorisés"],
              "La déontologie se voit dans la tenue, les paroles, la maîtrise de soi et le respect des personnes. Elle implique aussi de protéger les informations obtenues pendant la mission. Un incident, une photographie ou une donnée issue d’un contrôle n’a pas à circuler sur un téléphone personnel ou un réseau social. Utilisez les outils autorisés et limitez la transmission aux destinataires qui en ont besoin. Un collègue curieux n’est pas automatiquement un destinataire légitime. Dans un compte rendu, séparez les faits constatés des informations rapportées et précisez leur origine. Ne modifiez pas une chronologie pour protéger une mauvaise décision. Une erreur signalée peut être traitée ; une information falsifiée compromet le suivi et la confiance.", "La confidentialité continue après la fin du service."),
            S("Cas : une suspicion à l’accueil", "decision", ["Un objet semble manquer", "Vérifier les faits disponibles", "Alerter sans accuser"],
              "Analysons un cas fictif. Un salarié vous affirme qu’un visiteur a probablement pris un objet, mais il n’a pas vu les faits. Le visiteur se dirige vers la sortie. Vous ne présentez pas une hypothèse comme une infraction établie et vous ne l’enfermez pas pour mener un interrogatoire. Vous cherchez les éléments objectifs accessibles dans votre mission et informez le responsable selon la procédure. Si des faits nouveaux justifient un appel aux forces de l’ordre, vous leur transmettez exactement ce qui est connu et ce qui reste incertain. La communication avec le visiteur doit rester mesurée. Mettez la vidéo en pause et formulez votre premier message radio : il doit décrire la situation sans transformer le soupçon en certitude.", "Une information rapportée reste identifiée comme telle."),
            S("La trace qui permet de comprendre", "steps", ["Horaires et lieux", "Faits et paroles utiles", "Actions et relais"],
              "Un compte rendu professionnel permet à un lecteur absent de comprendre ce qui s’est passé. Indiquez les horaires utiles, le lieu précis, les faits constatés, les actions réalisées et les personnes ou services alertés. Évitez les jugements personnels et les formulations vagues. Si une information vient d’un témoin, dites-le. Si vous ne savez pas quelque chose, ne comblez pas le manque par une supposition. Relisez enfin la cohérence entre le récit, les décisions et les pièces disponibles. Pour poursuivre cette synthèse, choisissez une situation de votre poste et expliquez sa limite juridique : ce que vous pouvez faire, les conditions à respecter et le moment où un relais devient nécessaire. C’est cette capacité à justifier l’action qui sécurise votre pratique quotidienne.", "Faits, décision, transmission : une même cohérence."),
        ],
    },
    "04": {
        "title": "Prévenir les conflits et sécuriser l’accès",
        "subtitle": "Communication, filtrage, consentement et relais",
        "scenes": [
            S("Faire comprendre la règle", "illustration", ["Observer la tension", "Expliquer la règle", "Préparer une issue"],
              "Cette synthèse porte sur la prévention des conflits et la conduite professionnelle du filtrage. Une règle d’accès peut être justifiée et pourtant mal comprise. La manière de l’annoncer influence la réaction de la personne. Votre objectif est d’obtenir une situation sûre, compréhensible et maîtrisée, dans le cadre de votre mission. Vous n’avez pas à gagner un duel verbal ni à imposer une humiliation. Nous allons revoir l’observation de la tension, l’écoute, l’explication d’un refus, le respect du consentement et la demande de renfort. Les techniques d’intervention physique nécessitent un entraînement encadré. Ici, nous travaillons surtout les décisions et les paroles qui permettent de prévenir une escalade et de protéger les personnes."),
            S("Repérer ce qui fait monter la tension", "columns", ["La situation", "Les signes observables", "Votre propre posture"],
              "La tension peut venir d’une attente, d’une information contradictoire, d’un refus inattendu ou d’un sentiment d’injustice. Observez les signes concrets : hausse du volume de voix, gestes plus rapides, interruption répétée ou rapprochement insistant. Ces signes ne permettent pas à eux seuls de prédire une agression. Ils invitent à adapter la communication et à surveiller l’évolution. Examinez aussi votre propre posture : bras fermés, ironie ou réponse brusque peuvent alimenter le conflit. Gardez une distance adaptée au lieu et une possibilité de retrait. Ne vous placez pas volontairement dans un angle sans issue. Si plusieurs personnes parlent en même temps, proposez un interlocuteur principal et demandez du calme sans adopter un ton provocateur.", "Observer une évolution, sans diagnostiquer une personne."),
            S("Écouter puis reformuler", "steps", ["Laisser expliquer", "Reformuler le besoin", "Vérifier la compréhension"],
              "Commencez par écouter la demande quand la situation le permet. Une reformulation courte montre que vous avez compris sans valider une exigence incompatible avec la règle. Vous pouvez dire : vous avez attendu longtemps et vous souhaitez savoir pourquoi l’accès est refusé. Évitez les formules qui minimisent la difficulté, comme ce n’est rien, ou celles qui donnent un ordre émotionnel, comme calmez-vous, sans explication. Posez une question utile à la fois. Si la personne parle difficilement français, utilisez des mots simples et vérifiez la compréhension. La reformulation sert aussi à corriger un malentendu : un visiteur peut chercher un autre bâtiment ou posséder un document différent de celui attendu. Clarifier le besoin évite parfois tout conflit.", "Comprendre une demande ne signifie pas tout accepter."),
            S("Annoncer une limite et une solution", "steps", ["Règle claire", "Motif concret", "Solution ou relais"],
              "Pour annoncer une limite, formulez la règle, son motif utile et la suite possible. Par exemple : ce passage est réservé aux personnes inscrites ; votre nom n’apparaît pas sur la liste disponible ; je peux joindre l’accueil pour vérifier votre invitation. Cette formulation laisse une issue sans promettre un résultat que vous ne maîtrisez pas. Évitez les phrases personnelles comme je vous interdis d’entrer parce que je l’ai décidé. Si aucune alternative immédiate n’est possible, expliquez le circuit de réclamation ou l’interlocuteur compétent. Restez cohérent avec vos collègues afin de ne pas multiplier les consignes contradictoires. Une explication claire n’exige pas de débattre indéfiniment : lorsque l’échange tourne en boucle, préparez un relais calme.", "La limite est claire ; la personne conserve une issue."),
            S("Filtrage : distinguer les opérations", "columns", ["Contrôle du titre d’accès", "Inspection visuelle du bagage", "Fouille avec consentement"],
              "Au filtrage, ne confondez pas les opérations. Vérifier un titre d’accès, regarder visuellement l’intérieur d’un bagage présenté et procéder à sa fouille ne sont pas des actes identiques. Dans le cadre prévu pour les agents concernés, l’inspection visuelle des bagages à main est possible ; leur fouille exige le consentement du propriétaire. Expliquez ce qui est demandé et la manière dont l’opération va se dérouler. Vous n’avez pas à arracher un sac ou à l’ouvrir de force parce qu’une personne refuse. Le refus se traite selon les règles licites d’accès et les consignes du site, avec un relais si nécessaire. Il ne constitue pas automatiquement une preuve d’infraction. Restez attentif à la confidentialité des effets personnels.", "Un refus ne donne pas un droit à la contrainte."),
            S("Palpation : des conditions spécifiques", "layers", ["Cadre légal applicable", "Consentement exprès", "Personne du même sexe"],
              "La palpation de sécurité obéit à des conditions spécifiques. Elle n’est pas une formalité librement décidée à chaque entrée. Il faut vérifier le cadre légal applicable, les habilitations ou conditions particulières requises pour la mission et l’organisation de l’opération. Le consentement exprès de la personne est nécessaire, et la palpation est réalisée par une personne du même sexe. Ne confondez pas ce cadre avec une fouille corporelle relevant d’autres pouvoirs. Si l’une des conditions manque, vous n’improvisez pas une solution en dehors du droit : vous sollicitez le responsable et appliquez la procédure adaptée. Les gestes, la posture et la coordination doivent être appris en situation encadrée. Cette vidéo ne constitue pas une habilitation ni une validation pratique.", "Vérifier les conditions avant de réaliser l’opération."),
            S("Demander du renfort avant la rupture", "decision", ["La tension continue ?", "Prendre de la distance", "Demander le relais adapté"],
              "Un renfort demandé suffisamment tôt peut éviter une intervention précipitée. Décrivez au poste de sécurité ce qui se passe, où vous êtes, combien de personnes sont concernées et quel soutien est nécessaire. Évitez les messages dramatiques ou imprécis. Le collègue qui arrive doit comprendre son rôle : observer, reprendre l’explication, protéger un accès ou faciliter le retrait. L’accumulation d’agents autour d’une personne peut accroître la tension ; adaptez le dispositif au risque réel. Si une menace grave apparaît, la priorité devient la protection et l’appel aux services compétents. Ne poursuivez pas une discussion pour démontrer votre autorité alors que les conditions se dégradent. Le choix de se retirer et de faire intervenir un relais peut être la décision la plus professionnelle.", "Le renfort doit avoir une mission précise."),
            S("Cas : refus d’ouverture d’un sac", "decision", ["La personne refuse", "Expliquer les règles d’accès", "Relais sans fouille forcée"],
              "Voici une situation fictive. À l’entrée d’un événement, une personne refuse la vérification demandée pour son bagage et élève la voix. Vous gardez une distance adaptée, expliquez précisément la règle applicable et présentez la suite prévue en cas de refus. Vous ne touchez pas son sac par surprise et ne présentez pas ce refus comme une preuve de culpabilité. Un collègue prévient le responsable tandis que vous maintenez un dialogue simple. La personne demande à parler à quelqu’un d’autre : ce relais peut être utile si les conditions restent sûres. Mettez la vidéo en pause et préparez trois phrases : une reformulation, une explication de la règle et une proposition de suite. Chacune doit pouvoir être prononcée calmement, sans menace ni humiliation.", "Consentement, calme et continuité de la procédure."),
            S("Après le conflit : remettre le service en ordre", "steps", ["Vérifier la situation", "Transmettre les faits", "Améliorer la prévention"],
              "Quand la situation est revenue au calme, vérifiez que l’accès et les personnes sont en sécurité. Transmettez les informations utiles au responsable et rédigez le compte rendu prévu. Mentionnez le motif initial, les faits observés, les explications données, les relais sollicités et l’issue de l’événement. Analysez ensuite ce qui aurait pu éviter la tension : signalétique, information avant l’arrivée, cohérence de la liste d’accès ou répartition des rôles. L’objectif n’est pas de chercher un coupable dans l’équipe, mais de comprendre les points d’amélioration. Pour poursuivre, entraînez-vous avec un collègue à annoncer un refus d’accès, puis échangez les rôles. Le formateur pourra corriger la posture, le vocabulaire et les limites à respecter en situation réelle.", "Le retour d’expérience améliore aussi l’accueil suivant."),
        ],
    },
    "05": {
        "title": "Prévenir le risque terroriste",
        "subtitle": "Observer, protéger les personnes et alerter",
        "scenes": [
            S("Une vigilance fondée sur les faits", "illustration", ["Prévenir", "Protéger", "Alerter"],
              "Cette synthèse aborde la prévention du risque terroriste dans la mission de l’agent de prévention et de sécurité. Elle porte sur la vigilance, la protection du public et l’alerte. Elle ne prépare pas une confrontation armée. Votre rôle consiste à repérer des faits préoccupants, appliquer les consignes de sûreté, limiter l’exposition des personnes et transmettre une information utile aux services compétents. La vigilance ne consiste pas à suspecter un public en raison de son origine, de sa religion ou de sa tenue. Un comportement s’analyse dans son contexte, avec prudence et sans accusation hâtive. Nous allons examiner la préparation du site, les anomalies, les choix de protection et la manière de communiquer pendant un événement grave."),
            S("Connaître le site avant l’événement", "steps", ["Consignes et contacts", "Cheminements possibles", "Rôles de l’équipe"],
              "La préparation commence par les consignes de sûreté actualisées du site. Identifiez les moyens d’alerte, les responsables et les contacts des services d’urgence. Repérez les accès, les cheminements et les espaces prévus par l’organisation pour protéger les personnes. Ces repères doivent être connus sans être diffusés publiquement. Vérifiez que les portes, les moyens de communication et les dispositifs prévus sont utilisables selon la procédure. Une anomalie technique doit être signalée avant de devenir un obstacle en situation d’urgence. Les exercices encadrés permettent de vérifier la compréhension des rôles et l’adaptation du message au public. Ils doivent aussi prendre en compte les personnes ayant des difficultés de déplacement, d’audition, de vision ou de compréhension.", "La préparation relève d’une organisation partagée."),
            S("Décrire une anomalie sans conclure trop vite", "columns", ["Faits constatés", "Contexte connu", "Éléments incertains"],
              "Une anomalie peut concerner un accès inhabituellement ouvert, un objet dont la présence interroge ou un comportement qui s’écarte nettement de la situation attendue. Commencez par des faits : le lieu, l’heure, ce qui est visible et ce qui a changé. Ne cherchez pas à deviner une intention à partir d’un seul détail. Une personne stressée peut avoir de nombreuses raisons de l’être. Recoupez les informations disponibles dans le cadre de votre mission, sans vous exposer et sans mener une enquête improvisée. Signalez ce qui nécessite une vérification à l’interlocuteur prévu. Dans votre message, distinguez ce que vous avez vu de ce qu’un tiers vous a rapporté. Cette distinction aide à décider du niveau de réponse.", "Un signalement utile conserve les incertitudes."),
            S("Objet suspect : ne pas manipuler", "decision", ["Présence préoccupante", "Ne pas toucher ni déplacer", "Éloigner et alerter"],
              "Si un objet présente un caractère suspect au regard du contexte, ne l’ouvrez pas, ne le déplacez pas et ne cherchez pas à vérifier vous-même son contenu. Prévenez les personnes de ne pas s’en approcher et appliquez les consignes de mise à distance et d’alerte du site. Les modalités précises sont définies avec les responsables et les services compétents ; elles ne se remplacent pas par une estimation personnelle. Transmettez l’emplacement exact, l’aspect visible et les circonstances de découverte, depuis une position adaptée. Ne revenez pas auprès de l’objet pour prendre une meilleure photographie. Si une intervention spécialisée est nécessaire, facilitez l’accès des services et évitez les rassemblements de curieux. Votre priorité est la protection, pas l’identification technique de l’objet.", "L’agent ne vérifie pas le contenu par manipulation."),
            S("Danger grave : choisir une protection possible", "decision", ["Une fuite sûre est possible ?", "S’éloigner sans s’exposer", "Sinon, se mettre à l’abri"],
              "Face à une attaque ou à un danger grave, cherchez d’abord à réduire l’exposition. Les consignes publiques rappellent l’importance de s’échapper lorsque cela est possible sans se mettre davantage en danger, ou de se cacher lorsque la fuite n’est pas possible. Le choix dépend de ce qui est réellement observé et des consignes adaptées au site. Ne dirigez pas automatiquement le public vers un chemin dont la sécurité est inconnue. Donnez des indications courtes et compréhensibles et adaptez l’aide aux personnes présentes. Vous ne partez pas à la recherche de l’auteur et vous ne vous rapprochez pas pour confirmer une information. La protection d’un groupe repose sur une décision prudente, une communication claire et une réévaluation de la situation.", "Aucun trajet automatique sans apprécier le danger."),
            S("Alerter depuis une position sûre", "steps", ["Lieu et accès", "Faits et victimes visibles", "Protection engagée"],
              "Dès que les conditions le permettent, alertez les forces de l’ordre au dix-sept ou au cent douze. Donnez la localisation exacte, les faits constatés, les dangers visibles et les informations utiles sur les personnes exposées. Si un détail est incertain, annoncez cette incertitude. Indiquez également les mesures de protection déjà engagées et les difficultés d’accès connues. Laissez l’opérateur vous guider et restez disponible lorsque cela est possible sans accroître le risque. Ne retardez pas l’appel pour obtenir une description parfaite. Un message partiel mais fiable peut déjà être utile. À l’intérieur de l’équipe, partagez seulement les informations nécessaires, sur les canaux prévus, en évitant les rumeurs et les messages contradictoires qui désorganisent le public.", "Précision utile et prudence valent mieux qu’une certitude inventée."),
            S("Accueillir les forces de l’ordre", "columns", ["Suivre leurs consignes", "Mains visibles", "Aucun mouvement brusque"],
              "À l’arrivée des forces de l’ordre, adoptez un comportement lisible. Suivez leurs consignes, gardez les mains visibles et évitez les gestes brusques. N’avancez pas vers elles avec un objet à la main pour tenter d’expliquer plus vite la situation. Votre tenue professionnelle ne leur permet pas de connaître immédiatement votre rôle ou vos intentions. Quand elles vous le demandent, transmettez les informations utiles : localisation des personnes, faits observés et mesures prises. Ne gênez pas leur progression et ne revenez pas dans une zone pour récupérer des affaires ou chercher un collègue sans instruction. La coordination avec les services compétents prime sur l’initiative individuelle. Continuez à protéger les personnes dans le cadre des consignes reçues et de ce qui reste possible.", "Être identifiable par son comportement et les consignes suivies."),
            S("Cas : une information alarmante au poste", "decision", ["Un témoin signale un danger", "Évaluer sans s’approcher", "Protéger et alerter"],
              "Prenons une situation fictive. Un visiteur rejoint le poste d’accueil et signale un danger grave dans une autre partie du bâtiment. Il est très inquiet et son récit reste incomplet. Vous recueillez les faits essentiels sans prolonger un interrogatoire, prévenez immédiatement le responsable et faites déclencher l’alerte adaptée. Vous ne vous rendez pas dans la zone pour vérifier personnellement le récit. Vous protégez les personnes présentes selon les possibilités réelles et les consignes connues, tout en demandant le relais des forces de l’ordre. Mettez la vidéo en pause et préparez votre message : où se trouve le danger rapporté, qui l’a observé, ce qui reste incertain et ce que vous avez déjà fait. Une transmission honnête permet une réponse mieux orientée.", "La vérification ne doit pas créer une exposition supplémentaire."),
            S("Après l’alerte : préserver et transmettre", "steps", ["Consignes des autorités", "Informations préservées", "Retour d’expérience"],
              "Après une alerte grave, ne considérez pas qu’un retour au calme apparent autorise automatiquement la reprise du service. Suivez les décisions des autorités et des responsables. Préservez les éléments utiles sans les manipuler inutilement, protégez la confidentialité et abstenez-vous de diffuser des images ou des commentaires sur les réseaux sociaux. Le compte rendu distingue les faits observés, les informations rapportées, les horaires et les actions réalisées. L’équipe peut ensuite analyser les difficultés de communication et les moyens de protection, dans un cadre adapté à l’événement. Certaines personnes auront besoin d’un accompagnement après une situation éprouvante. Pour poursuivre votre travail, expliquez les trois priorités de cette synthèse : une vigilance factuelle, la protection des personnes et une alerte fiable depuis une position aussi sûre que possible.", "La reprise du site se décide avec les responsables compétents."),
        ],
    },
}


def run(args):
    completed = subprocess.run(args, capture_output=True)
    if completed.returncode:
        raise RuntimeError(completed.stderr.decode(errors="replace")[-5000:])
    return completed


def probe(path):
    return json.loads(run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)]).stdout)


def duration(path):
    return float(probe(path)["format"]["duration"])


def stamp(seconds, separator="."):
    ms = round(seconds * 1000)
    return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02}{separator}{ms % 1000:03}"


def normalize(value):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", value.lower()) if c.isalnum())


def narration_words(source, boundaries):
    """Attach authored character positions to actual TTS word boundaries."""
    positions, normalized = [], ""
    for i, char in enumerate(source):
        part = normalize(char)
        normalized += part
        positions.extend([i] * len(part))
    observed = "".join(normalize(w["text"]) for w in boundaries)
    if observed != normalized:
        raise ValueError("Narration/word-boundary mismatch: " + source[:60])
    starts, cursor = [], 0
    for word in boundaries:
        starts.append(positions[cursor])
        cursor += len(normalize(word["text"]))
    words = []
    for i, word in enumerate(boundaries):
        left = 0 if i == 0 else starts[i]
        right = starts[i + 1] if i + 1 < len(starts) else len(source)
        words.append({"text": source[left:right].strip(), "char_start": left, "char_end": right,
                      "start": word["offset"] / 1e7,
                      "end": (word["offset"] + word["duration"]) / 1e7})
    return words


def caption_cues(source, boundaries):
    """Preserve every authored character while using real speech word timings."""
    words = narration_words(source, boundaries)
    cues, i = [], 0
    while i < len(words):
        choices = []
        for j in range(i + 1, len(words) + 1):
            text = " ".join(w["text"] for w in words[i:j])
            wrapped = wrap_caption(text)
            if wrapped is None or words[j - 1]["end"] - words[i]["start"] > 6.0:
                break
            choices.append((j, wrapped))
            if re.search(r"[.!?]$", text):
                break
        if not choices:
            raise ValueError("Caption cannot fit: " + words[i]["text"])
        end, text = choices[-1]
        for candidate_end, candidate in reversed(choices):
            if len(candidate) >= 30 and re.search(r"[,;:.!?]$", candidate):
                end, text = candidate_end, candidate
                break
        start = max(0, words[i]["start"] - .05)
        next_start = words[end]["start"] - .05 if end < len(words) else words[end - 1]["end"] + .30
        finish = min(next_start, max(words[end - 1]["end"] + .18, start + 1.0))
        cues.append({"start": round(start, 3), "end": round(finish, 3), "text": text})
        i = end
    assert re.sub(r"\s+", "", " ".join(c["text"] for c in cues)) == re.sub(r"\s+", "", source)
    return cues


def visual_events(module, scene_index, words):
    """Resolve semantic changes against measured word positions, never thirds."""
    plan = json.loads(Path(__file__).with_name("mac_aps_visual_sync.json").read_text())
    scene = MODULES[module]["scenes"][scene_index]
    authored = plan["modules"][module][scene_index]
    assert authored["title"] == scene["title"]
    events = [{"start": 0.0, "active": []}]
    previous_char = -1
    for event in authored["events"]:
        assert scene["text"].count(event["anchor"]) == 1
        position = scene["text"].index(event["anchor"])
        assert position > previous_char
        previous_char = position
        word = next(w for w in words if w["char_start"] <= position < w["char_end"])
        events.append({**event, "start": word["start"]})
    return events


def wrap_caption(text):
    if len(text) <= 48:
        return text
    words, candidates = text.split(), []
    for i in range(1, len(words)):
        left, right = " ".join(words[:i]), " ".join(words[i:])
        if max(len(left), len(right)) > 48:
            continue
        score = abs(len(left) - len(right))
        if words[i - 1].lower() in {"de", "du", "des", "le", "la", "les", "un", "une", "à", "et", "en", "pour", "ne"}:
            score += 16
        candidates.append((score, left + "\n" + right))
    return min(candidates)[1] if candidates else None


def font(size, bold=False):
    return ImageFont.truetype(str(BOLD if bold else FONT), size)


def write_text(draw, value, x, y, width, size, max_lines=3, fill=NAVY, bold=False, line_height=1.30, centered=False):
    original = size
    while size >= min(18, original):
        f, lines, line = font(size, bold), [], ""
        for word in value.split():
            candidate = (line + " " + word).strip()
            if line and f.getlength(candidate) > width:
                lines.append(line)
                line = word
            else:
                line = candidate
        if line:
            lines.append(line)
        if len(lines) <= max_lines and all(f.getlength(line) <= width + .1 for line in lines):
            break
        size -= 1
    else:
        raise ValueError("MAC APS slide text overflow: " + value)
    for line in lines:
        px = x + (width - f.getlength(line)) / 2 if centered else x
        draw.text((px, y), line, font=f, fill=fill)
        y += size * line_height
    return y


def arrow(draw, start, end, color=BLUE, width=4):
    draw.line([start, end], fill=color, width=width)
    dx, dy = end[0] - start[0], end[1] - start[1]
    a = math.atan2(dy, dx)
    p1 = (end[0] - 12 * math.cos(a - .50), end[1] - 12 * math.sin(a - .50))
    p2 = (end[0] - 12 * math.cos(a + .50), end[1] - 12 * math.sin(a + .50))
    draw.polygon([end, p1, p2], fill=color)


def box(draw, bounds, label, number, active=False, small=False):
    x1, y1, x2, y2 = bounds
    draw.rounded_rectangle(bounds, radius=18, fill=BLUE if active else "#ffffff", outline=BLUE if active else "#ccdaef", width=2)
    fill = "#ffffff" if active else NAVY
    draw.ellipse((x1 + 18, y1 + 17, x1 + 57, y1 + 56), fill="#ffffff" if active else LIGHT)
    write_text(draw, str(number), x1 + 18, y1 + 21, 39, 21, 1, fill=BLUE, bold=True, centered=True)
    write_text(draw, label, x1 + 19, y1 + (64 if small else 74), x2 - x1 - 38, 25 if small else 28, 3, fill=fill, bold=True)


def frame(module, scene_index, active=()):
    # A sentence can concern several ideas, or none of the three labels.
    # Never imply a left-to-right sequence unless the narration says so.
    active = {active} if isinstance(active, int) else set(active)
    module_data = MODULES[module]
    scene = module_data["scenes"][scene_index]
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, W, 8), fill=BLUE)
    write_text(d, "INTÉGRALE ACADEMY  /  MAC APS", 46, 27, 860, 19, 1, bold=True)
    write_text(d, f"SÉQUENCE {scene_index + 1:02} / {len(module_data['scenes']):02}", 985, 29, 250, 16, 1, fill=MUTED)
    write_text(d, module_data["title"].upper(), 46, 80, 1188, 18, 1, fill=BLUE, bold=True)
    write_text(d, scene["title"], 46, 117, 1188, 38, 2, bold=True)
    d.rounded_rectangle((46, 219, 117, 224), radius=2, fill=GOLD)
    nodes, kind = scene["nodes"], scene["kind"]
    if kind == "illustration":
        pic = ImageOps.contain(Image.open(ILLUSTRATIONS / f"module-{module}.webp").convert("RGB"), (570, 280))
        im.paste(pic, (46 + (570 - pic.width) // 2, 242 + (280 - pic.height) // 2))
        d = ImageDraw.Draw(im)
        write_text(d, module_data["subtitle"], 654, 246, 570, 27, 3, bold=True)
        for j, label in enumerate(nodes):
            top = 355 + 48 * j
            d.rounded_rectangle((650, top, 1234, top + 42), radius=12, fill=BLUE if j in active else LIGHT)
            write_text(d, f"{j + 1:02}  {label}", 668, top + 7, 546, 21, 1, fill="#ffffff" if j in active else NAVY, bold=True)
    elif kind in {"steps", "columns"}:
        for j, node in enumerate(nodes):
            left = 46 + j * 408
            box(d, (left, 244, left + 372, 434), node, j + 1, j in active)
            if j < len(nodes) - 1 and kind == "steps":
                arrow(d, (left + 378, 339), (left + 403, 339))
        write_text(d, scene["note"], 50, 478, 1180, 24, 2, fill=MUTED, centered=True)
    elif kind == "decision":
        d.rounded_rectangle((366, 240, 914, 306), radius=18, fill=BLUE if 0 in active else LIGHT, outline=BLUE, width=2)
        write_text(d, nodes[0], 384, 258, 512, 27, 1, fill="#ffffff" if 0 in active else NAVY, bold=True, centered=True)
        arrow(d, (510, 310), (319, 348), BLUE)
        arrow(d, (770, 310), (962, 348), BLUE)
        box(d, (47, 352, 600, 487), nodes[1], 2, 1 in active, small=True)
        box(d, (680, 352, 1233, 487), nodes[2], 3, 2 in active, small=True)
        write_text(d, scene["note"], 50, 514, 1180, 20, 1, fill=MUTED, centered=True)
    elif kind == "layers":
        for j, node in enumerate(nodes):
            left, right, top = 250 - j * 70, 1030 + j * 70, 244 + j * 74
            d.rounded_rectangle((left, top, right, top + 65), radius=15, fill=BLUE if j in active else "#ffffff", outline=BLUE if j in active else "#ccdaef", width=2)
            write_text(d, f"{j + 1:02}  {node}", left + 21, top + 16, right - left - 42, 25, 1, fill="#ffffff" if j in active else NAVY, bold=True, centered=True)
        write_text(d, scene["note"], 50, 496, 1180, 23, 1, fill=MUTED, centered=True)
    else:
        raise ValueError(kind)
    # Captions occupy their own area; diagrams and illustration never cover them.
    d.rectangle((0, 592, W, H), fill="#0f1b2c")
    for i in range(len(module_data["scenes"])):
        step = 1188 / len(module_data["scenes"])
        x = 46 + i * step
        d.rounded_rectangle((x, 588, x + step - 10, 592), radius=2, fill=BLUE if i <= scene_index else "#d3dded")
    return im


def source_signature(module):
    payload = json.dumps(MODULES[module], ensure_ascii=False, sort_keys=True).encode()
    dependencies = ("mac_aps_visual_sync.json", "mac_aps_caption_sync.py", "resync_mac_aps.py", "mac_aps_visual_timing.json")
    build_sources = b"".join(Path(__file__).with_name(name).read_bytes() for name in dependencies if Path(__file__).with_name(name).is_file())
    return hashlib.sha256(payload + (ILLUSTRATIONS / f"module-{module}.webp").read_bytes() + FONT.read_bytes() + BOLD.read_bytes()
                          + Path(__file__).read_bytes() + build_sources).hexdigest()


async def speech(text, folder, scene_index, slots):
    import edge_tts
    import edge_tts.communicate as communication
    from edge_tts.constants import TRUSTED_CLIENT_TOKEN
    communication._SSL_CTX.load_verify_locations(cafile="/etc/ssl/certs/ca-certificates.crt")
    # Microsoft moved Edge's synthesis service in October 2026. Keep the
    # installed client's voice, authentication and timing implementation; only
    # use the current service address (upstream edge-tts PR #491 / issue #490).
    # https://github.com/rany2/edge-tts/pull/491
    communication.WSS_URL = (
        "wss://api.msedgeservices.com/tts/cognitiveservices/websocket/v1"
        "?Ocp-Apim-Subscription-Key=" + TRUSTED_CLIENT_TOKEN
    )
    signature = hashlib.sha256((VOICE + RATE + text).encode()).hexdigest()[:20]
    audio = folder / f"scene-{scene_index:02}-{signature}.mp3"
    timing = audio.with_suffix(".json")
    if audio.is_file() and timing.is_file():
        saved = json.loads(timing.read_text())
        if saved.get("signature") == signature and saved.get("words") and duration(audio) >= saved["last_word_end"] - .08:
            return audio, saved["cues"], saved["words"]
    async with slots:
        for attempt in range(4):
            try:
                boundaries = []
                async def collect():
                    with audio.with_suffix(".partial").open("wb") as output:
                        async for chunk in edge_tts.Communicate(text, voice=VOICE, rate=RATE, pitch="+0Hz", volume="+0%", boundary="WordBoundary").stream():
                            if chunk["type"] == "audio":
                                output.write(chunk["data"])
                            elif chunk["type"] == "WordBoundary":
                                boundaries.append(chunk)
                await asyncio.wait_for(collect(), timeout=95)
                if not boundaries:
                    raise ValueError("No timed narration returned")
                cues = caption_cues(text, boundaries)
                audio.with_suffix(".partial").replace(audio)
                last = (boundaries[-1]["offset"] + boundaries[-1]["duration"]) / 1e7
                assert duration(audio) >= last - .08, "Audio truncated before the last spoken word"
                run(["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-i", str(audio), "-f", "null", "-"])
                words = narration_words(text, boundaries)
                timing.write_text(json.dumps({"signature": signature, "last_word_end": last, "cues": cues, "words": words}, ensure_ascii=False))
                return audio, cues, words
            except Exception as error:
                if attempt == 3:
                    # Avoid including service URL parameters in build output.
                    status = getattr(error, "status", None)
                    raise RuntimeError(f"Narration failed for scene {scene_index}: {type(error).__name__}, HTTP {status}") from None
                await asyncio.sleep(2 * (attempt + 1))


def ass_file(path, cues):
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1280
PlayResY: 720
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,AcademyManrope600,38,&H00FFFFFF,&H00FFFFFF,&H000F1B2C,&H000F1B2C,0,0,0,0,100,100,0,0,1,0,0,2,55,55,22,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    for c in cues:
        text = c["text"].replace("\\", "\\\\").replace("{", r"\{").replace("}", r"\}").replace("\n", r"\N")
        events.append("Dialogue: 0," + stamp(c["start"])[:-1] + "," + stamp(c["end"])[:-1] + ",Default,,0,0,0,," + text + "\n")
    path.write_text(header + "".join(events), encoding="utf-8")


def encode(module, voices, folder):
    ASSETS.mkdir(parents=True, exist_ok=True)
    from mac_aps_caption_sync import reflow_captions
    narration_seconds = sum(duration(audio) for audio, _, _ in voices)
    assert narration_seconds >= 300, f"Module {module}: {narration_seconds:.1f}s spoken; add real explanatory content, never silence"
    captions, chapters, parts, offset = [], [], [], 0.0
    for index, (scene, (audio, cues, words)) in enumerate(zip(MODULES[module]["scenes"], voices)):
        cues = reflow_captions(cues, FONT)
        actual_audio = duration(audio)
        target = max(actual_audio + .30, cues[-1]["end"] + .10)
        frames = []
        events = visual_events(module, index, words)
        for event_index, event in enumerate(events):
            picture = frame(module, index, event["active"])
            png = folder / f"scene-{index:02}-{event_index}.png"
            picture.save(png)
            next_start = events[event_index + 1]["start"] if event_index + 1 < len(events) else target
            if next_start > event["start"]:
                frames.append((png, next_start - event["start"]))
            if index == 0 and event_index == 0:
                picture.save(ASSETS / f"module-{module}.jpg", quality=89)
        slideshow = folder / f"scene-{index:02}-frames.txt"
        slideshow.write_text("".join(f"file '{png}'\nduration {seconds:.6f}\n" for png, seconds in frames) + f"file '{frames[-1][0]}'\n")
        ass = folder / f"scene-{index:02}.ass"
        ass_file(ass, cues)
        part = folder / f"scene-{index:02}.mp4"
        run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(slideshow), "-i", str(audio),
             "-t", str(target), "-vf", f"fps={FPS},ass={ass}:fontsdir={FONT.parent},format=yuv420p", "-c:v", "libx264", "-preset", "veryfast",
             "-crf", "26", "-tune", "stillimage", "-threads", "2", "-c:a", "aac", "-b:a", "80k", "-ar", "48000", "-af", "apad", str(part)])
        actual = duration(part)
        assert abs(actual - target) < .30, f"Truncated scene {module}/{index}"
        captions.extend(dict(c, start=c["start"] + offset, end=c["end"] + offset) for c in cues)
        chapters.append({"title": scene["title"], "start_seconds": round(offset, 3), "end_seconds": round(offset + actual, 3)})
        parts.append(part)
        offset += actual
    concat = folder / "video-parts.txt"
    concat.write_text("".join(f"file '{part}'\n" for part in parts))
    out = ASSETS / f"module-{module}.mp4"
    temporary = ASSETS / f"module-{module}.partial.mp4"
    run(["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c:v", "copy", "-c:a", "aac",
         "-b:a", "80k", "-af", "aresample=async=1:first_pts=0", "-movflags", "+faststart", str(temporary)])
    actual = duration(temporary)
    assert actual >= 300 and abs(actual - offset) < .6
    assert actual >= captions[-1]["end"] and temporary.stat().st_size < 95 * 1024 * 1024
    metadata = probe(temporary)
    assert any(s["codec_type"] == "audio" for s in metadata["streams"])
    run(["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-i", str(temporary), "-f", "null", "-"])
    temporary.replace(out)
    (ASSETS / f"module-{module}.vtt").write_text("WEBVTT\n\n" + "".join(f"{stamp(c['start'])} --> {stamp(c['end'])}\n{c['text']}\n\n" for c in captions).rstrip() + "\n", encoding="utf-8")
    transcript = "\n\n".join(scene["text"] for scene in MODULES[module]["scenes"])
    entry = {"id": f"mac-aps-module-{module}-video", "module": module, "title": "Synthèse vidéo · " + MODULES[module]["title"],
             "src": f"media/mac-aps/v3/module-{module}.mp4", "poster": f"media/mac-aps/v3/module-{module}.jpg", "captions": f"media/mac-aps/v3/module-{module}.vtt",
             "duration_seconds": round(actual, 3), "narration_seconds": round(narration_seconds, 3), "voice": VOICE, "rate": RATE,
             "burned_captions": True, "required": False, "transcript": transcript, "words": len(transcript.split()), "chapters": chapters,
             "caption_cues": len(captions), "render_revision": REVISION, "source_sha256": source_signature(module), "video_sha256": hashlib.sha256(out.read_bytes()).hexdigest()}
    (ASSETS / f"module-{module}.json").write_text(json.dumps(entry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Module {module}: {entry['words']} mots, {actual:.1f} s, {len(captions)} sous-titres, {out.stat().st_size} octets", flush=True)
    return entry


def verify_entry(module, full_decode=False):
    path = ASSETS / f"module-{module}.json"
    entry = json.loads(path.read_text(encoding="utf-8"))
    assert entry["module"] == module and entry["render_revision"] == REVISION
    assert entry["source_sha256"] == source_signature(module), "Media/source mismatch"
    assert entry["voice"] == VOICE and entry["rate"] == RATE and entry["burned_captions"]
    assert entry["narration_seconds"] >= 300 and entry["duration_seconds"] >= 300
    assert len(entry["chapters"]) == len(MODULES[module]["scenes"])
    transcript = "\n\n".join(s["text"] for s in MODULES[module]["scenes"])
    assert entry["transcript"] == transcript and entry["words"] == len(transcript.split())
    for field, extension in [("src", "mp4"), ("poster", "jpg"), ("captions", "vtt")]:
        assert entry[field] == f"media/mac-aps/v3/module-{module}.{extension}"
        file = RES / "assets" / entry[field]
        assert file.is_file() and not file.is_symlink() and file.stat().st_size > 500
    movie = ASSETS / f"module-{module}.mp4"
    assert hashlib.sha256(movie.read_bytes()).hexdigest() == entry["video_sha256"]
    assert abs(duration(movie) - entry["duration_seconds"]) < .05
    assert movie.stat().st_size < 95 * 1024 * 1024
    vtt = (ASSETS / f"module-{module}.vtt").read_text()
    assert vtt.startswith("WEBVTT\n\n") and vtt.count(" --> ") == entry["caption_cues"]
    spoken = " ".join(line for line in vtt.splitlines()[1:] if line and " --> " not in line)
    assert re.sub(r"\s+", "", spoken) == re.sub(r"\s+", "", transcript), "Incomplete caption text"
    if full_decode:
        run(["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-i", str(movie), "-f", "null", "-"])
    return entry


def merge(full_decode=False):
    entries = {module: verify_entry(module, full_decode) for module in MODULES}
    manifest = {"schema_version": 1, "revision": REVISION, "voice": VOICE, "rate": RATE,
                "usage": "Support de révision et de préparation ; ne vaut ni attestation MAC, ni validation de gestes pratiques, ni relevé de présence réglementaire.",
                "total_duration_seconds": round(sum(row["duration_seconds"] for row in entries.values()), 3), "videos": entries}
    (RES / "media_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Manifest vérifié : {len(entries)} vidéos, {manifest['total_duration_seconds'] / 60:.1f} minutes", flush=True)


def prepare(modules):
    WORK.mkdir(parents=True, exist_ok=True)
    for module in modules:
        assert len(MODULES[module]["scenes"]) == 9
        words = sum(len(s["text"].split()) for s in MODULES[module]["scenes"])
        assert words >= 850, f"Module {module}: insufficient original narration ({words} words)"
        assert len({s["title"] for s in MODULES[module]["scenes"]}) == 9
        folder = WORK / module
        folder.mkdir(parents=True, exist_ok=True)
        for index, scene in enumerate(MODULES[module]["scenes"]):
            assert len(scene["nodes"]) == 3
            for active in range(3):
                rendered = frame(module, index, active)
                if active == 0:
                    rendered.save(folder / f"review-{index:02}.jpg", quality=90)
        print(f"Module {module}: {words} mots originaux, 9 séquences, 27 écrans vérifiés", flush=True)


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module", choices=sorted(MODULES))
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--merge", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.merge:
        merge(full_decode=args.verify)
        return
    selected = [args.module] if args.module else list(MODULES)
    prepare(selected)
    if args.prepare_only:
        return
    for module in selected:
        folder = WORK / module
        slots = asyncio.Semaphore(2)
        voices = await asyncio.gather(*(speech(s["text"], folder, i, slots) for i, s in enumerate(MODULES[module]["scenes"])))
        encode(module, voices, folder)
        verify_entry(module, full_decode=args.verify)
    if len(selected) == len(MODULES):
        merge(full_decode=False)


if __name__ == "__main__":
    asyncio.run(main())
