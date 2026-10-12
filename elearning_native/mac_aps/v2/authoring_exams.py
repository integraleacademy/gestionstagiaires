"""Reproduce the reviewed MAC APS v2 pedagogical question banks.

The v1 banks remain immutable. Questions retained from v1 are explicitly selected
and remapped to a principal v2 objective. New cases below cover the remaining
objectives without assessing the practical complements. Objective questionnaires
intentionally revisit selected questions, with separate identifiers.
"""
from __future__ import annotations

import copy
import hashlib
import json
import random
import unicodedata
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VERSION = "20261012-macaps-v2"
SOURCES = {
    "mac": "https://www.legifrance.gouv.fr/loda/id/JORFTEXT000034104578/",
    "foad": "https://www.legifrance.gouv.fr/loda/id/JORFTEXT000051058748/",
    "deonto": "https://www.legifrance.gouv.fr/codes/section_lc/LEGITEXT000025503132/LEGISCTA000029656370/",
    "bagages": "https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000054725427",
    "vehicules": "https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000054718795",
    "defense": "https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000006417218",
    "flagrance": "https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000029000766",
    "ddhc": "https://www.elysee.fr/la-presidence/la-declaration-des-droits-de-l-homme-et-du-citoyen",
    "discrimination": "https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000045391831",
    "laicite": "https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000006340313",
    "constitution": "https://www.legifrance.gouv.fr/loda/id/JORFTEXT000000571356/2026-08-23",
    "cnil": "https://www.cnil.fr/fr/la-videosurveillance-videoprotection-au-travail",
    "vigipirate": "https://www.sgdsn.gouv.fr/vigipirate",
    "plan": "https://www.sgdsn.gouv.fr/files/files/Vigipirate/22062026-VIGIPIRATE-Faire%20Face%20ensemble.pdf",
    "signalement": "https://www.sgdsn.gouv.fr/files/files/Publications/fiche-signalement-situation-suspecte.pdf",
    "radicalisation": "https://www.sgdsn.gouv.fr/files/files/Vigipirate/FICHE-RADICALISATION.pdf",
    "drones": "https://www.sgdsn.gouv.fr/files/files/Vigipirate/FICHE-DRONES.pdf",
    "alerte": "https://www.sgdsn.gouv.fr/files/files/Vigipirate/FICHE-CHAINE-D_ALERTE.pdf",
    "sst": "https://www.inrs.fr/dam/inrs/CataloguePapier/ED/TI-ED-4085-2.pdf",
    "secours": "https://www.inrs.fr/demarche/organisation-secours/accident-malaise.html",
}

# Each line is: source | lesson suffixes | prompt | correct | 3 distractors | feedback.
# Correct option positions are assigned independently for every bank below.
MODULE_ADDITIONS = {
    "menaces": r"""
plan|01|Un agent veut définir le terrorisme uniquement par le nombre de victimes. Quel élément manque à cette définition ?|La finalité d'intimidation ou de terreur liée aux actes prévus par la loi.|La présence obligatoire d'une revendication filmée.|L'obligation que les auteurs viennent de l'étranger.|L'utilisation nécessaire d'une arme à feu.|La qualification juridique ne se déduit pas du seul bilan humain. La finalité et les conditions légales comptent ; l'agent transmet les faits sans se substituer aux autorités compétentes.
""",
    "niveaux": r"""
plan|02,13|Une posture moins élevée est annoncée par les canaux officiels. Peut-on en déduire que les mesures permanentes du site sont supprimées ?|Non ; il faut distinguer les mesures permanentes des mesures additionnelles modifiées.|Oui ; le changement supprime toutes les vérifications jusqu'à la prochaine alerte.|Oui ; chaque agent peut choisir les contrôles qu'il conserve.|Non ; toutes les mesures exceptionnelles doivent rester éternellement identiques.|Une posture adapte le dispositif. Les mesures du socle demeurent, tandis que les mesures additionnelles évoluent selon les instructions applicables.
vigipirate|02,13|Une affiche datée de 2019 est encore visible au poste. Quel support permet de vérifier le stade VIGIPIRATE en octobre 2026 ?|La publication officielle actualisée et les consignes professionnelles qui la déclinent.|L'affiche la plus sévère, quelle que soit sa date.|Le niveau choisi par un site voisin sur son réseau social.|Le souvenir de l'agent le plus ancien.|Les appellations et les postures peuvent évoluer. La vérification porte sur la date, l'émetteur officiel et les instructions applicables à la mission.
""",
    "reflexes": r"""
plan|04|Vous découvrez au briefing un changement important du fonctionnement du site. Quel réflexe entretient une prévention efficace ?|Faire préciser les consignes, les interlocuteurs et les moyens utiles avant la prise de poste.|Conserver toutes les habitudes précédentes jusqu'au premier incident.|Demander seulement si le changement ralentira la relève.|Attendre que le public explique lui-même les nouvelles règles.|La vigilance suppose de comprendre l'organisation réelle. Une information utilisable permet d'identifier une anomalie et de savoir à qui la transmettre.
radicalisation|15|Plusieurs propos inquiétants sont rapportés à propos d'un salarié. Quelle démarche convient à l'agent qui n'en a entendu aucun lui-même ?|Identifier les sources et transmettre les éléments factuels par le circuit prévu en précisant leurs limites.|Présenter les propos comme un constat personnel pour leur donner du poids.|Constituer une liste publique de personnes à surveiller.|Rechercher ses convictions auprès de tous ses voisins.|Le signalement doit distinguer observation directe et information rapportée. Son évaluation appartient aux services compétents ; l'agent ne mène pas une enquête personnelle sur la vie privée.
radicalisation|04,15|Un collègue propose une liste de religions à contrôler davantage « par précaution ». Quelle correction améliore réellement la prévention ?|Rechercher des comportements pertinents, contextualisés, sans faire d'une religion un indicateur de danger.|Ajouter d'autres religions pour rendre la liste plus équilibrée.|Ne conserver que les religions peu présentes sur le site.|Utiliser la liste uniquement lors des journées d'affluence.|Une conviction ne prouve pas une intention violente. La prévention repose sur des faits et des combinaisons de signes préoccupants, analysés sans stéréotype.
""",
    "detection": r"""
signalement|05,16|Une personne photographie la façade ouverte au public. Aucun autre fait anormal n'est observé. Que peut-on conclure à ce stade ?|Ce seul fait ne permet pas d'affirmer un repérage hostile ; il faut considérer le contexte et les règles applicables.|Toute photographie extérieure prouve une préparation d'attentat.|L'agent peut exiger la suppression de toutes les images sans autre fondement.|L'absence d'infraction apparente interdit de noter toute observation ultérieure.|Un comportement peut avoir une explication ordinaire. La vigilance exige des faits contextualisés, sans transformer un signe isolé en accusation ni inventer un pouvoir de contrôle.
signalement|16|Dans un signalement, « individu suspect » est la seule description. Quel complément le rend exploitable ?|Les actions observées, le lieu, l'heure, la source et les éléments restant incertains.|Une appréciation sur les opinions supposées de la personne.|Le nombre de collègues partageant le même ressenti sans faits nouveaux.|Une qualification pénale choisie pour rendre le message plus urgent.|Un qualificatif ne permet pas de vérifier une situation. Les repères concrets permettent au destinataire d'apprécier le risque et de décider de la suite.
""",
    "culture": r"""
plan|06|Après une sensibilisation, les agents connaissent les numéros mais ignorent le responsable qui actualise les consignes. Quelle amélioration est nécessaire ?|Désigner le circuit de mise à jour et vérifier que les nouvelles consignes atteignent les équipes.|Ajouter uniquement une affiche supplémentaire sur le mur.|Considérer que la mémorisation des numéros suffit pour l'année.|Laisser chaque vacation fabriquer sa propre version des consignes.|Une culture de sécurité se maintient par une organisation vivante : responsabilités connues, information actualisée et vérification de la compréhension.
""",
    "blessures": r"""
mac|09|Une explosion a projeté une personne contre un mobilier. Elle présente peu de marques visibles. Quel élément doit figurer dans l'analyse du risque de blessure ?|Le mécanisme de projection et le choc, même si l'examen visuel paraît rassurant.|Seulement la présence d'un saignement sur les vêtements.|Uniquement le fait que la personne soit encore debout.|Le prix du mobilier endommagé.|Une attaque peut provoquer des lésions par souffle, fragments, chute ou choc. L'absence de marque importante ne permet pas d'écarter une atteinte interne ; le mécanisme et les signes sont transmis aux secours.
sst|09|Après un événement violent, une personne tremble, parle vite et se plaint d'une douleur. Quel raisonnement évite de minimiser son état ?|Décrire la douleur et les autres signes sans attribuer d'emblée tous les symptômes au stress.|Conclure à une peur passagère puisqu'elle peut parler.|Écarter une blessure si les vêtements sont intacts.|Lui demander de prouver d'abord qu'elle a été touchée.|Une détresse émotionnelle peut coexister avec une blessure ou un malaise. L'observation et l'avis médical priment sur une explication improvisée.
""",
    "secours": r"""
secours|10|Depuis une zone sûre, vous appelez pour plusieurs blessés après une attaque. Quelle information vient compléter leur nombre ?|Le lieu précis, les dangers connus, les signes observés et les moyens de contact utiles.|La liste complète des objets perdus par les témoins.|Votre hypothèse sur les motivations de l'auteur.|Le nombre de personnes inscrites à l'événement, sans préciser les blessés.|L'alerte médicale doit permettre de localiser et d'évaluer la situation. Un bilan factuel facilite l'engagement des secours ; les informations inconnues sont annoncées comme telles.
sst|10|Pendant votre appel, un collègue constate qu'une victime jusque-là parlante répond de moins en moins. Quelle information transmettez-vous ?|L'évolution de la réponse de cette victime et le moment où elle a été constatée.|La première observation seulement, pour ne pas compliquer le bilan.|L'affirmation qu'elle dort, puisqu'elle était consciente peu avant.|Aucune information avant d'avoir identifié sa pathologie.|Le bilan se met à jour lorsque l'état change. Décrire une aggravation permet à l'opérateur d'adapter ses consignes sans attendre un diagnostic de l'agent.
""",
}

