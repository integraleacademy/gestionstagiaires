"""Fictional individual productions for APS v10.

PRODUCTIONS contains learner input documents plus post-submission coaching data.
The runtime must withhold rubric.expected and model_response until submission.
There is no automatic professional or trainer certification in this dataset.
The builder replaces the section's existing transfer; it keeps its duration.
"""
from copy import deepcopy

from scripts.aps62_v10.radio_demonstrations import RADIO_DEMONSTRATIONS, dialogue_text


FEEDBACK_NOTICE = (
    "Comparez votre production aux critères et au modèle. Plusieurs formulations "
    "peuvent convenir. Cette auto-évaluation ne constitue ni une validation par un "
    "formateur ni une attestation de compétence professionnelle."
)
FICTION_NOTICE = (
    "Dossier entièrement fictif pour l'entraînement. Les noms, références et "
    "consignes locales ci-dessous ne sont pas utilisables sur un site réel."
)


def _field(key, label, help_text, minimum=35, maximum=1600):
    return {"id": key, "label": label, "help": help_text, "required": True,
            "multiline": True, "min_chars": minimum, "max_chars": maximum}


def _criterion(key, label, expected):
    return {"id": key, "label": label, "expected": expected}


def _case(section, title, brief, documents, fields, rubric, model, **extra):
    return {
        "id": section + "-production", "title": title, "brief": brief,
        "fiction_notice": FICTION_NOTICE, "documents": documents,
        "response_fields": fields, "rubric": rubric, "model_response": model,
        "feedback_notice": FEEDBACK_NOTICE, "trainer_validation": False,
        **extra,
    }


THREAT_CALL_AUDIO = {
    "id": "aps62-12-05-appel-exercice-v10",
    "title": "Appel fictif reçu au poste des Ateliers Rive",
    "turns": [
        {"speaker": "Agent", "text": "Poste de sécurité des Ateliers Rive, bonjour."},
        {"speaker": "Appelant", "text": "Écoutez bien. Dans vingt minutes, il y aura un grave incident dans la salle après la verrière. Faites partir les gens."},
        {"speaker": "Agent", "text": "De quelle verrière parlez-vous ? Il y en a deux sur le site."},
        {"speaker": "Appelant", "text": "Au fond. Vous avez entendu. Je ne répondrai plus."},
        {"speaker": "Agent", "text": "Pouvez-vous préciser la salle concernée ?"},
    ],
    "ending": "La communication est interrompue, sans autre réponse.",
    "source_notice": "Scène de formation fictive ; aucune menace réelle.",
}
THREAT_CALL_AUDIO["transcript"] = "\n".join(
    f"{turn['speaker']} : {turn['text']}" for turn in THREAT_CALL_AUDIO["turns"]
) + "\n[La communication est interrompue, sans autre réponse.]"
THREAT_CALL_AUDIO["narration_text"] = " ".join(
    f"{turn['speaker']}. {turn['text']}" for turn in THREAT_CALL_AUDIO["turns"]
) + " La communication est interrompue, sans autre réponse."