FINAL_ADDITIONS = {
    "republique": r"""
laicite|02|Une affiche interne affirme que « la laïcité interdit toute conviction visible à toute personne ». Quel examen doit précéder son application ?|Identifier le statut de la personne, la mission et la règle juridique réellement applicable.|Vérifier seulement que le mot laïcité figure en gros caractères.|Appliquer l'affiche à tous puis rechercher le texte en fin de journée.|Demander quelle conviction est majoritaire parmi les salariés.|La liberté de conscience et les obligations de neutralité s'apprécient dans leur cadre précis. Un mot sur une affiche ne crée pas une interdiction générale applicable à tous les usagers et salariés.
discrimination|04|Une visiteuse autorisée ne peut pas utiliser le dispositif ordinaire pour une raison de handicap. Quelle réponse évite une exclusion purement matérielle ?|Solliciter la modalité accessible prévue ou un relais permettant un contrôle équivalent.|Exiger qu'elle renonce à son rendez-vous pour simplifier le travail du poste.|La faire entrer sans aucun contrôle et sans prévenir personne.|Lui demander de justifier publiquement son dossier médical.|L'égalité suppose d'examiner les obstacles concrets et les solutions adaptées. La vérification utile peut être conservée sans exposer des informations médicales inutiles.
ddhc|06|Un responsable estime qu'une consigne est légitime parce qu'elle a été approuvée à l'unanimité de l'équipe. Quel contrôle reste indispensable ?|Vérifier sa compatibilité avec le droit et les limites de la mission.|Vérifier uniquement que tous les agents l'ont signée.|L'appliquer sans réserve puisque l'équipe connaît le terrain.|La publier sur le site pour lui donner automatiquement force de loi.|L'accord d'une équipe ne transforme pas une règle privée en loi. Une restriction doit reposer sur un cadre valable, même lorsqu'elle semble pratique ou consensuelle.
ddhc|03|À propos d'un incident, un agent veut annoncer publiquement une peine à la personne mise en cause. Quel principe doit être rappelé ?|La sécurité privée n'exerce pas le pouvoir de juger et de prononcer une sanction pénale.|L'agent peut prononcer une peine si elle est inférieure à celle de la loi.|Le client peut déléguer librement le pouvoir de condamner.|La peine devient possible lorsque plusieurs témoins approuvent.|L'État de droit répartit les compétences et soumet les sanctions au cadre légal. L'agent rapporte les faits et utilise les relais compétents ; il ne se substitue pas à la justice.
ddhc|05|Des collègues veulent diffuser la photographie d'une personne simplement soupçonnée, avec la mention « coupable ». Quelle correction est nécessaire ?|Préserver la présomption d'innocence et réserver les éléments utiles aux destinataires autorisés.|Diffuser la photographie sans prénom pour pouvoir maintenir la mention.|Demander l'avis majoritaire du groupe de discussion.|Attendre une heure avant la diffusion pour rendre l'accusation prudente.|Un soupçon n'est pas une déclaration de culpabilité. Les preuves utiles suivent le circuit professionnel et légal ; une diffusion accusatoire n'est pas un compte rendu.
discrimination|04|Un contrôle semble plus sévère pour les femmes depuis plusieurs semaines. Quel examen est pertinent lors du bilan du poste ?|Comparer des situations équivalentes, les critères appliqués et les décisions effectivement prises.|Conclure qu'il n'y a aucun problème si personne n'a déposé plainte.|Conserver la pratique si elle réduit légèrement l'attente ailleurs.|Demander seulement aux agents s'ils se considèrent impartiaux.|L'analyse d'une différence de traitement porte sur les faits et les critères, y compris leurs effets dans le temps. Une intention déclarée ne remplace pas cette vérification.
ddhc|01,06|Une personne exprime une opinion politique opposée à la vôtre, tout en respectant les conditions d'accès. Quel critère doit guider la décision ?|Son autorisation et son comportement au regard des règles applicables.|La proximité de ses opinions avec celles du client.|L'impression que son opinion pourrait déplaire à d'autres visiteurs.|L'accord préalable des agents avec son discours.|La liberté d'opinion impose de distinguer les convictions des comportements relevant de la sécurité. L'impartialité s'apprécie dans l'application des règles légitimes.
constitution|01,05|Un exercice révèle qu'un agent aide seulement les personnes qu'il connaît, alors que plusieurs autres peuvent être assistées sans risque. Quel progrès est attendu ?|Organiser l'aide selon les besoins et les possibilités sûres, sans préférence personnelle.|Conserver cette priorité pour ne pas fragiliser les relations de confiance.|Donner toujours priorité à la personne qui parle le plus fort.|Refuser toute aide pour traiter tout le monde à l'identique.|La fraternité et l'égalité orientent une solidarité concrète. Une organisation professionnelle tient compte des besoins et des possibilités d'assistance, sans favoritisme.
ddhc|06|Une restriction d'accès temporaire est levée par le responsable compétent. Un agent veut la maintenir pour punir des réclamations antérieures. Quel défaut identifiez-vous ?|La mesure perd sa justification de sécurité et devient une sanction personnelle.|La règle doit rester dès lors qu'elle a été annoncée une première fois.|L'ancienneté de l'agent suffit pour prolonger toute restriction.|Une réclamation prive automatiquement du droit de demander un accès.|Une restriction doit rester rattachée à son objet et à son cadre. Le pouvoir confié pour la sécurité ne peut pas servir à régler un différend personnel.
ddhc|03,06|Un chef présente l'État de droit comme une obligation qui concerne seulement le public. Quelle formulation corrige cette idée ?|Les autorités et les professionnels agissent eux aussi dans les limites fixées par le droit.|Les professionnels sont dispensés de la loi lorsqu'ils poursuivent un objectif utile.|Seuls les agents débutants doivent vérifier leurs pouvoirs.|Le contrat privé remplace les règles légales à l'intérieur du site.|L'État de droit encadre l'exercice du pouvoir. La finalité de sécurité ne crée pas une exemption pour l'entreprise, le responsable ou l'agent.
""",
    "cadre-juridique": r"""
bagages|08|Une personne a accepté hier une fouille de sac sur le même site. Peut-on présumer son consentement aujourd'hui ?|Non ; il faut établir le consentement applicable au contrôle proposé aujourd'hui.|Oui ; le consentement vaut pour toute la durée de validité du badge.|Oui ; seule une lettre écrite peut mettre fin au premier accord.|Oui ; le fait de revenir sur le site renouvelle automatiquement l'accord.|Le contrôle actuel doit respecter ses propres conditions. Un accord antérieur ne permet pas d'écarter un refus exprimé lors d'une nouvelle fouille.
bagages|08|Une palpation est légalement envisageable, mais le visiteur ne répond que par le silence. Quel élément manque ?|Un consentement exprès clairement établi avant la palpation.|L'autorisation du visiteur placé derrière lui dans la file.|Une mention générale de consentement dans la main courante.|Une deuxième demande formulée plus fermement, qui vaudrait accord.|Le silence n'établit pas le consentement exprès requis. L'organisation traite le refus ou l'absence d'accord dans le cadre applicable, sans transformer le contrôle en contrainte.
vehicules|08|À l'entrée d'un lieu couvert par L613-2-1, un conducteur refuse l'inspection visuelle. L'agent peut-il en conclure que toute entrée à pied lui est interdite ?|Non ; le refus d'accès avec le véhicule ne supprime pas par principe la possibilité d'un accès sans véhicule.|Oui ; le refus rend automatiquement le conducteur indésirable pour la journée.|Oui ; l'interdiction s'étend obligatoirement à tous ses passagers.|Non ; l'agent doit alors laisser entrer le véhicule sans contrôle.|Le texte prévoit le refus d'accès du véhicule tout en réservant la possibilité d'entrer sans lui. L'accès piéton reste soumis à ses propres conditions légales.
vehicules|08|Un gestionnaire souhaite inspecter un fourgon aménagé pour l'habitation dans le cadre de L613-2-1. Quelle réserve devez-vous formuler ?|Cette catégorie est exclue de l'inspection visuelle prévue par cet article.|L'inspection devient possible si elle dure moins d'une minute.|Le véhicule peut être démonté si le conducteur signe une décharge.|L'absence de personne à l'intérieur suffit à supprimer l'exclusion.|Le champ de L613-2-1 exclut les véhicules spécialement aménagés à usage d'habitation. L'agent ne transforme pas l'accord du gestionnaire en extension de compétence.
deonto|07|Un accessoire de tenue ressemble à un insigne de police et le client le trouve rassurant. Quel critère doit guider sa validation ?|L'identification claire de l'activité privée et l'absence de confusion avec une autorité publique.|L'effet d'autorité ressenti par les visiteurs.|L'absence de réclamation pendant la première semaine.|Le coût déjà engagé pour acheter les accessoires.|L'apparence professionnelle doit rester compatible avec la déontologie. Un avantage commercial ou une impression d'autorité ne justifie pas la confusion avec les services publics.
cnil|02,06|Un agent exporte des images du site sur son téléphone pour les revoir chez lui, sans procédure ni habilitation correspondante. Quel problème apparaît ?|La sortie des images du cadre autorisé de finalité, d'accès et de sécurité des données.|Le seul risque que le fichier soit trop lourd pour son téléphone.|Aucun problème si l'agent promet de ne rien publier.|Aucun problème dès lors que les personnes sont salariées du site.|L'accès professionnel aux images ne vaut pas autorisation de copie personnelle. Les destinataires, les usages et les supports doivent rester dans le cadre prévu.
flagrance|04|Un client vous demande d'enfermer une personne « le temps de vérifier », en invoquant une ancienne rumeur de vol. Quelle limite est décisive ?|La privation de liberté ne peut pas être fondée sur une simple rumeur ; les conditions légales doivent être établies.|Une durée inférieure à dix minutes rend toute rétention licite.|Le client peut créer une retenue contractuelle dans son règlement.|La présence d'une caméra remplace les conditions de l'article 73.|L'article 73 ne crée pas une faculté générale de retenir pour enquêter. La réalité des faits et les conditions de flagrance doivent être appréciées, avec les relais compétents.
deonto|05|Deux comptes rendus diffèrent sur un détail que les agents n'ont pas vu depuis le même endroit. Quelle correction est professionnelle ?|Conserver les observations propres à chacun et préciser l'incertitude, sans fabriquer une version commune.|Faire recopier exactement la version de l'agent le plus ancien.|Supprimer toutes les mentions du détail divergent.|Ajouter un témoin fictif pour stabiliser le récit.|Une trace sincère distingue les sources et les limites d'observation. La recherche de cohérence ne doit pas créer des faits ni effacer des divergences utiles à l'analyse.
foad|08|Un client demande si les 14 heures numériques terminées constituent à elles seules une attestation réglementaire MAC APS en octobre 2026. Quelle réponse est exacte ?|Elles décrivent un suivi pédagogique ; il faut un cadre réglementaire en vigueur et le stage requis pour conclure à une réalisation réglementaire.|Oui ; toute plateforme qui compte 14 heures peut délivrer l'attestation de stage.|Oui ; le paiement du parcours suffit à prolonger la dérogation de 2025.|Oui ; un seuil de 80 % transforme automatiquement le résultat en certification SST.|Le dispositif de janvier 2025 visait une période close au 31 décembre 2025. Le volume et les scores de ce support n'inventent pas une prorogation ni une validation des parties pratiques.
mac|01,08|Une personne dispensée du secourisme général demande de supprimer aussi les apprentissages sur les blessés en contexte d'attaque. Quel point faut-il rappeler ?|La dispense générale de secourisme ne supprime pas automatiquement les objectifs distincts de la séquence terrorisme.|La dispense SST supprime la totalité du module terrorisme.|La carte professionnelle seule dispense de tous les gestes pratiques.|Une bonne note au bilan en ligne permet à l'agent de décider seul de ses dispenses.|Les dispenses doivent être justifiées dans leur périmètre exact. L'alerte médicale et le secours tactique du module terrorisme restent distincts du module général de secours.
""",
    "menaces": r"""
plan|01,11|Un briefing réduit toute menace terroriste à une seule origine idéologique. Quel élargissement est nécessaire ?|Prendre en compte les diverses inspirations violentes décrites par les sources officielles, sans associer une population à une menace.|Remplacer cette origine par celle qui inquiète le plus l'équipe.|Classer toutes les opinions contestataires comme terroristes.|Considérer seulement les actes commis hors de France.|Le terrorisme a des histoires et des inspirations variées. Une prévention utile examine les faits et la violence projetée ; elle ne crée pas un profil démographique de danger.
plan|11|Pourquoi étudier les enseignements d'attentats passés dans une formation de prévention ?|Pour comprendre leurs effets sur les personnes et l'organisation, puis améliorer la préparation défensive.|Pour reproduire précisément les modes opératoires offensifs.|Pour fixer définitivement la forme du prochain événement.|Pour conclure qu'un autre type de site ne peut pas être touché.|L'étude historique éclaire les conséquences et les besoins de coordination. Elle ne prédit pas à elle seule une menace actuelle et ne doit pas devenir un enseignement de passage à l'acte.
plan|01|Un collègue confond toute dégradation avec un acte terroriste. Quelle distinction convient ?|Une qualification terroriste exige les conditions et la finalité prévues par le droit, au-delà de la seule dégradation.|Une dégradation devient terroriste dès qu'elle choque un témoin.|La présence d'un agent en uniforme suffit à caractériser le terrorisme.|Le propriétaire du bien décide seul de la qualification pénale.|Un même dommage matériel peut relever de qualifications différentes selon les faits. L'agent décrit l'événement et transmet ; l'autorité compétente apprécie sa qualification.
plan|12|Une panne informatique survient le jour où une rumeur de menace circule. Que permet ce rapprochement à lui seul ?|De signaler les deux faits et de demander une analyse, sans affirmer un lien de causalité.|D'affirmer une cyberattaque terroriste coordonnée.|De rétablir le système en supprimant toutes les protections sans autorisation.|D'écarter la panne parce qu'elle relève seulement de l'informatique.|La concomitance n'est pas une preuve de cause commune. Une anomalie numérique peut affecter la sûreté et mérite un traitement coordonné, sans qualification inventée.
plan|01,12|La prévention du site repose sur l'idée qu'un auteur serait toujours une personne extérieure inconnue. Quel angle mort identifiez-vous ?|L'absence de prise en compte d'un risque provenant aussi d'une personne ayant un accès légitime.|Le fait de ne pas contrôler systématiquement tous les salariés comme des suspects.|L'absence d'une liste des convictions personnelles du personnel.|Le refus d'interdire tout accès aux prestataires déjà connus.|Un accès habituel n'annule pas tout risque. L'analyse reste fondée sur les faits, les autorisations et les anomalies, avec le même respect des droits pour tous.
plan|11|Un responsable pense qu'un attentat ne produit que des blessures au lieu exact des faits. Quel effet doit aussi être anticipé dans l'organisation ?|Des conséquences humaines, des perturbations et des besoins d'information pouvant toucher plus largement le site.|La disparition automatique de tout autre risque de sécurité.|Le droit pour l'entreprise de suspendre toutes ses obligations.|L'impossibilité de préparer une continuité avant l'événement.|Les effets d'un événement violent peuvent se prolonger au-delà de son point initial. La préparation porte sur la continuité, l'information fiable et les besoins des personnes sans dramatiser ni inventer de certitudes.
plan|01,11|Un établissement n'a jamais connu d'attaque. Quelle valeur ce constat a-t-il pour l'analyse de risque ?|C'est un élément d'historique, qui ne dispense pas d'examiner les menaces et les vulnérabilités actuelles.|Il prouve que le site est durablement hors de danger.|Il permet de supprimer toute veille officielle.|Il oblige à appliquer le niveau maximal en permanence.|L'absence d'antécédent ne garantit pas l'absence de risque. La prévention associe l'actualité de la menace aux caractéristiques et à l'organisation présentes du site.
""",
    "niveaux": r"""
plan|13|Le chef de poste souhaite annoncer qu'il a lui-même fait passer la France en « alerte attentat ». Quel point devez-vous corriger ?|Le niveau national relève des autorités compétentes ; le poste applique les consignes reçues pour le site.|Tout titulaire d'une carte professionnelle peut changer le niveau national.|Le niveau dépend uniquement du nombre de visiteurs du site.|Le niveau est choisi par le fabricant du dispositif d'accès.|Le niveau VIGIPIRATE et sa posture sont décidés et diffusés par la chaîne publique prévue. Les responsables locaux mettent en œuvre les mesures qui leur sont applicables.
plan|02,13|Deux établissements reçoivent le même niveau VIGIPIRATE mais présentent des activités et des accès différents. Faut-il nécessairement leur appliquer des consignes identiques en tous points ?|Non ; la déclinaison doit tenir compte des mesures applicables et des vulnérabilités de chacun.|Oui ; le niveau national impose un plan de site unique dans toute la France.|Non ; chaque agent peut supprimer seul les mesures gênantes.|Oui ; toute adaptation locale annule automatiquement le plan national.|Le niveau est un repère commun ; les mesures se déclinent selon les secteurs, les situations et les instructions. L'adaptation ne donne pas une liberté de déroger aux obligations applicables.
vigipirate|13|En octobre 2026, quelle précaution accompagne une consigne citant la durée du stade sommital « alerte attentat » ?|Vérifier son activation et son éventuel renouvellement dans la décision officielle, sans la prolonger par habitude.|Considérer qu'il reste actif jusqu'à la prochaine année civile.|Décider de sa fin d'après le calme observé au poste.|Confondre sa durée avec celle d'une carte professionnelle.|Le SGDSN présente en 2026 une activation de douze jours renouvelable sur décision expresse du Premier ministre. La vérification de la décision applicable évite une prolongation ou une levée inventée localement.
plan|02|Une annonce médiatique mentionne un risque accru, mais aucune consigne nouvelle n'a encore été confirmée au poste. Quelle démarche est appropriée ?|Vérifier rapidement les canaux officiels et professionnels tout en maintenant les mesures applicables et la vigilance.|Suspendre tous les contrôles en attendant le prochain briefing.|Transformer immédiatement chaque visiteur en suspect.|Remplacer les consignes par les commentaires du journaliste.|Une information médiatique peut appeler une vérification rapide. Les mesures se fondent sur les instructions compétentes ; la vigilance et le traitement d'un danger concret ne sont pas suspendus pendant cette vérification.
plan|13|Un agent confond le plan VIGIPIRATE avec l'instauration automatique d'un régime juridique d'exception. Quelle distinction est nécessaire ?|Le plan organise la vigilance et la protection ; les pouvoirs particuliers exigent leur propre fondement légal.|Tout stade VIGIPIRATE autorise automatiquement toutes les restrictions possibles.|Le plan supprime les conditions des contrôles privés dès qu'une affiche est visible.|Un régime d'exception peut être créé par le règlement intérieur d'un site.|Un dispositif de planification ne remplace pas les textes fixant les pouvoirs et les restrictions. L'agent vérifie le cadre de chaque mesure et ses conditions d'application.
""",
    "materiels": r"""
plan|03,14|Un objet suspect ressemble à un article courant et ne comporte aucun élément technique visible. Que vaut cette apparence pour l'agent ?|Elle ne permet pas de certifier l'absence de danger ; l'agent garde la distance et le cadre d'alerte prévus.|Elle prouve qu'il peut être ouvert sans risque.|Elle autorise une manipulation si l'objet est léger.|Elle rend inutile toute prise en compte du contexte.|La reconnaissance sert à repérer une situation et à la décrire. L'agent ne devient pas expert du contenu d'un objet à partir de sa seule apparence.
plan|14|Un véhicule habituellement utilitaire apparaît dans l'analyse des moyens pouvant être détournés pour une attaque. Quel apprentissage est attendu de l'APS ?|Comprendre qu'un objet d'usage courant peut devenir un danger selon les faits, sans suspecter automatiquement tous ses utilisateurs.|Apprendre à modifier le véhicule pour reproduire son emploi offensif.|Considérer tout conducteur de ce modèle comme un auteur probable.|Déduire la dangerosité uniquement du pays de l'immatriculation.|La formation explique les familles de dangers et leurs conséquences pour la prévention. Le contexte et les comportements comptent ; l'objet seul ne désigne pas une intention criminelle.
plan|03,14|Un collègue affirme qu'une substance dangereuse serait toujours reconnaissable à son odeur. Quelle réserve est correcte ?|L'odeur ou son absence ne permet pas d'identifier sûrement une substance ni d'écarter un risque.|Une odeur forte permet toujours d'évaluer la concentration sans matériel.|L'absence d'odeur autorise systématiquement le retour dans la zone.|Un agent peut sentir de près un contenant pour confirmer son contenu.|La reconnaissance non spécialisée a des limites. Les faits observés se transmettent aux services compétents ; on ne recherche pas une confirmation par une exposition supplémentaire.
plan|14|Une image lointaine montre un objet ressemblant à une arme. Quel niveau de description est approprié dans la prévention ?|Décrire l'objet et les faits visibles en signalant que sa nature exacte n'est pas confirmée.|Nommer un modèle précis pour donner plus de crédibilité au signalement.|Conclure à un jouet parce qu'aucun tir n'a été entendu.|Chercher à le manipuler avant tout signalement.|La description doit refléter le degré réel de certitude. Une ressemblance justifie la prudence et le relais adapté, sans expertise technique improvisée.
""",
    "reflexes": r"""
radicalisation|15|Un employé tient des propos légitimant explicitement une violence contre des personnes. Quel traitement évite à la fois la banalisation et l'accusation improvisée ?|Rapporter les propos utiles et leur contexte par le circuit adapté, en traitant sans délai tout danger immédiat.|Classer automatiquement le propos comme une plaisanterie parce que l'employé est ancien.|Diffuser son identité à tous les clients avant toute évaluation.|Chercher soi-même une preuve en consultant ses comptes privés.|Des propos favorables à la violence peuvent constituer des éléments préoccupants. Le signalement reste factuel et confidentiel, et l'urgence se traite par les services compétents.
radicalisation|04,15|Deux agents disposent d'une rumeur sur une radicalisation mais d'aucun fait vérifié. Quelle attitude leur permet de progresser utilement ?|Distinguer la rumeur des faits disponibles et demander le relais prévu pour apprécier les éléments.|Fabriquer une observation commune afin que le signalement soit pris au sérieux.|Conserver une liste secrète de croyants du quartier.|Faire pression sur la personne pour qu'elle explique ses convictions.|Le rôle professionnel ne consiste pas à attribuer une dangerosité sur une rumeur. Les sources et les limites du renseignement doivent rester visibles dans le circuit compétent.
plan|04|Une longue période sans incident a conduit l'équipe à ignorer certaines anomalies de fermeture. Quel réflexe faut-il rétablir ?|Vérifier les écarts, les signaler et suivre leur traitement selon les responsabilités prévues.|Attendre plusieurs incidents identiques avant de parler au responsable.|Ouvrir davantage d'accès pour faciliter le travail de la relève.|Considérer que l'ancienneté de l'habitude rend l'écart acceptable.|La routine peut diminuer l'attention. Une anomalie connue doit être traitée et suivie ; son ancienneté n'est pas une garantie de sûreté.
deonto|04,15|Un tiers demande par messagerie personnelle le dossier d'un signalement sensible en disant « vouloir aider ». Quel réflexe préserve la prévention ?|Vérifier son habilitation et utiliser le circuit autorisé, en limitant les informations au besoin réel.|Transmettre tout le dossier pour montrer la coopération de l'équipe.|Supprimer les noms puis publier tous les autres détails dans un groupe ouvert.|Répondre avec une copie des documents sur un téléphone personnel.|La confidentialité protège les personnes et la qualité du traitement. Une intention déclarée ne suffit pas à autoriser la diffusion d'informations sensibles.
radicalisation|15|Un signalement de radicalisation est en cours d'examen lorsqu'une menace immédiate contre une personne est constatée. Quelle priorité doit être comprise ?|Le danger immédiat appelle l'alerte urgente adaptée, sans attendre la fin de l'examen administratif du signalement.|Il faut attendre le retour du service chargé du signalement avant toute autre action.|Le signalement initial remplace automatiquement tous les appels d'urgence.|L'agent doit d'abord obtenir une qualification terroriste définitive.|Le traitement d'un signalement et la réponse à un danger immédiat ont des temporalités distinctes. La protection et l'alerte urgente ne dépendent pas d'une qualification préalable par l'agent.
plan|04|Un agent se sent moins attentif pendant une vacation et constate qu'il oublie des vérifications prévues. Quelle décision soutient la prévention ?|Signaler la difficulté et utiliser le relais ou l'organisation prévue pour maintenir la vigilance.|Masquer les oublis pour préserver son image professionnelle.|Supprimer discrètement les contrôles les moins visibles du client.|Compter seulement sur l'absence récente d'incident.|La prévention dépend aussi des facteurs humains et de l'organisation. Un relais approprié traite un risque concret ; la dissimulation laisse les mêmes défaillances se répéter.
""",
    "detection": r"""
signalement|05,16|Un rapport mélange une observation directe et deux messages reçus par téléphone. Quelle présentation facilite l'analyse ?|Séparer les faits vus de chaque information rapportée, avec l'heure et la source disponibles.|Regrouper toutes les informations comme si l'agent les avait constatées.|Écarter systématiquement tout témoignage indirect même précis.|Choisir la version la plus inquiétante et supprimer les autres.|Les sources n'ont pas toutes la même portée. Une transmission structurée rend les vérifications possibles et évite de transformer une accumulation de messages en certitude artificielle.
signalement|16|Vous avez signalé un comportement inhabituel puis apprenez une explication professionnelle vérifiée qui l'éclaire. Quelle suite donnez-vous ?|Transmettre aussi cet élément nouveau au destinataire du signalement, sans effacer la trace initiale.|Conserver l'accusation initiale parce qu'elle a déjà été envoyée.|Supprimer discrètement le rapport sans informer personne.|Refuser l'explication parce qu'elle rend le premier doute moins important.|Un signalement est une information à évaluer. Sa mise à jour, y compris lorsqu'elle réduit un doute, préserve l'exactitude de l'analyse et la traçabilité des décisions.
signalement|05|Un prestataire sollicite à répétition des informations sensibles qui ne sont pas nécessaires à son intervention. Quelle réponse reste dans le rôle de l'agent ?|Limiter la transmission aux informations autorisées et signaler les demandes précises au responsable.|Inventer de faux codes pour tester discrètement ses intentions.|Lui remettre tout le dossier afin d'éviter un conflit.|Le déclarer publiquement auteur d'un projet terroriste.|La prévention combine la protection de l'information et le signalement factuel. Le caractère inhabituel d'une demande ne crée pas un pouvoir d'enquête ou de sanction privée.
""",
    "culture": r"""
plan|06|Un débriefing identifie un défaut de compréhension, mais aucune action n'est attribuée. Que manque-t-il pour que le retour d'expérience soit utile ?|Une amélioration concrète avec un responsable, une échéance adaptée et une vérification de son efficacité.|Une liste plus longue des erreurs personnelles des participants.|Une conclusion indiquant simplement que tout le monde fera attention.|La suppression du compte rendu dès que les participants l'ont lu.|Un retour d'expérience doit produire une évolution vérifiable. L'attribution et le suivi évitent que le même constat réapparaisse sans traitement.
plan|06|Un nouveau remplaçant connaît le risque terroriste en général, mais pas les consignes locales. Quelle action complète utilement ses connaissances ?|Un accueil au poste portant sur les consignes et contacts du site, avec vérification de leur compréhension.|Le laisser interpréter seul le plan du bâtiment après l'ouverture.|Considérer qu'une ancienne formation remplace tout briefing local.|Lui demander seulement de signer une feuille sans explication.|Une culture de sécurité associe les connaissances générales à l'organisation réellement en place. L'intégration au poste et la compréhension des consignes sont des étapes distinctes.
""",
    "blessures": r"""
mac|09|Après une explosion, un témoin explique qu'il a été frappé par des fragments mais ne saigne presque pas. Quelle donnée doit rester dans le bilan ?|La projection de fragments, les zones concernées et les symptômes décrits, sans conclure à une blessure légère.|Seulement l'absence de sang visible.|L'affirmation qu'aucune lésion n'est possible si les vêtements sont peu abîmés.|Une estimation de la profondeur des blessures sans examen compétent.|Le mécanisme lésionnel renseigne les secours. L'importance d'une atteinte ne se déduit pas uniquement du saignement extérieur et l'agent n'improvise pas de diagnostic.
sst|09|Une personne exposée à une forte détonation signale une douleur à l'oreille et une gêne persistante. Quel traitement de l'information est correct ?|Relater ces symptômes et le contexte aux secours pour avis, sans les banaliser.|Conclure à un bruit ordinaire si elle répond aux questions.|Lui demander de subir un nouveau bruit pour tester son audition.|Attendre obligatoirement le lendemain avant de noter la plainte.|Un signe après un événement violent doit être décrit avec son contexte. L'agent recueille les informations utiles et sollicite l'avis approprié au lieu d'effectuer un test improvisé.
sst|09|Vous trouvez une victime après un choc en contexte d'attaque. Elle ne répond pas à une question simple. Quel constat est utile avant toute conclusion ?|Sa réponse ou absence de réponse et sa respiration observée, transmises sans diagnostic improvisé.|La certitude qu'elle simule parce qu'aucune plaie n'est visible.|Une cause psychologique déduite de l'agitation des témoins.|Un pronostic établi seulement à partir de son âge.|L'identification des signes vitaux oriente l'alerte et les consignes des secours. L'absence de réponse est un fait à traiter ; elle ne permet pas à l'agent de conclure seul à sa cause.
""",
    "secours": r"""
secours|10|L'adresse du site comporte plusieurs entrées et le lieu des blessés se trouve loin du portail principal. Quelle précision améliore l'appel médical ?|Le bâtiment, l'étage ou les repères connus et l'accès utilisable selon les informations sûres disponibles.|Seulement le nom commercial du groupe propriétaire.|L'entrée la plus proche même si elle est connue comme dangereuse.|Une direction supposée pour éviter de dire que certains détails manquent.|La localisation doit aider les secours à atteindre la situation sans être trompés sur l'accès. L'agent indique les repères fiables, les dangers connus et ses incertitudes.
sst|10|Vous avez vu deux blessés ; un témoin en annonce trois autres dans une zone non vérifiée. Comment formulez-vous ce nombre aux secours ?|Deux blessés observés et trois autres rapportés par un témoin, restant à confirmer.|Cinq blessés confirmés par l'agent.|Deux blessés seulement, sans mentionner le témoignage.|Un nombre volontairement majoré pour obtenir plus de moyens.|Le bilan distingue le constat direct de l'information rapportée. Les secours peuvent ainsi tenir compte du besoin possible tout en connaissant le niveau de certitude.
secours|10|L'opérateur médical vous pose des questions alors que vous pensez avoir donné toutes les informations. Quelle conduite favorise une alerte efficace ?|Rester disponible, répondre précisément et suivre ses instructions jusqu'à la fin de l'échange.|Raccrocher pour montrer que l'appel est terminé.|Remplacer ses questions par votre analyse des motivations de l'auteur.|Transmettre le téléphone à un témoin sans expliquer ce qui a déjà été dit.|L'opérateur peut avoir besoin de préciser le bilan et de guider l'assistance. L'agent décrit ce qu'il sait, annonce ce qu'il ignore et suit le déroulement de l'appel.
sst|10|Une information médicale vous a été donnée par la victime avant l'appel. Comment l'intégrer au bilan ?|La transmettre comme une déclaration de la victime, si elle est utile, sans la transformer en diagnostic personnel.|La présenter comme un diagnostic confirmé par l'agent.|La diffuser au groupe général de messagerie du site.|La remplacer par l'hypothèse du témoin le plus affirmatif.|Les propos de la victime peuvent aider les secours. Leur source doit rester claire et leur diffusion limitée au besoin de prise en charge.
secours|10|Un collègue a déjà appelé les secours, mais vous constatez ensuite un changement majeur du nombre ou de l'état des victimes. Que doit prévoir l'équipe ?|Une mise à jour coordonnée de l'alerte avec les nouveaux faits fiables.|L'absence de nouvel échange puisqu'un appel a déjà été passé.|Plusieurs appels contradictoires sans préciser le premier bilan.|La modification silencieuse de la main courante sans prévenir les secours.|Un appel initial ne fige pas la situation. La coordination et les mises à jour factuelles évitent de laisser les services agir sur un bilan devenu incomplet.
""",
}