PRODUCTIONS = {
    "aps62-01-02": _case(
        "aps62-01-02", "Préparer une affectation à partir de trois dossiers",
        "Vous êtes au bureau de prise de service du site fictif Boréal, le 14 octobre 2026 à 7 h 30. "
        "Le responsable vous demande une note sur trois dossiers pour une mission de surveillance humaine à 8 heures. "
        "Lisez les références, distinguez ce qui est vérifié de ce qui manque, puis formulez la suite à proposer. "
        "Vous ne délivrez aucun titre et ne vous substituez pas au service habilité.",
        [
            {"title": "Mission du jour et contrôle interne", "text": "Surveillance humaine et contrôle des accès du site Boréal, 8 h–16 h. Le responsable habilité décide de l'affectation après contrôle de concordance identité, activité et statut du titre par le canal officiel.",
             "rows": [["Rôle au poste", "Préparer les contrôles et signaler les écarts ; ne pas déclarer seul un titre valide à partir d'une capture."], ["Continuité", "En cas de dossier non clarifié, informer immédiatement le responsable pour organiser un remplacement régulier."]]},
            {"title": "Dossier A — Camille Durand (fictif)", "text": "Identité présentée : Camille Durand. Diplôme APS joint.",
             "rows": [["Vérification officielle consignée à 7 h 20", "Camille Durand ; activité : surveillance humaine ; statut valide pour le 14 octobre 2026."], ["Référence interne", "Vérification RH-31, auteur habilité identifié."], ["Préparation au site", "Accueil et consignes du poste tracés ; affectation à confirmer par le responsable."]]},
            {"title": "Dossier B — Noor Martin (fictif)", "text": "Diplôme et identité de Noor Martin joints. Une page de vérification est classée dans le même dossier.",
             "rows": [["Page de vérification jointe", "Noémie Martin ; activité : surveillance humaine ; résultat daté du 14 octobre 2026."], ["Message reçu", "« Les noms se ressemblent, c'est probablement la bonne page. »"], ["Autre contrôle", "Aucun résultat concordant avec Noor Martin n'est disponible au poste."]]},
            {"title": "Dossier C — Alex Petit (fictif)", "text": "Identité d'Alex Petit et diplôme APS joints. Un document est présenté comme un récépissé de renouvellement.",
             "rows": [["Copie fournie", "La page relative à la portée et aux conditions du récépissé manque."], ["Service habilité", "Aucune vérification de cette situation n'est consignée au poste."], ["Message de planning", "« Affectation urgente, la copie sera complétée plus tard. »"]]},
        ],
        [_field("dossiers", "Votre analyse des dossiers A, B et C", "Pour chaque dossier : source disponible, concordance ou manque, conclusion limitée à ce que le dossier permet.", 100, 1900),
         _field("suite", "Votre message au responsable de l'affectation", "Proposez la vérification manquante et la mesure d'organisation avant 8 heures, sans inventer un résultat officiel.", 60, 1100)],
        [_criterion("concordance", "J'ai rapproché identité, activité, date et source.", "A possède des éléments concordants pour la mission annoncée ; la décision d'affectation reste au responsable. B comporte une autre identité malgré un nom ressemblant."),
         _criterion("recepisse", "Je n'ai pas présumé l'effet d'une copie incomplète.", "C ne permet pas de conclure au maintien ou à l'absence du droit d'exercer : portée du récépissé et situation doivent être vérifiées par le service habilité."),
         _criterion("organisation", "Ma suite est praticable avant la prise de poste.", "Faire clarifier B et C sans les affecter sur les seules pièces incertaines ; prévenir le responsable pour une organisation ou un remplacement régulier, sans présenter le diplôme comme une autorisation provisoire.")],
        {"dossiers": "A : la vérification RH-31 de 7 h 20 concorde avec l'identité de Camille Durand, la surveillance humaine et le jour de la mission. La préparation au site est tracée ; je transmets au responsable pour décision d'affectation. B : la vérification concerne Noémie Martin, pas Noor Martin. Le droit d'exercer de Noor n'est donc pas établi par cette page. C : la copie du récépissé est incomplète ; je ne peux pas déterminer sa portée ni la situation actuelle d'Alex à partir de ces éléments.",
         "suite": "Pour le service de 8 heures, merci de faire vérifier par le canal habilité l'identité et la situation de Noor Martin, ainsi que la portée du récépissé et le statut d'Alex Petit. Je ne propose pas leur affectation sur ces seules copies. Si la vérification n'est pas obtenue avant la prise de poste, merci d'organiser une solution régulière. Le dossier A peut être soumis à votre décision avec les références vérifiées."}),
    "aps62-01-04": _case(
        "aps62-01-04", "Contrôler une dotation avant un poste d'entrepôt",
        "Vous prenez une mission ordinaire de surveillance privée dans un entrepôt, hors mission relevant des règles particulières de sûreté aéronautique. "
        "La dotation est posée sur une table avant votre prise de poste. Comparez sa fiche au contrôle réalisé et rédigez une demande de correction. "
        "Les dimensions ci-dessous sont des mesures, pas une image à l'échelle.",
        [
            {"title": "Repère réglementaire fourni pour cet exercice", "text": "Arrêté du 18 juillet 2023, articles 1 à 4. Pour cette mission : numéro correspondant aux sept derniers chiffres du numéro unique de bénéficiaire, en Arial 36 sur bande 54 × 15 mm noir sur blanc ou blanc sur noir, en haut à gauche de la poitrine au porté. L'insigne de l'entreprise ou du service interne est en dessous, d'une taille au moins équivalente à un carré de 50 mm. Au dos : SÉCURITÉ PRIVÉE sur une ligne, centrée, majuscules Arial 76, rétro-réfléchissantes blanches sur fond noir. Les éléments restent visibles en permanence.",
             "rows": [["Orientation", "Gauche au porté = gauche de la personne qui porte la veste ; vue de face, elle se trouve à droite de l'image."], ["Limite", "Ce dossier ne traite pas les missions relevant des dispositions particulières de sûreté aéronautique."]]},
            {"title": "Bon de dotation fictif D-44", "text": "Veste prévue pour l'entrepôt ; numéro pédagogique fictif 7654321, sans lien avec une personne réelle.",
             "rows": [["Numéro", "7654321 ; Arial 36 ; bande 54 × 15 mm noir sur blanc."], ["Insigne", "Entreprise fictive Boréal Sécurité, 50 × 50 mm."], ["Dos", "Texte prévu : SÉCURITÉ PRIVÉE, Arial 76 blanc rétro-réfléchissant sur noir, une ligne centrée."]]},
            {"title": "Constat avant port", "text": "Contrôle de la veste réellement reçue, et non du seul bon de dotation.",
             "rows": [["Poitrine gauche au porté", "Insigne entreprise cousu au niveau supérieur ; bande numéro placée en dessous, masquée par le rabat fermé de la poche."], ["Poitrine droite au porté", "Aucun marquage."], ["Dos", "Les mots SÉCURITÉ et PRIVÉE sont superposés sur deux lignes. Taille, couleurs et caractère rétro-réfléchissant conformes à la fiche."], ["Présentation proposée", "Le fournisseur dit : « Le bon est conforme ; inutile de vérifier la veste. »"]]},
        ],
        [_field("ecarts", "Les écarts observés et leurs références", "Décrivez les emplacements au porté. Distinguez les caractéristiques conformes de celles qui doivent être corrigées.", 90, 1600),
         _field("correction", "Votre demande de correction avant la prise de poste", "Écrivez le message au responsable de dotation, puis une phrase de présentation au public.", 70, 1300)],
        [_criterion("orientation", "J'ai utilisé le bon côté et le bon ordre.", "En haut à gauche au porté : bande numéro, puis insigne en dessous. Le contrôle porte sur la veste reçue ; le bon de dotation ne suffit pas."),
         _criterion("visibilite", "J'ai vérifié la visibilité et le dos.", "Le rabat masque le numéro ; il doit rester visible. La mention du dos doit être sur une ligne centrée, même si la police et les matériaux indiqués sont conformes."),
         _criterion("suite", "Je demande une dotation vérifiée et présente clairement mon rôle.", "Faire corriger ou remplacer la veste par le circuit de dotation avant le poste, sans fabriquer un attribut ressemblant à une force publique. La présentation indique agent de sécurité privée du site.")],
        {"ecarts": "Sur la veste reçue, l'ordre de la poitrine gauche au porté est inversé : le numéro doit être au niveau supérieur, l'insigne en dessous. Le rabat masque le numéro ; sa présence ne suffit donc pas. Au dos, les deux mots sont répartis sur deux lignes alors qu'une seule ligne centrée est requise pour cette mission. Les dimensions, polices, couleurs et propriétés annoncées ne sont pas en cause d'après le constat fourni.",
         "correction": "Merci de faire corriger ou remplacer la veste D-44 avant mon affectation : numéro 7654321 fictif en haut à gauche au porté et visible, insigne entreprise en dessous, mention SÉCURITÉ PRIVÉE sur une ligne centrée au dos. Je vérifierai la dotation réelle après correction. Au public : « Bonjour, je suis l'agent de sécurité privée du site ; je vérifie votre autorisation d'accès. »"}),
    "aps62-08-02": _case(
        "aps62-08-02", "Composer une transmission exploitable au PC",
        "Vous êtes l'agent Ronde 4 sur le site fictif Orme. À partir des notes ci-dessous, rédigez le message que vous prononceriez maintenant, puis la confirmation après la réponse du PC. "
        "Ne transformez pas une action demandée en action déjà accomplie.",
        [
            {"title": "Notes de terrain — 10 h 18", "text": "Ronde 4, bâtiment C, rez-de-chaussée, passage piéton intérieur entre la réserve 2 et l'escalier nord. Une roue détachée de chariot est au milieu du passage. Aucun blessé n'est vu ni signalé à l'agent.",
             "rows": [["Actions réalisées", "Passage maintenu hors d'usage au point de contrôle, sans déplacer la roue ; visiteurs orientés par le passage intérieur S, autorisé et vérifié libre."], ["Ce qui manque", "Service logistique non encore averti ; enlèvement non réalisé."], ["Demande utile", "Faire prendre en charge l'enlèvement par la logistique et confirmer le destinataire."], ["Communication", "Canal opérationnel 1, destinataire PC ; pas de données personnelles à transmettre."]]},
            {"title": "Réponse fictive du PC, à utiliser pour votre confirmation", "text": "« Ronde 4 de PC, reçu : passage entre réserve 2 et escalier nord, roue de chariot, accès protégé et détour S utilisé. J'avertis la logistique. Maintenez la mesure et signalez son arrivée. »", "rows": []},
        ],
        [_field("message", "Votre premier message au PC", "Écrivez les paroles exactes : indicatif, lieu, fait, danger utile, mesures réalisées et besoin. Restez bref.", 100, 950),
         _field("confirmation", "Votre confirmation après la réponse du PC", "Reformulez la suite et ce que vous devez surveiller. N'annoncez pas que la logistique est déjà arrivée.", 35, 550)],
        [_criterion("localisation", "Mon destinataire peut localiser l'événement sans deviner.", "PC, Ronde 4, bâtiment C, rez-de-chaussée, passage entre réserve 2 et escalier nord. Un lieu abrégé reste acceptable s'il conserve ces repères utiles."),
         _criterion("statut", "Je distingue constat, protection réalisée et intervention demandée.", "Roue de chariot au milieu du passage ; passage protégé et détour S vérifié utilisé ; aucun blessé connu, sans affirmer un bilan du site entier ; enlèvement encore à organiser."),
         _criterion("relais", "Le besoin et la confirmation sont explicites.", "Demande de logistique pour l'enlèvement ; après réponse, maintien de la mesure et signalement de l'arrivée. Aucune réparation ou arrivée inventée.")],
        {"message": "PC de Ronde 4. À 10 h 18, bâtiment C, rez-de-chaussée, passage entre réserve 2 et escalier nord : une roue de chariot obstrue le cheminement. Aucun blessé ne m'est signalé. Le passage est protégé et les visiteurs passent par S, vérifié libre. Demandez la logistique pour l'enlèvement, s'il vous plaît.",
         "confirmation": "PC de Ronde 4, reçu. Vous avertissez la logistique ; je maintiens la protection et le détour S, puis je vous signale l'arrivée de l'intervenant et l'évolution du passage."},
        oral_prompt="Après rédaction, prononcez votre premier message à voix haute. Vérifiez qu'un collègue pourrait retrouver le lieu et comprendre votre besoin sans relire les notes."),
    "aps62-08-04": _case(
        "aps62-08-04", "Rédiger un compte rendu depuis des notes brutes",
        "À la fin d'une ronde sur le site fictif Orme, rédigez un compte rendu destiné au chef de poste. "
        "Le lecteur n'a pas vos notes sous les yeux. Séparez les constatations personnelles, la déclaration d'un témoin et l'état des démarches. "
        "Ne cherchez pas à désigner un auteur que les pièces ne permettent pas d'identifier.",
        [
            {"title": "Carnet de l'agent — 14 octobre 2026", "text": "Auteur : agent fictif Nora L., indicatif Ronde 4.",
             "rows": [["16 h 42 — vu par l'agent", "Bâtiment C, porte de la réserve 2 : vitre fissurée. Aucun geste de dégradation observé."], ["16 h 43 — déclaration", "Le salarié fictif Karim B. dit avoir entendu un choc « vers 16 h 35 », sans avoir vu son origine."], ["16 h 44 — action", "Accès proche de la vitre tenu à l'écart selon la consigne ; cheminement alternatif intérieur S maintenu libre."], ["16 h 46 — transmission", "PC avisé. Le PC annonce contacter la maintenance."], ["16 h 50 — état", "Maintenance non encore arrivée ; cause de la fissure inconnue."], ["Note non vérifiée", "Une personne de passage dit : « Ce sont sûrement les livreurs. » Aucun fait ni identité précise fournis."]]},
            {"title": "Repère de rédaction du site", "text": "Le compte rendu indique date, auteur, lieu, chronologie, sources, mesures et suites ouvertes. Un horaire estimé est marqué comme tel. Les propos utiles sont attribués ; une hypothèse n'est pas écrite comme un constat.",
             "rows": [["Diffusion", "Chef de poste et responsable désigné par le canal professionnel."], ["Clôture", "Une maintenance annoncée ne suffit pas à annoncer une réparation."]]},
        ],
        [_field("rapport", "Votre compte rendu", "Rédigez un texte compréhensible sans les pièces jointes. Vous pouvez utiliser de courts paragraphes ou une chronologie.", 220, 2600),
         _field("suivi", "La suite à transmettre à la relève", "Indiquez ce qui reste ouvert et quelle confirmation sera nécessaire.", 50, 800)],
        [_criterion("faits", "J'attribue chaque information à sa vraie source.", "La vitre fissurée est constatée à 16 h 42 ; le choc vers 16 h 35 est rapporté par Karim B., qui n'en a pas vu l'origine. L'accusation vague contre les livreurs n'établit rien et ne doit pas devenir une conclusion."),
         _criterion("chronologie", "Les heures exactes et estimées ne sont pas confondues.", "Conserver la date, l'auteur, les repères du lieu, le constat à 16 h 42 et l'heure approximative du témoignage. Ne pas remplacer l'une par l'autre."),
         _criterion("actions", "Les actions et les suites sont séparées.", "Protection à 16 h 44, PC avisé à 16 h 46 ; contact maintenance annoncé, arrivée et réparation non confirmées à 16 h 50. Maintenir le suivi de la protection jusqu'à sécurisation confirmée.")],
        {"rapport": "Compte rendu du 14 octobre 2026 — Nora L., Ronde 4. À 16 h 42, au bâtiment C, porte de la réserve 2, j'ai constaté une vitre fissurée. Je n'ai pas observé la dégradation se produire. À 16 h 43, Karim B. m'a déclaré avoir entendu un choc vers 16 h 35, sans en avoir vu l'origine. À 16 h 44, l'accès proche de la vitre a été tenu à l'écart selon la consigne et le cheminement intérieur S a été maintenu libre. Le PC a été avisé à 16 h 46 et a annoncé contacter la maintenance. À 16 h 50, la maintenance n'était pas arrivée. La cause et l'auteur éventuel de la fissure ne sont pas établis.",
         "suivi": "À reprendre : protection de l'accès près de la réserve 2 et disponibilité du cheminement S. Attendre le retour du PC sur la maintenance, tracer l'arrivée et les actions de l'intervenant. Ne clore qu'après confirmation de la sécurisation prévue ; aucune réparation n'est confirmée à 16 h 50."}),
    "aps62-10-06": _case(
        "aps62-10-06", "Rapprocher une étiquette et la bonne FDS",
        "Vous consultez au poste les copies documentaires d'un produit stocké dans un local technique. "
        "Personne n'est exposé et aucune fuite n'est signalée. Un responsable vous demande quel document doit accompagner le signalement d'un étiquetage à vérifier. "
        "Vous travaillez uniquement sur les copies : ni approche, ni essai, ni manipulation du produit.",
        [
            {"title": "Copie d'étiquette — produit pédagogique non commercialisé", "text": "NET-ALC P17 — nettoyant industriel fictif. Fabricant fictif : Laboratoire Pédago. Mention d'avertissement : DANGER. Pictogramme décrit : corrosion, liquide attaquant une main et un métal (GHS05). Mention : provoque de graves brûlures de la peau et de graves lésions des yeux.",
             "rows": [["Code produit", "P17"], ["Usage annoncé", "Nettoyant alcalin, usage professionnel prévu par la procédure locale."], ["Limite pédagogique", "Cette étiquette inventée ne permet de choisir aucun équipement ni geste sur un produit réel."]]},
            {"title": "FDS A — extrait pédagogique", "text": "Produit : NET-ALC P17. Code P17. Version A4, document de formation fictif.",
             "rows": [["Rubrique 2 — dangers", "Corrosion ; brûlures de la peau et lésions oculaires graves."], ["Rubrique 4 — premiers secours", "Les informations de premiers secours figurent dans cette rubrique ; en situation réelle, suivre les instructions compétentes et la FDS complète du produit exact."], ["Rubrique 6 — dispersion accidentelle", "Éviter l'exposition ; empêcher l'accès selon l'organisation du site et faire intervenir le personnel compétent. Aucun nettoyage improvisé par l'agent non formé."], ["Rubrique 8 — protection", "Choix réservé à l'évaluation de la tâche, aux consignes et aux personnes compétentes ; des gants ordinaires ne constituent pas une garantie."]]},
            {"title": "FDS B — extrait pédagogique", "text": "Produit : NET-ALC P71. Code P71. Version B8, plus récente que A4 ; produit différent.",
             "rows": [["Rubrique 2 — dangers", "Cette rubrique décrit uniquement P71."], ["Message du magasinier", "« Le nom ressemble beaucoup et la date est plus récente : prenons celle-ci. »"]]},
            {"title": "Consigne locale fictive C-PROD", "text": "Le poste transmet le nom et le code déjà disponibles sur les copies, la correspondance documentaire et les points incertains au responsable produits. Il ne déduit pas un équipement de protection d'un pictogramme seul.",
             "rows": [["Si une fuite est ensuite signalée", "Déclencher l'alerte et la protection prévues depuis une position sûre, sans entrer pour confirmer le produit ni tenter de le neutraliser."]]},
        ],
        [_field("document", "Le document à rapprocher et l'information utile", "Citez le nom, le code, la FDS correspondante et deux informations que vous avez réellement lues. Expliquez pourquoi l'autre FDS ne convient pas.", 100, 1400),
         _field("transmission", "Votre transmission au responsable produits", "Indiquez ce qui est établi, la limite de votre rôle et la suite si une fuite était signalée. Ne prescrivez pas un geste chimique ou un EPI.", 80, 1100)],
        [_criterion("identite", "La correspondance repose sur le produit exact.", "P17 sur l'étiquette correspond à FDS A/P17, pas à P71. La date plus récente et la ressemblance du nom ne corrigent pas un code produit différent."),
         _criterion("lecture", "J'extrais des informations du document.", "Corrosion / brûlures cutanées et lésions oculaires graves ; premiers secours en rubrique 4, dispersion en rubrique 6, protections en rubrique 8. Au moins deux informations utiles sont identifiées sans en inventer."),
         _criterion("limites", "Je transmets sans transformer la lecture en intervention.", "Travail sur copies uniquement ; vérification par le responsable produits. Si fuite, alerte et protection depuis une position sûre, sans essai, mélange, neutralisation ni choix improvisé de protections.")],
        {"document": "La copie concerne NET-ALC P17, code P17 : la FDS A est celle à rapprocher. Elle indique en rubrique 2 un danger de corrosion, avec brûlures de la peau et lésions oculaires graves. La rubrique 6 concerne les dispersions accidentelles ; la rubrique 4 porte sur les premiers secours. La FDS B concerne P71, un autre produit : sa date plus récente ne la rend pas applicable à P17.",
         "transmission": "Responsable produits : les copies disponibles rapprochent l'étiquette NET-ALC P17 de la FDS A/P17. Merci de vérifier la correspondance avec le dossier produit et la version complète applicable. Aucun incident ni exposition n'est signalé dans ce cas. Je ne choisis pas d'EPI sur le seul pictogramme. Si une fuite est signalée, j'applique le circuit d'alerte et de protection depuis une position sûre, sans manipulation ni neutralisation."}),
    "aps62-12-05": _case(
        "aps62-12-05", "Restituer un appel sans compléter les blancs",
        "Il est 14 h 07 aux Ateliers Rive, site fictif. Écoutez l'appel de formation ou utilisez sa transcription accessible. "
        "Vous avez une liaison distincte avec le collègue du PC. Rédigez la fiche puis le message immédiat au PC. "
        "L'appelant n'est pas une autorité qui peut décider la mise en sécurité du site.",
        [
            {"title": "Journal de réception", "text": "Appel reçu le 14 octobre 2026 à 14 h 07 au poste Ateliers Rive. Numéro affiché : masqué. Aucun nom donné. La communication est interrompue après la dernière question de l'agent.",
             "rows": [["Plan disponible au poste", "Le site comporte une verrière Nord et une verrière Sud ; plusieurs salles se trouvent derrière chacune."], ["Éléments disponibles", "Aucune observation de danger ni confirmation technique n'est ajoutée à ce dossier."], ["Communication interne", "Canal de liaison distinct : PC. Le PC active la chaîne d'alerte prévue et coordonne les décisions du site."]]},
            {"title": "Consigne locale d'alerte fictive", "text": "Transmettre rapidement les paroles utiles, l'heure, la localisation annoncée et ses incertitudes, sans attendre un second appel. Conserver la fiche par le circuit autorisé. Rester calme, ne pas provoquer ni rappeler l'appelant de sa propre initiative.",
             "rows": [["Décision sur le site", "Les consignes de protection sont données par la chaîne compétente, pas déduites d'un ordre de l'appelant."], ["Échéance citée", "Présenter une échéance comme annoncée par l'appelant ; elle n'est pas une confirmation de ce qui va se produire."]]},
        ],
        [_field("fiche", "Votre fiche de réception", "Citez les mots utiles aussi fidèlement que possible, l'heure, le numéro disponible, le lieu annoncé et ce qui n'a pas pu être précisé.", 140, 1800),
         _field("alerte", "Votre message immédiat au PC", "Rédigez ce que vous diriez. Signalez la menace et ses limites, demandez le relais, sans ordonner vous-même un déplacement sur la seule parole de l'appelant.", 100, 1000)],
        [_criterion("fidelite", "Les paroles et les données de réception restent fidèles.", "Réception à 14 h 07, numéro masqué, pas de nom. L'appelant annonce un grave incident « dans vingt minutes » et cite « la salle après la verrière », puis « au fond ». La ligne est interrompue sans précision."),
         _criterion("incertitude", "Je n'ai pas inventé la verrière ou la salle.", "Deux verrières existent ; Nord/Sud et salle précise restent inconnus. On peut calculer un repère indicatif vers 14 h 27 en l'attribuant à l'annonce, mais il n'est ni nécessaire ni certain."),
         _criterion("action", "L'alerte est rapide, sans diagnostic ni ordre supposé.", "Transmettre au PC maintenant, conserver la fiche et ses incertitudes. Ne pas attendre une confirmation, ne pas présenter « faites partir les gens » comme une instruction validée du dispositif.")],
        {"fiche": "14 octobre 2026, 14 h 07, poste Ateliers Rive. Numéro masqué, appelant non identifié. Paroles : « Dans vingt minutes, il y aura un grave incident dans la salle après la verrière. Faites partir les gens. » À la question sur la verrière concernée, l'appelant répond : « Au fond. Vous avez entendu. Je ne répondrai plus. » Aucune salle précise ni verrière Nord ou Sud n'a pu être obtenue. La communication est interrompue. L'échéance est celle annoncée par l'appelant ; aucun danger technique n'est confirmé par ce dossier.",
         "alerte": "PC de Poste Ateliers Rive. Appel menaçant reçu à 14 h 07, numéro masqué. L'appelant annonce un grave incident dans vingt minutes, dans « la salle après la verrière ». Le site a deux verrières et le lieu reste indéterminé ; la ligne a coupé avant précision. Activez la chaîne d'alerte prévue. Je conserve la fiche et les paroles exactes ; aucune consigne de déplacement n'est validée par cet appel."},
        audio={"title": THREAT_CALL_AUDIO["title"], "src": "media/aps62/v10/aps62-12-05-appel-exercice.mp3", "transcript": THREAT_CALL_AUDIO["transcript"]},
        audio_script_id=THREAT_CALL_AUDIO["id"],
        oral_prompt="Prononcez votre alerte au PC à voix haute. Distinguez la menace annoncée de ce que vous avez personnellement vérifié."),
    "aps62-13-01": _case(
        "aps62-13-01", "Préparer une saisie et corriger sans effacer",
        "Vous utilisez votre compte individuel dans une main courante de formation du site fictif Orme. "
        "Rédigez le contenu de l'entrée nouvelle, puis de la rectification liée à une entrée existante. "
        "Il s'agit d'un entraînement de rédaction et de traçabilité ; ce formulaire ne prouve pas à lui seul votre maîtrise d'un logiciel professionnel.",
        [
            {"title": "Événement à saisir maintenant", "text": "Nous sommes le 14 octobre 2026 à 9 h 18. Votre indicatif : Accueil 3. Votre compte de formation est individuel.",
             "rows": [["Fait constaté", "À 9 h 12, le lecteur du portillon P3 n'a pas répondu à deux présentations du badge de test prévu par la procédure."], ["Mesure", "À 9 h 13, maintien du passage par l'accès contrôlé P2, disponible et prévu au mode dégradé."], ["Transmission", "PC avisé à 9 h 14 ; prise en charge technique demandée, non confirmée à 9 h 18."], ["Limite", "La cause du défaut n'est pas établie."]]},
            {"title": "Entrée existante MC-118 à rectifier", "text": "Entrée de votre compte saisie à 9 h 10 : « À 8 h 50, maintenance arrivée pour le défaut d'éclairage du couloir nord. »",
             "rows": [["Vérification à 9 h 16", "Le registre d'accès intervenants confirme une arrivée à 9 h 02. Vous reconnaissez une erreur de report d'heure dans MC-118."], ["À conserver", "La date, l'auteur et le texte initial de MC-118 restent consultables."], ["Fonction prévue", "Ajouter une rectification liée : référence initiale, élément corrigé, nouvelle donnée, source, motif, auteur et heure de rectification."]]},
        ],
        [_field("entree", "Contenu de la nouvelle entrée", "Indiquez les heures des faits et l'heure de saisie, le lieu, les actions, l'état actuel et votre auteur/indicatif.", 130, 1500),
         _field("rectification", "Rectification liée à MC-118", "Corrigez l'heure à partir de la source fournie ; gardez la trace du texte initial et expliquez le motif.", 100, 1300)],
        [_criterion("nouvelle", "Ma nouvelle entrée permet de suivre P3 sans inventer sa réparation.", "P3 sans réponse à 9 h 12 ; mode dégradé P2 à 9 h 13 ; PC avisé à 9 h 14 ; saisie à 9 h 18 sous Accueil 3 ; cause et prise en charge technique non confirmées."),
         _criterion("correction", "La correction est liée, sourcée et attribuée.", "MC-118 : heure d'arrivée corrigée de 8 h 50 à 9 h 02 ; registre intervenants vérifié à 9 h 16 et erreur de report reconnue ; rectification actuelle datée et attribuée, sans supprimer l'original."),
         _criterion("controle", "Je distingue contenu préparé et enregistrement effectif.", "Le texte est prêt à saisir ; après une vraie saisie, vérifier le dossier, l'enregistrement et la visibilité pour la relève. La préparation de ce formulaire n'atteste pas une transmission effective dans un logiciel réel.")],
        {"entree": "14 octobre 2026 — saisie à 9 h 18 — Accueil 3. À 9 h 12, le lecteur du portillon P3 n'a pas répondu à deux présentations du badge de test prévu. À 9 h 13, le passage a été maintenu par l'accès contrôlé P2 selon le mode dégradé. PC avisé à 9 h 14 ; prise en charge technique demandée mais non confirmée à 9 h 18. Cause non établie ; suivi du défaut P3 à maintenir.",
         "rectification": "14 octobre 2026, 9 h 18 — Accueil 3 — rectification liée à MC-118, sans suppression de l'entrée initiale. L'heure d'arrivée de la maintenance pour le couloir nord est 9 h 02, au lieu de 8 h 50. Source : registre d'accès intervenants vérifié à 9 h 16. Motif : erreur de report d'heure reconnue par l'auteur de MC-118. Les autres éléments de l'entrée ne sont pas modifiés."}),
    "aps62-13-02": _case(
        "aps62-13-02", "Reprendre trois notes après une panne",
        "L'accès au logiciel de formation du poste Accueil 2, sur le site fictif Boréal, est rétabli à 12 h 20 après une panne locale commencée à 11 h 40. Les autres postes, dont Logistique 1, sont restés opérationnels. "
        "Comparez le journal de secours et les entrées visibles. Préparez la reprise sans doublon ni antidatage, puis un message de contrôle à la relève.",
        [
            {"title": "Journal papier de secours — auteur Accueil 2", "text": "Notes prises pendant l'indisponibilité selon la procédure locale.",
             "rows": [["S-01 — fait 11 h 45, note 11 h 46", "Interphone I2 inaudible. PC averti à 11 h 47 ; orientation des visiteurs vers l'accueil A."], ["S-02 — fait et note 11 h 55", "Prestataire annoncé au quai 1 ; identité et rendez-vous vérifiés par le contact logistique ; attente à l'emplacement prévu."], ["S-03 — fait 12 h 05, note 12 h 06", "Réponse du technicien : interphone I2 testé à nouveau et fonctionnement rétabli selon son compte rendu. Accueil 2 n'a pas effectué ce test."]]},
            {"title": "Écran de reprise à 12 h 20", "text": "Historique consulté sous votre compte individuel avant import.",
             "rows": [["MC-204 — enregistré à 11 h 56 par Logistique 1", "Prestataire du quai 1 : même rendez-vous et même contrôle que S-02, référence dossier L-19."], ["Interphone I2", "Aucune entrée correspondant à S-01 ou S-03 dans l'historique consulté."], ["Correspondance", "La comparaison de référence L-19, heure, contact et emplacement confirme que S-02 et MC-204 décrivent le même événement."]]},
            {"title": "Procédure fictive de reprise", "text": "Conserver le support de secours. Reporter l'heure des faits, l'heure de consignation papier et l'heure réelle de saisie numérique. Relier les suites au même incident. Lorsqu'une entrée concordante existe, tracer le rapprochement au lieu de créer un deuxième événement.",
             "rows": [["Fin de reprise", "Vérifier les références créées, les liens et la visibilité pour la relève ; ne pas assimiler logiciel rétabli à historique vérifié."], ["Source d'une résolution", "Attribuer un test déclaré par un technicien ; ne pas le présenter comme effectué par l'agent."]]},
        ],
        [_field("reprise", "Votre plan de reprise et les textes à enregistrer", "Traitez S-01, S-02 et S-03 séparément. Pour les textes nouveaux, utilisez 12 h 20 comme heure réelle de saisie.", 200, 2400),
         _field("controle", "Votre compte rendu de contrôle à la relève", "Indiquez les rapprochements, le support conservé et ce qui doit être vérifié dans l'outil après la saisie.", 70, 1000)],
        [_criterion("doublon", "J'ai traité le doublon sur des éléments concordants.", "S-02 correspond à MC-204/L-19 : tracer le rapprochement avec la note de secours, ne pas créer un nouvel événement prestataire."),
         _criterion("horaires", "Je conserve trois types d'heure et les liens utiles.", "S-01 : fait 11 h 45, note 11 h 46, saisie 12 h 20 ; S-03 : fait 12 h 05, note 12 h 06, saisie 12 h 20, suite liée à I2. Ne pas antidater la saisie numérique."),
         _criterion("source", "La remise en service et la fin de reprise sont vérifiées à leur juste niveau.", "Attribuer le test et le rétablissement au compte rendu du technicien ; Accueil 2 n'a pas fait le test. Conserver le papier et contrôler enregistrement, références et accès à la relève.")],
        {"reprise": "S-01 : créer l'incident I2 sous mon compte à 12 h 20. Fait à 11 h 45, consigné sur papier à 11 h 46 : interphone I2 inaudible, PC averti à 11 h 47, visiteurs orientés vers A. S-02 : rapprocher la note de MC-204, dossier L-19 ; même événement confirmé par référence, heure, contact et lieu. Ne pas créer de doublon. S-03 : ajouter une suite liée à l'incident I2, saisie à 12 h 20, fait à 12 h 05 et note papier à 12 h 06 : le technicien rapporte un test et un fonctionnement rétabli. Je n'ai pas effectué personnellement ce test.",
         "controle": "Le journal papier est conservé. La reprise distingue S-01/I2, le rapprochement S-02 avec MC-204/L-19 et la suite S-03 liée à I2. Après saisie, je vérifie les références, les liens, les heures et la visibilité pour la relève. Je confirme le contrôle effectif de l'historique ; le seul retour du logiciel ne suffit pas à le prouver."}),
    "aps62-15-02": _case(
        "aps62-15-02", "Appliquer une matrice de droits à trois arrivées",
        "Vous tenez le point C1 du forum fictif Latitude, le 14 octobre 2026 à 16 h 10. "
        "Trois personnes arrivent. À partir de la matrice et des confirmations fournies, rédigez une décision motivée pour chacune et le bref message à adresser au responsable. "
        "Ne créez ni droit permanent ni priorité non prévue.",
        [
            {"title": "Plan de zones — extrait du briefing V6 validé", "text": "Le point C1 sépare le hall public P du couloir technique T. L'espace presse R se rejoint depuis P par le contrôle C2. La voie S est réservée aux secours et doit rester libre.",
             "rows": [["P", "Hall public → C1 vers T ; → C2 vers R."], ["T", "Couloir technique : droit spécifique, éventuelles conditions d'accompagnement."], ["R", "Espace presse, desservi par C2."], ["S", "Voie secours ; ne sert pas de file d'attente ou de raccourci public."]]},
            {"title": "Matrice d'accès du jour", "text": "Tous les contrôles de concordance du détenteur restent applicables.",
             "rows": [["PUBLIC P", "Zone P, 9 h–19 h ; pas de droit T ou R."], ["PRESSE R", "Zones P et R, 9 h–18 h ; entrée de R par C2 ; pas de droit T."], ["TECH T", "Zone T, 15 h–16 h, avec accompagnement logistique identifié."], ["Extension", "Seul le responsable accréditations peut confirmer une extension, son secteur, son horaire et son accompagnement."]]},
            {"title": "Arrivées à C1 à 16 h 10", "text": "Les trois badges correspondent bien à leurs détenteurs ; les difficultés portent sur les droits et conditions.",
             "rows": [["Personne A", "Badge PRESSE R ; demande l'espace presse R en pensant passer par C1."], ["Personne B", "Badge TECH T ; dit avoir oublié un outil dans T. Pas d'accompagnant ; créneau initial terminé à 16 h."], ["Personne C", "Badge PUBLIC P ; rendez-vous technique mentionné dans une confirmation reçue par le canal accréditations authentifié."]]},
            {"title": "Confirmation reçue pour C", "text": "Le responsable accréditations confirme à 16 h 08 un accès exceptionnel de C à T de 16 h 10 à 16 h 25, accompagné par Logistique 2. Logistique 2 est annoncé mais pas encore au point C1.",
             "rows": [["À tracer", "Référence EX-9 ; identité concordante, créneau, secteur T et accompagnement Logistique 2."], ["Limite", "Aucune extension à R ni au reste de la journée."]]},
        ],
        [_field("decisions", "Vos trois décisions et leurs motifs", "Pour A, B et C : accès ou attente, raison documentaire, orientation ou vérification nécessaire.", 170, 2200),
         _field("message", "Votre message au responsable", "Rendez compte des points à traiter sans demander une validation déjà reçue ni supposer l'accompagnement présent.", 65, 950)],
        [_criterion("zones", "J'applique la zone et le cheminement au bon titre.", "A possède le droit R à 16 h 10, mais passe par C2 depuis P, pas par le couloir T. Le badge presse n'étend pas les droits techniques."),
         _criterion("temps", "Je tiens compte du créneau et de l'accompagnement.", "B : créneau T terminé et accompagnement absent ; demande d'extension au contact habilité, sans accès immédiat. C : extension EX-9 validée, mais attendre Logistique 2 avant l'entrée accompagnée."),
         _criterion("trace", "Je conserve la portée exacte de la confirmation.", "C limité à T, 16 h 10–16 h 25, avec Logistique 2 ; tracer la réalisation et ne pas élargir le droit. Garder la voie S libre.")],
        {"decisions": "A : son badge PRESSE R couvre R à 16 h 10. Je l'oriente depuis P vers C2, sans la faire traverser T. B : le droit TECH T expirait à 16 heures et aucun accompagnant n'est présent. Je maintiens l'attente au point prévu et demande une extension éventuelle au responsable accréditations. C : EX-9 confirme T de 16 h 10 à 16 h 25, mais avec Logistique 2. L'accompagnant n'est pas encore arrivé ; j'attends sa présence et vérifie la concordance avant le passage, puis je trace les conditions réalisées.",
         "message": "Accréditations de C1. A est orientée vers C2 pour R. B demande T après la fin de son créneau, sans accompagnant ; merci de traiter l'éventuelle extension. Pour C, EX-9 est reçu : attente de Logistique 2 avant l'accès à T, limité à 16 h 25. La voie secours S reste libre."}),
    "aps62-15-05": _case(
        "aps62-15-05", "Lire un plan puis formuler une consigne au public",
        "Vous êtes au point A2 du forum fictif Latitude. Une mise en sécurité du hall vient d'être demandée par le responsable du dispositif. "
        "Lisez le plan et les mises à jour horodatées avant d'écrire votre confirmation au PC puis les paroles destinées au public. "
        "Le but n'est pas d'improviser une stratégie générale : appliquez l'itinéraire réellement vérifié et les appuis attribués.",
        [
            {"title": "Plan pédagogique P8 — coordonnées du secteur", "image": "media/aps62/v10/plan-latitude.svg", "image_alt": "Plan fictif du forum Latitude : hall A2 relié à Porte Est B2, passage E C2 et Jardin D2 ; autre liaison vers Porte Sud A3 et rampe Sud B3. Atelier A1 et accès secours D3 sans liaison publique. L’état des passages est donné dans les messages horodatés.", "text": "Le quadrillage sert à localiser les points. Seules les liaisons indiquées ci-dessous sont praticables ; la proximité sur le quadrillage ne vaut pas autorisation de passage.",
             "rows": [["A1", "Cour atelier : zone technique, non ouverte au public."], ["A2", "Hall public ; votre poste."], ["B2", "Porte Est et début du cheminement E."], ["C2", "Passage couvert E, accessible au public lorsqu'il est vérifié libre."], ["D2", "Point d'accueil Jardin, accessible."], ["A3", "Porte Sud ; liaison vers B3."], ["B3", "Rampe Sud et issue vers le parking."], ["D3", "Accès secours ; voie à préserver."], ["Liaisons prévues", "A2–B2–C2–D2 ; A2–A3–B3. Aucune liaison publique vers A1 ou D3."]],
             "map": {"columns": ["A", "B", "C", "D"], "rows": ["1", "2", "3"], "cells": {"A1": "Atelier interdit", "A2": "Hall / poste", "B2": "Porte Est", "C2": "Passage E", "D2": "Accueil Jardin", "A3": "Porte Sud", "B3": "Rampe Sud", "D3": "Accès secours"}, "routes": [["A2", "B2", "C2", "D2"], ["A2", "A3", "B3"]], "alt": "Le hall A2 rejoint Jardin D2 par Porte Est B2 et passage E C2. L'autre chemin va du hall à Porte Sud A3 puis Rampe Sud B3. L'atelier A1 et la voie secours D3 ne sont pas des passages publics."}},
            {"title": "État reçu à 17 h 03", "text": "La rampe Sud B3 est encombrée par du matériel. La porte Est B2 est disponible ; l'état du passage couvert C2 n'est pas encore confirmé.",
             "rows": [["Proposition non validée", "Un exposant propose de passer directement par la cour atelier A1 parce qu'elle est proche."], ["Besoin d'aide", "Une personne au hall signale avoir besoin d'un accompagnement pour se déplacer ; aucune information médicale n'est nécessaire au message public."]]},
            {"title": "Message authentifié du PC — 17 h 05, état actuel", "text": "« Passage E C2 vérifié libre par Secteur Est. Utilisez A2–B2–C2–D2 vers Accueil Jardin. Appui 2 rejoint A2 pour l'accompagnement. Gardez D3 libre pour les secours ; rendez compte du mouvement et des difficultés. »",
             "rows": [["Statut de l'appui", "Appui 2 est annoncé, pas encore arrivé à A2."], ["Déclenchement", "Le responsable a demandé cette mise en sécurité ; le présent dossier ne demande pas à l'agent de décider seul une évacuation générale."]]},
        ],
        [_field("pc", "Votre confirmation au PC à 17 h 05", "Confirmez le trajet, la destination, la limite Sud et la situation de l'appui annoncé.", 80, 1000),
         _field("public", "Les paroles que vous adressez au public", "Utilisez des mots de terrain compréhensibles sans connaître le quadrillage. Mentionnez la direction et la destination sans diffuser de donnée personnelle.", 60, 800),
         _field("suivi", "Ce que vous surveillez et transmettez ensuite", "Indiquez le mouvement, les difficultés, l'accompagnement et la voie secours ; ne confondez pas annonce et arrivée effective.", 55, 900)],
        [_criterion("itineraire", "Mon trajet suit la dernière confirmation vérifiée.", "A2–B2–C2–D2 : hall, Porte Est, passage E, Jardin. Ne pas utiliser la rampe Sud encombrée, la cour atelier ni la voie secours comme raccourci."),
         _criterion("public", "Le public reçoit une consigne simple et complète.", "Indiquer Porte Est, passage couvert et point Jardin, inviter à suivre les agents calmement et à signaler un besoin d'aide. Pas de jargon A2/C2 nécessaire au public ; pas de détail médical personnel."),
         _criterion("suivi", "Je poursuis la coordination après le premier départ.", "Accuser réception de l'appui annoncé sans le dire présent ; confirmer son arrivée et la prise en charge, signaler obstacle ou difficulté nouvelle, suivre la progression et garder D3 libre.")],
        {"pc": "PC de Hall A2, reçu à 17 h 05. Nous utilisons la Porte Est B2, le passage E C2 confirmé libre, puis l'Accueil Jardin D2. La rampe Sud reste indisponible. Appui 2 est attendu à A2 pour l'accompagnement ; je vous confirme son arrivée. L'accès secours D3 reste libre.",
         "public": "Mesdames, messieurs, suivez les agents vers la Porte Est, puis le passage couvert jusqu'au point d'accueil Jardin. Avancez calmement dans ce sens. Si vous avez besoin d'aide pour vous déplacer, signalez-le à l'agent le plus proche ; un accompagnement est organisé.",
         "suivi": "Je suis la progression dans le passage et signale immédiatement un obstacle ou une personne en difficulté. Je vérifie l'arrivée d'Appui 2 et la prise en charge de l'accompagnement, sans la considérer terminée parce qu'elle est annoncée. Je préserve l'accès secours D3 et rends compte de l'arrivée au point Jardin et des suites encore ouvertes."},
        oral_prompt="Dites votre message au public à voix haute. Vérifiez qu'une personne qui n'a jamais vu le plan peut comprendre par où passer et où aller."),
}


# Reading the documents, drafting and reviewing; no automatic extra time credit.
_ESTIMATED_MINUTES = {
    "aps62-01-02": 10,
    "aps62-01-04": 8,
    "aps62-08-02": 8,
    "aps62-08-04": 12,
    "aps62-10-06": 10,
    "aps62-12-05": 10,
    "aps62-13-01": 10,
    "aps62-13-02": 12,
    "aps62-15-02": 10,
    "aps62-15-05": 10,
}
for _section_id, _minutes in _ESTIMATED_MINUTES.items():
    PRODUCTIONS[_section_id]["estimated_minutes"] = _minutes


def get_production(section_id):
    """Return a copy: builders may attach assets without changing source data."""
    return deepcopy(PRODUCTIONS[section_id])


def apply_practical_cases(course):
    """Replace existing transfer activities; preserve activity IDs and durations.

    The runtime owns rendering, draft persistence and feedback confidentiality.
    No course outside these ten target sections is modified by this helper.
    """
    for section in course.get("sections", []):
        if section.get("id") not in PRODUCTIONS:
            continue
        target = section["id"] + "-transfert"
        matches = [a for a in section["activities"] if a.get("id") == target]
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one existing transfer for {section['id']}")
        activity = matches[0]
        activity.pop("practice", None)
        activity["academy"] = {"kind": "transfer"}
        activity["type"] = "content"
        activity["scored"] = False
        activity["blocks"] = []
        activity["title"] = "À vous de produire · " + PRODUCTIONS[section["id"]]["title"]
        activity["production"] = get_production(section["id"])
    return course