def normalized(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def objective_key(short):
    return "macaps-" + short if short in ("republique", "cadre-juridique") else "macaps-terrorisme-" + short


def remap_legal_refs(question):
    refs = []
    for ref in question.get("lesson_refs", []):
        if ref.startswith("macaps-04-"):
            ref = "macaps-03-08"
        elif ref.startswith("macaps-01-"):
            ref = "macaps-03-04"
        if ref.startswith("macaps-03-") and ref not in refs:
            refs.append(ref)
    return refs or ["macaps-03-08"]


def retained(question, short, refs=None, source=None):
    row = copy.deepcopy(question)
    row["origin_question_id"] = row.pop("id")
    row["objective_id"] = objective_key(short)
    if refs is not None:
        row["lesson_refs"] = ["macaps-" + row["module"] + "-" + ref for ref in refs.split(",")]
    elif row["module"] == "03":
        row["lesson_refs"] = remap_legal_refs(row)
    else:
        row["lesson_refs"] = [r for r in row.get("lesson_refs", []) if r.startswith("macaps-" + row["module"] + "-")]
    original_source = row["source_url"]
    if source:
        row["source_url"] = SOURCES[source]
    row["sources"] = list(dict.fromkeys([row["source_url"], original_source]))
    return row


def additions(blocks):
    rows = []
    for short, block in blocks.items():
        module = "02" if short == "republique" else "03" if short == "cadre-juridique" else "05"
        for raw in block.strip().splitlines():
            fields = raw.split("|")
            assert len(fields) == 8, (short, len(fields), raw)
            source, refs, prompt, correct, wrong1, wrong2, wrong3, explanation = fields
            rows.append({"module": module, "objective_id": objective_key(short),
                "prompt": prompt, "options": [{"id": chr(97+i), "text": text} for i, text in enumerate([correct, wrong1, wrong2, wrong3])],
                "answer": "a", "explanation": explanation, "source_url": SOURCES[source],
                "sources": [SOURCES[source]],
                "lesson_refs": ["macaps-" + module + "-" + ref for ref in refs.split(",")]})
    return rows


def balance(rows, seed, prefix, offset=0):
    """Choose positions with at most one answer difference per bank, reproducibly."""
    rng = random.Random(seed)
    positions = [chr(97 + ((i + offset) % 4)) for i in range(len(rows))]
    rng.shuffle(positions)
    result = []
    for i, (question, position) in enumerate(zip(rows, positions), 1):
        row = copy.deepcopy(question)
        correct = next(o["text"] for o in row["options"] if o["id"] == row["answer"])
        wrong = [o["text"] for o in row["options"] if o["id"] != row["answer"]]
        rng.shuffle(wrong)
        options = []
        for ident in "abcd":
            options.append({"id": ident, "text": correct if ident == position else wrong.pop()})
        row.update(id=prefix + "-%03d" % i, options=options, answer=position)
        result.append(row)
    return result


def build():
    v1_path = ROOT.parent / "exams.json"
    original = v1_path.read_bytes()
    legacy = json.loads(original)
    plan = json.loads((ROOT / "curriculum.json").read_text(encoding="utf-8"))
    objectives = {o["id"]: o for o in plan["objectives"]}
    modules = {
        "02": [retained(q, "republique") for q in legacy["modules"]["02"]],
        "03": [retained(q, "cadre-juridique") for q in legacy["modules"]["03"]],
        "05": [],
    }
    # Only the eight theoretical objectives; no active-attack protection/police
    # intervention or tactical first-aid gesture from the legacy module 05.
    selected_modules = {
        1: ("niveaux", "02", "vigipirate"),
        2: ("niveaux", "02", "plan"),
        4: ("detection", "05", "signalement"),
        5: ("reflexes", "04,15", "radicalisation"),
        6: ("materiels", "03", "plan"),
        7: ("materiels", "03,14", "plan"),
        8: ("materiels", "03,14", "plan"),
        9: ("materiels", "14", "plan"),
        18: ("menaces", "11", "plan"),
        19: ("menaces", "12", "plan"),
        21: ("menaces", "12", "plan"),
        22: ("menaces", "12", "drones"),
        23: ("detection", "05,16", "signalement"),
        24: ("culture", "06", "plan"),
        25: ("culture", "06", "plan"),
        26: ("blessures", "09", "mac"),
        29: ("secours", "10", "secours"),
    }
    for q in legacy["modules"]["05"]:
        selected = selected_modules.get(int(q["id"][-3:]))
        if selected:
            modules["05"].append(retained(q, *selected))
    modules["05"].extend(additions(MODULE_ADDITIONS))

    final = [retained(q, "republique" if q["module"] == "02" else "cadre-juridique")
             for q in sorted(legacy["final"], key=lambda q: q["id"]) if q["module"] in ("02", "03")]
    selected_final = {
        3: ("niveaux", "02,13", "bagages"),
        4: ("culture", "06", "plan"),
        5: ("culture", "06", "deonto"),
        6: ("detection", "05,16", "signalement"),
        7: ("materiels", "03,14", "plan"),
        8: ("materiels", "03", "plan"),
        10: ("detection", "05", "alerte"),
        21: ("blessures", "09", "sst"),
        26: ("detection", "16", "drones"),
        30: ("culture", "06", "plan"),
    }
    for q in sorted(legacy["final"], key=lambda q: q["id"]):
        selected = selected_final.get(int(q["id"][-3:])) if q["module"] == "05" else None
        if selected:
            final.append(retained(q, *selected))
    final.extend(additions(FINAL_ADDITIONS))

    # Stable interleaving avoids presenting the final as three separate tests.
    random.Random(VERSION + "-final-order").shuffle(final)
    for i, number in enumerate(modules):
        modules[number] = balance(modules[number], VERSION + number, "macaps-v2-q-" + number, offset=i)
    final = balance(final, VERSION + "-final", "macaps-v2-q-final")

    assessments = {}
    pool = [q for rows in modules.values() for q in rows] + final
    for i, objective in enumerate(plan["objectives"]):
        eligible = [q for q in pool if q["objective_id"] == objective["id"]]
        random.Random(VERSION + objective["id"]).shuffle(eligible)
        count = objective["assessment_question_count"]
        assert len(eligible) >= count, (objective["id"], len(eligible), count)
        selected = copy.deepcopy(eligible[:count])
        for row in selected:
            row["reinvestment_question_id"] = row.pop("id")
        assessments[objective["id"]] = balance(selected, VERSION + objective["id"],
            objective["id"] + "-v2-cloture", offset=i)

    result = {"schema_version": 2, "version": VERSION, "reviewed_on": "2026-10-12",
        "pedagogical_scope": "principal", "pass_percent": 80,
        "notice": "Évaluations pédagogiques du support numérique de 14 heures ; elles ne valent ni attestation de stage MAC APS ni certification SST et n'attribuent aucun crédit réglementaire automatique.",
        "final_distribution": {"02": 25, "03": 30, "05": 45},
        "objective_assessment_method": "Réinvestissement ciblé de questions du même objectif avec identifiants distincts ; les 190 questions des banques de modules et du final ont des énoncés distincts.",
        "legacy_source_sha256": hashlib.sha256(original).hexdigest(),
        "modules": modules, "final": final, "objectives": assessments}
    validate(result, objectives)
    assert original == v1_path.read_bytes(), "The legacy bank must never be modified."
    return result


def validate(result, objectives):
    assert set(result["modules"]) == {"02", "03", "05"}
    assert all(len(rows) == 30 for rows in result["modules"].values())
    assert len(result["final"]) == 100
    assert Counter(q["module"] for q in result["final"]) == result["final_distribution"]
    assert set(result["objectives"]) == set(objectives)
    assert sum(map(len, result["objectives"].values())) == 74
    banks = [*result["modules"].values(), result["final"], *result["objectives"].values()]
    main = [q for rows in result["modules"].values() for q in rows] + result["final"]
    assert len({normalized(q["prompt"]) for q in main}) == 190
    all_questions = [q for rows in banks for q in rows]
    assert len({q["id"] for q in all_questions}) == len(all_questions) == 264
    for rows in banks:
        positions = Counter(q["answer"] for q in rows)
        assert max(positions.values()) - min(positions.values()) <= 1
        for q in rows:
            objective = objectives[q["objective_id"]]
            assert q["module"] == objective["module"]
            assert q["lesson_refs"] and set(q["lesson_refs"]) <= set(objective["lesson_refs"])
            assert len(q["options"]) == 4 and {o["id"] for o in q["options"]} == set("abcd")
            assert len({normalized(o["text"]) for o in q["options"]}) == 4
            assert q["answer"] in "abcd" and len(q["explanation"]) > 60
            assert q["source_url"].startswith("https://") and q["source_url"] in q["sources"]
    for ident, rows in result["objectives"].items():
        assert len(rows) == objectives[ident]["assessment_question_count"]
        assert all(q["objective_id"] == ident for q in rows)


if __name__ == "__main__":
    payload = build()
    target = ROOT / "exams.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"file": str(target), "module_questions": 90, "final_questions": 100,
        "objective_questions": 74, "total": 264, "final_distribution": payload["final_distribution"]}, ensure_ascii=False))
