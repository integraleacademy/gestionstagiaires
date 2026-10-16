#!/usr/bin/env python3
"""Apply the reviewed pedagogical layer to the faithful 2020 PDF extraction.

Usage: python scripts/vtc/annales/enrich_annales_2020.py /private/path/source.pdf
Original question wording/choices and source keys are deliberately not repaired.
Ambiguous or outdated source items are retained for study, excluded from scoring.
"""
import json
import sys
from pathlib import Path
from pypdf import PdfReader
from extract_annales_2020 import extract

ROOT = Path(__file__).resolve().parents[3]

# One precise explanation per source question, mapped to existing course lessons.
NOTES = {
'A': [
('A.12', "La cour d’appel peut réexaminer un jugement correctionnel. La Cour de cassation contrôle l’application du droit ; elle n’est pas le degré ordinaire de réexamen des faits."),
('A.02 A.03', "La préfecture compétente instruit la demande de carte et contrôle les conditions d’honorabilité. Le conducteur ne remplace pas cette vérification administrative par un simple bulletin personnel."),
('A.05', "Deux risques sont à distinguer : les dommages liés à la circulation du véhicule et ceux liés à l’exécution professionnelle du service. L’assurance doit couvrir explicitement le transport rémunéré de personnes."),
('A.04 A.12', "Le corrigé 2020 retient B et D. Il faut distinguer le retrait administratif de la carte et les conséquences d’une décision pénale sur les conditions d’exercice ; un juge pénal n’est pas l’autorité qui délivre la carte."),
('A.03 A.04', "Une annulation du permis fait disparaître une condition nécessaire à la conduite professionnelle. Certaines condamnations visées par le code des transports sont incompatibles avec l’exercice : la qualification et l’inscription au casier doivent être examinées précisément."),
('A.01', "Une course T3P ne comporte pas de plafond général de 300, 500 ou 1 000 km. La distance n’exonère jamais du respect de la sécurité, de la réglementation territoriale et des conditions de la prestation."),
('A.02 A.04', "L’agrément du centre de formation relève du préfet du département d’implantation, ou du préfet de police à Paris. Ce contrôle du centre est distinct de la délivrance de la carte du conducteur."),
('A.11', "Police et gendarmerie peuvent contrôler une activité T3P. Un magistrat ou un agent SNCF n’a pas, du seul fait de cette qualité, la compétence de contrôle routier proposée dans l’énoncé."),
('A.01', "Le code des transports contient le cadre du transport public particulier de personnes. Le code de la route s’applique aussi à la conduite et d’autres textes régissent notamment les assurances et la consommation."),
('G.03 G.11', "Les catégories hybrides et électriques bénéficient d’une exception à la limite d’ancienneté propre aux VTC. Cela ne dispense ni du contrôle technique, ni de l’entretien, ni des autres obligations applicables."),
('G.05 A.11', "La preuve de réservation est un justificatif écrit, présentable sur papier ou support électronique. Une simple affirmation orale ne permet pas à l’agent de contrôler ses mentions."),
('G.05', "Le justificatif comporte l’identité et les coordonnées de l’exploitant, son numéro REVTC et son identifiant unique, les informations client, les dates et heures de réservation et de prise en charge, et le lieu prévu. Le texte de 2025 prévoit un moyen de contact immédiat si les informations client ne figurent pas sur le support."),
('G.03', "Une motorisation électrique n’efface pas toutes les contraintes professionnelles : assurance, signalétique, contrôle technique et conformité générale subsistent. L’exemption concerne des caractéristiques techniques déterminées, pas l’ensemble des règles T3P."),
('A.04', "Le 28 janvier 2020, une personne née le 12 mai 1950 avait 69 ans : le corrigé retient donc deux ans. Les visites professionnelles sont au maximum quinquennales avant 60 ans, biennales de 60 à moins de 76 ans et annuelles à partir de 76 ans."),
('A.01 F.01', "Aucun nombre minimal d’habitants ne conditionne à lui seul l’exercice d’une activité T3P. Le potentiel commercial local et les autorisations nécessaires sont des questions distinctes."),
],
'B': [
('B.05 B.10', "L’acquisition d’un véhicule destiné à servir durablement à l’activité est un investissement. Une prime d’assurance et des honoraires de comptabilité correspondent en principe à des charges de la période."),
('B.11', "Les pièces justificatives et documents comptables se conservent dix ans à compter de la clôture de l’exercice. Une durée applicable à un autre document ne remplace pas ce délai comptable."),
('B.04 B.10', "Dans le modèle linéaire fourni, 21 000 ÷ 3 = 7 000 € d’amortissement par année entière. L’amortissement répartit le coût d’un actif sur sa durée d’utilisation ; ce n’est pas le remboursement d’un crédit."),
('B.02', "L’ancien Répertoire des métiers utilisait notamment la nature artisanale de l’activité et un critère d’effectif. Depuis 2023, l’immatriculation artisanale se lit dans le Registre national des entreprises ; ne pas réutiliser une ancienne formalité comme procédure actuelle."),
('B.02', "L’Insee attribue le code APE à partir de l’activité principale déclarée. Ce code statistique décrit l’activité ; il ne tient pas lieu d’autorisation professionnelle VTC."),
('B.01', "La durée statutaire d’une société ne peut dépasser 99 ans lors de sa constitution. Une prorogation est possible : 99 ans ne signifie donc pas nécessairement disparition définitive de l’entreprise."),
('B.01', "SARL signifie société à responsabilité limitée. La limitation concerne en principe la responsabilité des associés à leurs apports ; elle ne supprime pas tous les risques d’une caution ou d’une faute."),
('B.02', "Le D1 était l’extrait d’immatriculation au Répertoire des métiers. L’attestation d’immatriculation au RNE est désormais le document à rechercher pour justifier l’inscription artisanale."),
('B.01', "Une personne morale est une entité reconnue par le droit, distincte des personnes qui la composent. Une société peut avoir un seul associé : le regroupement de plusieurs personnes n’est donc pas toujours nécessaire."),
('B.06', "La TVA à décaisser résulte de la TVA collectée exigible diminuée de la TVA déductible admise, avec les régularisations éventuelles. Si la différence est négative, il peut s’agir d’un crédit de TVA, pas d’un paiement négatif."),
('B.04', "Dans le périmètre de l’exploitation, produits supérieurs aux charges donnent un résultat d’exploitation positif. Ce bénéfice ne prouve pas à lui seul que la trésorerie est disponible ni que le résultat net est positif."),
('B.01 B.12', "Un gérant minoritaire rémunéré de SARL et un président rémunéré de SAS relèvent en principe du régime des assimilés salariés pour leur mandat. Ce régime social ne crée pas automatiquement un contrat de travail ni une assurance chômage."),
('B.03', "Le bilan présente un équilibre : total de l’actif = total du passif. Le résultat figure dans les capitaux propres ; il ne se lit pas en soustrayant les deux totaux du bilan."),
('B.12', "CRDS désigne la contribution au remboursement de la dette sociale. La reconnaître évite de la confondre avec une cotisation régionale ou une réduction de dette personnelle."),
('B.01 B.12', "Le président rémunéré de SASU est assimilé salarié au titre de son mandat social. Ce statut de sécurité sociale ne signifie pas qu’il dispose automatiquement d’un contrat de travail."),
('B.06', "La récupération de TVA sur le carburant dépend notamment du droit à déduction de l’entreprise, de l’affectation du véhicule et de la nature du carburant. La franchise en base ne permet pas de récupérer la TVA sur les achats : la formule « dans tous les cas » est impropre."),
('B.04 B.05', "Dans un régime réel et sous les conditions de déduction, l’entretien professionnel et les loyers de crédit-bail peuvent être des charges. Un prélèvement personnel n’est pas une charge ; l’achat du véhicule est normalement immobilisé puis amorti. En micro, ces dépenses ne sont pas déduites individuellement."),
('B.02 A.03', "L’immatriculation de l’entreprise et l’aptitude du conducteur sont deux contrôles distincts. Le permis D et la propriété du véhicule ne sont pas des conditions générales de création d’une entreprise VTC. Le Répertoire des métiers a été remplacé par le RNE."),
],
'C': [
('C.01 C.10', "Le voyant de réserve impose de rechercher une station accessible et d’adopter une conduite souple. Il ne justifie pas un arrêt dangereux au bord de la chaussée ; l’autonomie restante varie selon le véhicule et les conditions."),
('C.01', "Un pneu sous-gonflé se déforme davantage, augmente la résistance au roulement et s’échauffe. Cela peut accroître la consommation et le risque d’éclatement ; il faut vérifier la pression préconisée, de préférence à froid."),
('C.02', "À vitesse constante, 100 ÷ 120 × 60 = 50 minutes ; 100 ÷ 130 × 60 ≈ 46,15 minutes. Le gain théorique n’est que d’environ 3 min 51 s, soit quatre minutes, sans tenir compte de la circulation."),
('C.12', "Pour un accident seulement matériel, s’arrêter sans créer de danger et communiquer identité et adresse aux autres personnes impliquées sont les obligations visées. En présence de blessés, l’alerte aux services de secours et aux forces de l’ordre devient nécessaire."),
('C.12', "Le triangle se place à au moins 30 mètres pour prévenir les véhicules arrivants. Il ne faut pas l’installer si cette action expose manifestement le conducteur à un danger ; la mise à l’abri prime."),
('C.02', "Un dépassement de 40 à moins de 50 km/h relève de la quatrième classe et entraîne un retrait de quatre points. Ces conséquences ne doivent pas être confondues avec celles d’une tranche de vitesse voisine."),
('C.04', "En agglomération, le klaxon est réservé au danger immédiat. Saluer un collègue ou manifester son impatience n’entre pas dans ce motif."),
('C.05', "Le chevauchement non autorisé d’une ligne continue entraîne le retrait d’un point ; son franchissement est une autre infraction, avec un retrait de trois points. Identifier précisément le geste décrit est essentiel."),
('C.01 C.11', "Les feux de route doivent éclairer efficacement au moins 100 mètres par temps clair la nuit. Cette performance réglementaire ne signifie pas qu’ils peuvent être conservés lorsqu’ils éblouissent d’autres usagers."),
('C.03', "Le corrigé donne environ 80 mètres, proche du repère pédagogique 9 × 9 = 81 mètres. Une distance d’arrêt réelle dépend du temps de réaction, de l’adhérence, du freinage, des pneus et de la pente : ce chiffre n’est pas une constante à 90 km/h."),
('C.04', "Le piéton doit tenir compte de la visibilité, des distances et des vitesses. Il utilise un passage prévu à son intention s’il en existe à moins de 50 mètres ; le conducteur doit aussi anticiper et respecter sa priorité lorsqu’elle s’applique."),
('C.01', "Le pare-brise et les vitres latérales avant doivent transmettre au moins 70 % de la lumière, sauf dérogation prévue. Cette règle ne signifie pas 70 % de teinte et ne s’étend pas de la même manière aux vitres arrière."),
('C.12', "La bande d’arrêt d’urgence est réservée à une nécessité absolue telle qu’une panne ou un accident. Elle n’est pas un emplacement pour téléphoner, patienter ou déposer un passager."),
('C.03 C.09', "Une seconde est un ordre de grandeur usuel du temps de réaction d’un conducteur attentif. À 90 km/h, le véhicule parcourt déjà 25 mètres en une seconde avant même que le freinage ne commence ; fatigue et distractions peuvent allonger ce délai."),
('C.04', "Lors du dépassement d’un piéton ou d’un cycliste, l’écart latéral minimal est d’un mètre en agglomération et d’un mètre et demi hors agglomération. Si la place manque, il faut patienter."),
('A.04 C.02', "En permis probatoire, une infraction entraînant au moins trois points de retrait impose le stage de sensibilisation selon la procédure de la lettre 48N. Les pertes de trois et de quatre points proposées atteignent toutes deux ce seuil."),
('C.05', "Le panneau triangulaire représenté, avec deux bosses séparées par un creux, annonce un cassis ou dos-d’âne (A2a). Il se distingue du panneau de ralentisseur de type dos-d’âne qui représente une seule bosse."),
('C.11 C.03', "La pluie réduit généralement l’adhérence et allonge la distance de freinage, donc la distance d’arrêt. Elle ne modifie pas mécaniquement le temps physiologique de réaction ; il faut réduire la vitesse et augmenter les marges."),
('C.09', "Tenir un téléphone en main au volant expose à un retrait de trois points. La conversation, la lecture et la manipulation détournent l’attention ; un arrêt dans un emplacement autorisé doit précéder l’usage du téléphone."),
('C.08 A.12', "La récidive de conduite après usage de stupéfiants entraîne l’annulation du permis et expose à confiscation ou immobilisation du véhicule dans les conditions légales. Le régime de récidive doit être distingué d’une première infraction."),
],
'D': [
('D.03 D.06', "Le corrigé choisit la motorisation électrique ; l’article présente aussi un design inhabituel et moqué. Comme le lien causal avec la clientèle traditionnelle reste implicite, il faut distinguer la clé de l’annale et une preuve explicite dans le texte."),
('D.02', "Le texte de 2019 annonce 800 km pour le modèle supérieur et 400 km pour l’entrée de gamme. La question porte sur le maximum annoncé dans ce texte, pas sur une fiche commerciale actuelle."),
('D.07', "Un prototype est un premier modèle destiné à l’étude, à la mise au point ou aux essais d’un produit. Il n’est ni le dernier modèle d’une série ni nécessairement un produit commercialisé en grande quantité."),
('D.03 D.06', "La formule rapportée associe l’identité de Tesla à la controverse et à une rupture avec les attentes habituelles. Elle n’établit pas que tout scandale augmente forcément le succès commercial : cette causalité ajoutée par le corrigé dépasse le texte."),
('D.02', "Le passage indique que le même alliage doit être utilisé pour une fusée de SpaceX. Blade Runner est une référence cinématographique et le F-150 un modèle concurrent : ces noms jouent des rôles différents."),
('D.02 D.10', "La démonstration devait prouver la résistance du véhicule, mais une vitre du prototype s’est cassée lors du lancer d’une boule d’acier. Il faut relier l’objectif de la démonstration à l’événement qui le contredit."),
('D.07', "Dans « arborer un design », arborer signifie montrer ou afficher de façon visible. Le corrigé accepte aussi « révéler », synonyme plus approximatif ; « dissimuler » et « cacher » expriment l’idée opposée."),
('D.06 D.07', "Dans « une allure futuriste », allure désigne l’aspect ou le style du véhicule. Le même mot peut désigner une vitesse dans un autre contexte : la phrase, et non le mot isolé, permet de choisir."),
('D.02 D.10', "Pour répondre avec quatre caractéristiques, sélectionner quatre informations distinctes du texte : par exemple motorisation électrique, six places annoncées, construction en acier inoxydable et accélération annoncée de 0 à 100 km/h en environ trois secondes. Ce sont des annonces datées."),
('D.02 D.12', "Le texte nomme le Ford F-150 comme référence ancienne du marché américain. SpaceX désigne une entreprise spatiale et Blade Runner une œuvre de fiction, pas les modèles visés par cette phrase."),
],
'E': [
('E.11', "L’anglais imprimé ne comporte pas « not ». La traduction corrigée, « on m’a dit de ne rien dire », correspondrait à « I was told not to say anything ». Il faut repérer la négation au lieu d’apprendre cette paire erronée."),
('E.02 E.04', "« Available » signifie disponible et « get me to the station » exprime le transport jusqu’à la gare. Le français « disponible » n’est pas le mot anglais usuel ; « take me to the station » serait également naturel."),
('E.12', "« You will see » signifie « vous verrez ». Après « will », on emploie la base verbale ; ici « see » convient à une appréciation que le visiteur découvrira."),
('E.10', "« Ride » désigne ici la course et « keep the change » invite le conducteur à garder la monnaie. « Change » ne signifie pas changer de comportement dans cette formule de paiement."),
('E.06', "Une opération habituelle se dit au présent simple : « we check ». « Three times per year » signifie trois fois par an, alors que « per week » signifie par semaine. Pour le moteur d’une voiture, « engine » est plus courant."),
('E.02 E.04', "« Pick someone up » signifie passer prendre quelqu’un. « Could you…? » formule une demande polie ; « tomorrow at 6 » fixe un rendez-vous qu’il faut préciser en 6 a.m. ou 6 p.m. si le contexte ne suffit pas."),
('E.12', "« Have you come for…? » demande le motif de la venue : « êtes-vous venus pour…? ». Ce n’est ni une question sur le billet d’entrée ni une question sur un événement déjà visité."),
('E.09', "« Took » est le passé de « take » ; « were on strike » signifie étaient en grève. La traduction conserve donc le passé et la cause précise du recours au taxi."),
('E.05', "« Disabled welcome » indique un accueil des personnes en situation de handicap. Une formulation plus complète et respectueuse est « Passengers with disabilities are welcome » ; l’accueil ne garantit pas à lui seul l’accessibilité de tout véhicule."),
('E.10', "L’expression est « credit card ». Pour vérifier le paiement, on peut dire « Do you take credit cards? » ; traduire littéralement carte bleue par « blue card » ne convient pas ici."),
('E.10', "« Would you like a receipt? » propose poliment un reçu. « Did you want…? » renvoie au passé et « bill » désigne plutôt une facture ou l’addition, selon le contexte."),
('E.12', "« When … was built » demande la date de construction. La tournure passive permet de parler du bâtiment sans nommer son constructeur ; une demande de visite ne répond pas à la même question."),
('E.06', "La construction correcte est « forbidden to + verbe ». Pour annoncer la règle de service, « It’s forbidden to smoke in the car » signifie qu’il est interdit de fumer, à l’inverse de « allowed »."),
('E.12', "« Enjoy your stay » signifie apprécier son séjour. La question vise l’expérience du séjour, pas seulement une opinion générale sur la France."),
('E.09', "« En ce moment » appelle ici le présent continu : « are blocking ». Le présent simple décrit plutôt une habitude, « blocked » un passé et « will block » un futur. La phrase est un exercice de grammaire, pas une information routière actuelle."),
('E.12', "Pour une situation commencée dans le passé et toujours vraie, « has been living … for ten years » convient. « For » introduit une durée ; « since » introduit un point de départ, par exemple « since 2016 »."),
('E.07', "« Slow » signifie lent et son contraire est « fast », rapide. « Noisy » signifie bruyant et « dry » sec : il faut rester sur le même axe de sens."),
('E.12', "À la troisième personne du singulier au présent simple, le verbe prend généralement -s : « she speaks ». « Spoken » est un participe passé, pas un verbe conjugué seul dans cette phrase."),
('E.10', "« You owe us 53 euros » exprime une somme due. « Owe » signifie devoir de l’argent ; l’auxiliaire « must » exprime une obligation mais ne remplace pas ce verbe."),
('E.08', "« A lower price » signifie un prix plus bas. Le comparatif de « low » est « lower » ; « less price » et « gooder price » ne sont pas les constructions attendues."),
],
'F': [
('G.07 H.04', "La saturation du parking professionnel n’autorise ni l’arrêt sur des zébras ni l’occupation de la dépose réservée aux taxis. Rechercher un emplacement public autorisé et communiquer le point de rendez-vous au client."),
('F.10 H.08', "Contacter le client permet d’obtenir une nouvelle estimation puis de vérifier la compatibilité avec la course suivante. Si elle ne l’est plus, proposer une solution de remplacement convenue ; sinon organiser l’attente selon les conditions annoncées."),
('H.06 H.10 A.06', "Une dépose nocturne soignée combine emplacement autorisé, aide proposée et vérification discrète que la personne rejoint son accès en sécurité. Il faut respecter son accord et son intimité, sans imposer un accompagnement jusqu’à l’appartement."),
('F.04 G.09', "Les informations précontractuelles et conditions de vente doivent être adaptées au client particulier ou professionnel. Entre professionnels, des CGV établies doivent être communiquées à celui qui les demande ; une simple référence globale à la loi Hamon ne permet pas de vérifier leur contenu."),
('F.10', "Se présenter en donnant le nom de l’entreprise et en saluant identifie immédiatement le bon interlocuteur. Une formule brève et intelligible sécurise la prise de réservation, avant de relever les informations utiles."),
('F.03 F.12', "Une marge peut être rapportée au chiffre d’affaires ou au coût de revient, mais les taux diffèrent. Pour 100 € de vente et 80 € de coût, la marge de 20 € représente 20 % du CA et 25 % du coût."),
('F.01 F.02', "Les quatre P sont Product, Price, Place et Promotion : produit ou service, prix, distribution et communication. « Place » ne désigne pas seulement le lieu physique ; elle couvre la façon dont l’offre atteint le client."),
('B.04 B.10', "Trois ans est une durée souvent utilisée pour certains équipements informatiques. La durée d’amortissement doit néanmoins correspondre à l’utilisation attendue et aux règles applicables ; « peut être amorti » n’impose pas une durée unique pour tout matériel."),
('F.06 F.08', "La prospection peut être directe, par exemple auprès d’un hôtel ou par téléphone, ou numérique, par un site ou une campagne ciblée. Chaque canal demande un public défini, une offre claire et un suivi des contacts, en respectant les règles de démarchage et de données personnelles."),
('F.12', "Le panier moyen mesure le montant moyen des achats sur le périmètre retenu. Pour le calculer, préciser si l’on divise le chiffre d’affaires par le nombre de commandes ou de clients : ces dénominateurs ne sont pas interchangeables."),
('B.06 F.03', "Avec le taux de 10 % retenu dans le corrigé, HT = 75 ÷ 1,10 = 68,1818…, soit 68,18 € ; TVA = 75 − 68,18 = 6,82 €. Calculer 10 % du TTC donnerait une base erronée."),
('F.03', "Un prix de lancement très bas peut attirer des clients mais doit couvrir les coûts pertinents et préserver une marge. Vérifier aussi la durée de l’offre et son positionnement ; un prix bas ne prouve pas à lui seul une mauvaise qualité."),
('F.01', "L’analyse du marché précède normalement le choix du mix marketing et du plan d’action. Étudier la demande, la concurrence et les besoins permet de concevoir une offre et un prix cohérents."),
('F.06 F.09', "La prospection renouvelle le portefeuille et réduit la dépendance à quelques clients. Elle se combine à la fidélisation ; elle n’est pas une obligation imposée par le comptable."),
('F.01 F.07', "B to B signifie Business to Business : une entreprise fournit une autre entreprise. Les deux propositions qui donnent le développement anglais et sa définition française décrivent la même relation."),
('B.04 B.08', "Le corrigé obtient 43 000 € en faisant 50 000 − 10 000 + 8 000 − 5 000. Ce calcul ne suffit pas à déterminer un résultat comptable : la TVA reversée n’est généralement pas une charge et la cession exige notamment la valeur nette comptable du véhicule. Les données sont insuffisantes."),
],
'G': [
('G.06 A.12', "Le corrigé 2020 retient une peine de prison, 15 000 € d’amende et une suspension possible. Le plafond légal de l’article L3124-12 a depuis été porté à trois ans d’emprisonnement et 45 000 € d’amende ; il faut qualifier précisément l’infraction et la situation avant d’appliquer un texte."),
('G.03', "L’arrêté sur les véhicules VTC prévoit une exception technique pour les catégories hybrides et électriques visées. Il ne crée pas la demande individuelle de dérogation préfectorale systématique décrite dans le corrigé 2020."),
('G.03', "Pour les véhicules relevant des caractéristiques ordinaires VTC, les dimensions minimales sont 4,50 m de longueur et 1,70 m de largeur. Vérifier le champ des exceptions avant d’appliquer ces valeurs à un hybride ou un électrique."),
('G.01', "L’inscription au registre est une formalité d’exploitant, distincte de l’obtention de la carte de conducteur. Le corrigé indique une attestation et une présence sur la liste des exploitants ; aucune des deux ne constitue un diplôme."),
('G.04', "La signalétique VTC se place à l’avant et à l’arrière selon les emplacements réglementaires. La couleur noire du véhicule ou un aspect haut de gamme ne prouvent pas l’inscription de l’exploitant."),
('G.07', "Le stationnement en attente d’un client ayant réservé, dans l’enceinte d’une gare ou d’un aéroport ou à ses abords, est limité à une heure avant la prise en charge souhaitée. La réservation ne donne pas le droit d’occuper n’importe quel emplacement."),
('G.05 G.09', "Le support électronique est admis pour prouver la réservation. Il faut distinguer l’accord contractuel, les conditions générales, le justificatif obligatoire de réservation et la facture : ce sont des documents de fonctions différentes."),
('G.04 G.12', "Le corrigé reprend l’ancienne obligation de retirer ou d’occulter la signalétique hors activité VTC. Cette phrase ne figure plus dans l’article R3122-8 en vigueur depuis juillet 2017. Il faut consulter les prescriptions actuelles de signalétique et distinguer macaron définitif, temporaire et carte professionnelle, au lieu d’étendre automatiquement l’ancien texte."),
]}

HISTORICAL = {
'A04': "Les réponses historiques mêlent sanction administrative et conséquence d’une condamnation pénale. Le libellé ne précise pas la procédure ni le fondement : ne pas l’utiliser comme question notée sur le droit actuel.",
'A12': "La liste du corrigé 2020 ne comprend pas toutes les mentions désormais fixées par l’arrêté du 6 août 2025, notamment le numéro REVTC. Les anciennes réponses sont conservées ; apprendre la liste actuelle dans le complément.",
'A13': "La réponse source « sans contraintes particulières » est trop générale : l’exception concernant certaines caractéristiques techniques ne supprime pas les autres obligations professionnelles. Question neutralisée.",
'A14': "La date de naissance était à apprécier au jour de l’épreuve du 28 janvier 2020 (69 ans, deux ans). Au 7 octobre 2026, cette personne a 76 ans : la périodicité maximale professionnelle devient annuelle. Énoncé non actualisé, hors score.",
'B04': "Le Répertoire des métiers a été remplacé par le RNE le 1er janvier 2023. La procédure et le document historiques ne sont pas enseignés comme démarches actuelles.",
'B08': "Le D1 correspond à l’ancien Répertoire des métiers, remplacé par le RNE depuis 2023. Utiliser l’attestation d’immatriculation au RNE pour la situation actuelle.",
'B12': "L’énoncé confond salarié et assimilé salarié, omet la rémunération et appelle « gérant » le président de SAS. Les clés B/D du PDF sont préservées mais ne constituent pas une qualification sociale complète.",
'B16': "Le corrigé coche « oui, totalement dans tous les cas ». Cette affirmation absolue est fausse, notamment en franchise en base ; le droit à déduction dépend de la situation et du carburant. Ne pas noter selon cette clé.",
'B17': "L’énoncé dit seulement entrepreneur individuel et ne précise pas le régime fiscal. Les clés entretien/crédit-bail correspondent à une déduction de charges réelles sous conditions ; elles ne s’appliquent pas individuellement au régime micro.",
'B18': "Le RM a été remplacé par le RNE. La formulation réunit immatriculation de l’entreprise et qualification personnelle du conducteur ; il faut traiter ces démarches séparément.",
'C10': "Le corrigé retient 80 m sans préciser adhérence, pneus, freinage ou temps de réaction. Conserver comme repère historique, pas comme distance universelle ni question notée sans hypothèses.",
'D01': "Le corrigé retient le caractère électrique, mais le texte insiste aussi sur le design inhabituel et ne formule pas une cause unique. Question conservée pour discuter la distinction entre information explicite et inférence.",
'D04': "L’idée du corrigé selon laquelle les scandales ne feraient qu’accroître le succès généralise au-delà du texte. La citation originale et sa correction sont visibles, mais l’exercice est hors score.",
'D07': "Le corrigé accepte à la fois révéler et afficher. Dans le contexte, afficher est le synonyme net ; révéler est discutable. Les choix originaux restent inchangés et l’item est hors score.",
'E01': "L’énoncé anglais a perdu la négation « not », indispensable à la traduction C du corrigé. Aucune option ne restitue fidèlement la phrase imprimée : question neutralisée sans modifier l’original.",
'F04': "Une référence générale à la loi Hamon et le terme « facultatives » en B2B ne décrivent pas précisément les obligations actuelles d’information et de communication sur demande. Les choix historiques ne sont pas un test juridique actuel.",
'F08': "Le corrigé sélectionne uniquement trois ans alors que « peut être amorti » ne définit ni matériel, ni durée d’utilisation. D’autres durées peuvent être justifiées : la question n’a pas une clé exclusive suffisamment précise.",
'F10': "Le terme panier moyen est défini de façon trop vague dans le PDF (« par client ») sans période ni unité de transaction. Le tableau de bord doit distinguer panier par commande et revenu par client ; l’item n’est pas noté.",
'F16': "Le corrigé soustrait la TVA payée du résultat et ajoute tout le prix de cession du véhicule sans sa valeur nette comptable. Les données ne permettent pas un résultat comptable fiable : aucune proposition ne doit être imposée comme correction actuelle.",
'G01': "L’article 28 de la loi n°2026-534 du 25 juin 2026 a relevé, à l’article L3124-12, les maxima d’un à trois ans et de 15 000 à 45 000 €. Les options de 2020 sont conservées et exclues du score.",
'G02': "Le corrigé exige une demande préfectorale de dérogation pour l’électrique. L’exception technique est prévue directement par l’article 2 de l’arrêté du 26 mars 2015 pour les catégories visées ; cette démarche générale n’est pas fondée par ce texte.",
'G07': "L’énoncé assimile le contrat avec le client au justificatif de réservation obligatoirement présentable. La règle papier/électronique du justificatif est vérifiable ; l’obligation générale de forme écrite de tout contrat n’est pas établie par cette question.",
'G08': "Le corrigé reprend la rédaction de R3122-8 applicable de 2015 à juillet 2017. La rédaction actuelle ne contient plus cette obligation de retrait/occultation hors activité. Portée actuelle à confirmer au regard de l’arrêté de signalétique avant réemploi en évaluation.",
}

# Pedagogical choice sets for original short-answer questions; no text entry.
QRC = {
'A03': (["Responsabilité civile circulation couvrant le transport rémunéré et responsabilité civile professionnelle.", "Assurance automobile privée et assurance de protection juridique, sans extension transport rémunéré.", "Responsabilité civile professionnelle seule, la réservation couvrant les risques de circulation."], ['a']),
'A05': (["Annulation du permis ou condamnation incompatible avec l’exercice au titre du code des transports.", "Changement d’adresse et renouvellement de l’assurance du véhicule.", "Baisse du chiffre d’affaires et fin d’un partenariat avec une plateforme."], ['a']),
'A07': (["Le préfet du département où se trouve le centre, ou le préfet de police à Paris.", "La CMA qui organise l’examen, sans agrément préfectoral.", "Le gestionnaire du registre des exploitants VTC."], ['a']),
'A11': (["Un justificatif écrit de réservation sur papier ou support électronique.", "La carte professionnelle accompagnée d’une déclaration orale du client.", "La facture de la course précédente, si elle indique la même destination."], ['a']),
'A12': (["Un support papier ou électronique mentionnant notamment l’entreprise et les dates/heures de réservation et de prise en charge.", "Un accord oral précisant la destination et le prix, sans justificatif consultable.", "Un relevé de paiement mentionnant uniquement le montant et la date du règlement."], ['a']),
'B03': (["7 000 € par année entière : 21 000 ÷ 3.", "6 300 € par année entière : 21 000 × 30 %.", "21 000 € chaque année, car le véhicule est utilisé trois ans."], ['a']),
'B09': (["Une entité reconnue par le droit et distincte des personnes qui la constituent, telle qu’une société.", "Toute personne physique qui dirige une entreprise, quelle que soit sa forme.", "Un groupe de salariés qui utilise une enseigne, sans existence juridique propre."], ['a']),
'D04': (["La citation présente la controverse comme une composante habituelle de l’image de Tesla.", "La citation annonce que Tesla abandonne les innovations et imite ses concurrents.", "La citation affirme que le prototype est déjà homologué pour tous les marchés."], ['a']),
'D06': (["Une boule d’acier a cassé la vitre que la démonstration devait montrer résistante.", "Le moteur électrique n’a pas permis au prototype de monter sur scène.", "Le constructeur a annulé le lancement avant de présenter le véhicule."], ['a']),
'D09': (["Électrique ; six places annoncées ; acier inoxydable ; environ trois secondes annoncées de 0 à 100 km/h.", "Hybride ; quatre places ; carrosserie en aluminium ; autonomie de 100 km.", "Diesel ; six places ; acier inoxydable ; autonomie de 400 km pour tous les modèles."], ['a']),
'F02': (["Contacter le client, estimer le retard, puis convenir d’une attente ou d’un remplacement compatible avec les engagements suivants.", "Annuler la réservation sans contact dès que l’horaire annoncé est dépassé.", "Attendre sans prévenir même si cela empêche d’honorer la réservation suivante."], ['a']),
'F09': (["Prospection directe auprès d’hôtels ou par téléphone, et prospection numérique par site ou communication ciblée.", "Uniquement la présence sur une plateforme, sans contact ni suivi commercial.", "Uniquement la fidélisation des clients existants, sans recherche de nouveaux contacts."], ['a']),
'F11': (["HT : 68,18 € ; TVA : 6,82 €, en divisant 75 par 1,10.", "HT : 67,50 € ; TVA : 7,50 €, en calculant 10 % du TTC.", "HT : 82,50 € ; TVA : 7,50 €, en ajoutant 10 % au TTC."], ['a']),
'F12': (["Vérifier les coûts et la marge : attirer du volume par un prix bas peut fragiliser rentabilité et positionnement.", "Conclure qu’un prix bas assure la rentabilité dès que le nombre de clients augmente.", "Choisir le tarif uniquement à partir du prix d’un concurrent, sans calcul de ses propres coûts."], ['a']),
'G02': (["Demander une dérogation au préfet avant l’inscription du véhicule : réponse historique du corrigé, contestée dans la mise à jour.", "Demander une dérogation au constructeur après l’immatriculation du véhicule.", "Obtenir uniquement un accord écrit de la plateforme de réservation."], ['a']),
'G08': (["Retirer ou occulter la signalétique VTC pendant l’usage privé.", "Masquer seulement la vignette arrière et conserver celle de l’avant visible.", "Laisser les deux vignettes visibles dès lors que la carte professionnelle est rangée."], ['a']),
}

SOURCES = {
'appeal': ('Service Public · Faire appel d’un jugement', 'https://www.service-public.gouv.fr/particuliers/vosdroits/F1384'),
'vtc': ('Service Public Entreprendre · Devenir chauffeur de VTC', 'https://entreprendre.service-public.gouv.fr/vosdroits/F31027'),
'rne': ('Service Public Entreprendre · Remplacement du RM par le RNE', 'https://entreprendre.service-public.gouv.fr/actualites/A15855'),
'reservation': ('Arrêté du 6 août 2025 · Justificatif de réservation VTC', 'https://www.legifrance.gouv.fr/jorf/id/JORFTEXT000052153206'),
'hybrid': ('Arrêté du 26 mars 2015 · Article 2, catégories hybrides et électriques', 'https://www.legifrance.gouv.fr/loda/article_lc/LEGIARTI000030437123'),
'medical': ('Code de la route · Article R221-11', 'https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000046217357/2026-04-28'),
'formation': ('Préfecture · Agrément des centres T3P', 'https://www.ille-et-vilaine.gouv.fr/index.php/Demarches/Activites-et-professions-reglementees/Transport-public-et-prive-de-personnes/Les-formations-T3P-initiale-continue-et-mobilite/Les-formations-T3P-initiale-continue-et-mobilite'),
'social': ('Service Public Entreprendre · Régime social du gérant de SARL', 'https://entreprendre.service-public.gouv.fr/vosdroits/F37411'),
'legalform': ('Service Public Entreprendre · Formes juridiques', 'https://entreprendre.service-public.gouv.fr/vosdroits/F23844'),
'accounting': ('Service Public Entreprendre · Obligations comptables', 'https://entreprendre.service-public.gouv.fr/vosdroits/F37169'),
'ape': ('Insee · Code APE attribué à l’entreprise', 'https://www.insee.fr/fr/information/2015441'),
'companyduration': ('Code de commerce · Article L210-2', 'https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000006222349/2026-05-10'),
'crds': ('Service Public · CSG et CRDS', 'https://www.service-public.gouv.fr/particuliers/vosdroits/F2971'),
'fuel': ('BOFiP · TVA, déduction et produits pétroliers', 'https://bofip.impots.gouv.fr/bofip/1194-PGP.html/identifiant=BOI-TVA-DED-30-30-40-20210224'),
'vat': ('Service Public Entreprendre · Déclarer et payer la TVA', 'https://entreprendre.service-public.gouv.fr/vosdroits/F23566'),
'points': ('Service Public · Barème des retraits de points', 'https://www.service-public.gouv.fr/particuliers/vosdroits/F31551'),
'accident': ('Code de la route · Article R231-1', 'https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000006841506/2026-05-16'),
'triangle': ('DGCCRF · Gilet et triangle de sécurité', 'https://www.economie.gouv.fr/dgccrf/les-fiches-pratiques/gilet-et-triangle-de-securite'),
'horn': ('Code de la route · Article R416-1', 'https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000006842256'),
'headlight': ('Code de la route · Article R313-2', 'https://www.legifrance.gouv.fr/loda/article_lc/LEGIARTI000042266184/2022-03-31'),
'pedestrian': ('Code de la route · Article R412-37', 'https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000023095943/2026-04-01'),
'windows': ('Code de la route · Article R316-3', 'https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000032401379/2026-08-03'),
'emergency': ('Code de la route · Article R421-7', 'https://www.legifrance.gouv.fr/loda/article_lc/LEGIARTI000047794509/2026-03-06'),
'overtake': ('Code de la route · Dépassement, article R414-4', 'https://www.legifrance.gouv.fr/codes/section_lc/LEGITEXT000006074228/LEGISCTA000006177131/2022-09-01/'),
'probation': ('Service Public · Stage de sensibilisation', 'https://www.service-public.gouv.fr/particuliers/vosdroits/F14208'),
'drugs': ('Code de la route · Article L235-4', 'https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000023718915/2026-07-01'),
'cgv': ('Ministère de l’Économie · CGV entre professionnels', 'https://www.economie.gouv.fr/entreprises/gerer-sa-comptabilite-et-ses-demarches/conditions-generales-de-vente-entre'),
'sanction': ('Code des transports · Article L3124-12, version du 27 juin 2026', 'https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000047053344'),
'signage': ('Code des transports · Article R3122-8, version depuis juillet 2017', 'https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000034389549/2026-05-03'),
'waiting': ('Code des transports · Article D3120-3, attente en gare et aéroport', 'https://www.legifrance.gouv.fr/codes/section_lc/LEGITEXT000023086525/LEGISCTA000030048393/2026-01-05'),
}

SOURCE_MAP = {
'A01':'appeal','A02':'vtc','A03':'vtc','A05':'vtc','A07':'formation',
'A10':'hybrid','A11':'reservation','A12':'reservation','A13':'hybrid','A14':'medical',
'B02':'accounting','B04':'rne','B05':'ape','B06':'companyduration','B07':'legalform','B08':'rne','B10':'vat',
'B12':'social','B14':'crds','B15':'legalform','B16':'fuel','B18':'rne',
'C04':'accident','C05':'triangle','C06':'points','C07':'horn','C08':'points','C09':'headlight',
'C11':'pedestrian','C12':'windows','C13':'emergency','C15':'overtake','C16':'probation',
'C19':'points','C20':'drugs','F04':'cgv','G01':'sanction','G02':'hybrid','G03':'vtc',
'G04':'vtc','G05':'vtc','G06':'waiting','G07':'reservation','G08':'signage',
}

FRENCH_PASSAGE = """Texte reproduit dans l’annale, page 11 (article du 22 novembre 2019 ; annonces datées, à lire comme un document de compréhension).

Gros fail et design douteux... Elon Musk présente le « cybertruck » 100% électrique de Tesla
BLADE RUNNER Cet engin électrique est censé résister à toute attaque extérieure (mais n’a pas résisté pendant le show)

Lignes (très) épurées et inox mat pour le nouveau véhicule Tesla. Elon Musk fait un bond dans le futur en présentant jeudi soir près de Los Angeles son étrange « cybertruck », moitié véhicule blindé, moitié avion furtif et 100 % électrique. Un show à l’américaine... qui ne s’est pas déroulé comme prévu.
Elon Musk avait prévenu : son véhicule aurait une allure « futuriste » et « cyberpunk » inspirée par Blade Runner, le film de science-fiction de Ridley Scott [...]. « Il ne ressemble à rien d’autre », a résumé fièrement le PDG de Tesla sur scène, désignant son pick-up massif aux lignes angulaires lors d’un show dans le centre de design du constructeur à Hawthorne (Californie). Un design rapidement moqué sur les réseaux sociaux.

Résistant... mais pas trop
À défaut d’arborer un design élégant, le « cybertruck » affiche sur le papier des performances impressionnantes, abondamment vantées par Elon Musk avec des démonstrations impliquant des coups de masse, des jets de boules en acier, voire des tirs d’arme à feu, ceux-là enregistrés en vidéo pour raisons de sécurité.
« C’est littéralement résistant aux balles de pistolet calibre 9 mm », a-t-il assuré. « C’est un alliage en acier inoxydable ultrarésistant que nous avons développé. Nous allons utiliser le même alliage pour la fusée spatiale que pour le “cybertruck” », a lancé Elon Musk en référence à l’activité de SpaceX, dont il est aussi le fondateur et le PDG.
Problème : lors de l’essai de l’envoi d’une balle d’acier sur scène, la démonstration rate, et la vitre du prototype casse (sans toutefois exploser). Rires dans la salle, sourire gêné pour Elon Musk. « Oh my f**king God. Bon... Peut-être que c’était un peu trop violent. On va arranger ça en post-production », blague le milliardaire.

Moins de 50.000 dollars
Le futur pickup de Tesla aura six places, pourra emporter plus de 1,5 tonne et sera capable de tracter sept tonnes, a-t-il détaillé. Le « cybertruck » sera décliné en trois modèles, 39.900 dollars et 400 km d’autonomie pour l’entrée de gamme, jusqu’à 69.900 dollars et 800 km d’autonomie annoncée pour le modèle supérieur. Et il pourra passer de 0 à 100 km/h en environ trois secondes, s’est réjoui le fantasque patron de Tesla.
Elon Musk avait promis que son fameux pick-up coûterait moins de 50.000 dollars, un prix dans la moyenne de cette catégorie de véhicules, et qu’il surpasserait les performances du Ford F-150, numéro un aux États-Unis sur ce segment depuis longtemps.
Certains experts estiment que le pick-up électrique Tesla aura du mal à séduire la clientèle traditionnelle pour ce type d’engins. « Même si le pick-up de Tesla ne séduit pas les amateurs habituels du F-150, il n’en a pas forcément besoin », relevait Jessica Caldwell, directrice de la prospective pour le guide automobile Edmunds, dans une déclaration transmise à l’AFP avant la présentation. « Si le pick-up Tesla n’était pas un peu polémique, ça ne serait pas une Tesla », estime-t-elle.

Source indiquée dans le document : 20 Minutes, article du 22 novembre 2019. Transcription de l’image fournie ; la ponctuation typographique a été normalisée."""


def build(pdf_path):
    data = extract(pdf_path)
    data['reviewed_on'] = '2026-10-07'
    data['correction_policy'] = 'QCM : choix et clés du PDF conservés, reconnus par les pictogrammes jaunes. QRC : réponse du PDF conservée ; choix pédagogiques ajoutés. Les items obsolètes ou ambigus sont hors évaluation.'
    data['extraction_checks'] = {'vtc_questions':107,'qcm':91,'qrc_adapted':16,'excluded_specialty_questions':39,'source_pages':22}
    for section in data['sections']:
        module = section['module']
        assert len(NOTES[module]) == len(section['questions'])
        for q in section['questions']:
            key = f"{module}{q['number']:02}"
            refs, explanation = NOTES[module][q['number']-1]
            q.update(lesson_refs=refs.split(), explanation=explanation, learning_points=[explanation],
                     status='historical' if key in HISTORICAL else 'active',
                     update_note=HISTORICAL.get(key, ''), sources=[])
            if key in SOURCE_MAP:
                title,url = SOURCES[SOURCE_MAP[key]]
                q['sources'].append({'title':title,'url':url})
            if q['original_kind'] == 'qrc':
                options, answers = QRC[key]
                shift = (ord(module) + q['number']) % len(options)
                rotated = options[shift:] + options[:shift]
                q['options'] = [{'id':chr(97+i),'text':v} for i,v in enumerate(rotated)]
                q['answers'] = [chr(97 + ((ord(a)-97-shift) % len(options))) for a in answers]
                q['kind'] = 'multiple' if len(answers)>1 else 'single'
                q['correction_origin'] = 'pedagogical'
                q['original_answer_origin'] = 'source'
                q['adaptation_note'] = 'Question ouverte originale transformée en choix pédagogiques pour un entraînement sans rédaction. Les choix ne figuraient pas dans l’épreuve ; la réponse source est conservée séparément.'
            if module == 'D':
                q['image'] = 'media/vtc/annales/annales-2020-d-texte.png'
                q['context'] = FRENCH_PASSAGE
            if key == 'C17':
                q['image'] = 'media/vtc/annales/annales-2020-c-17.png'
            if key == 'F11':
                q['context'] = 'Hypothèse pédagogique explicite du corrigé : prestation soumise à une TVA de 10 %. Ce taux n’était pas écrit dans la question originale.'
    # Verify every mapping against actual lesson coverage, not an invented index.
    existing = {}
    for p in (ROOT/'elearning_native/vtc/courses').glob('*/20261007-vtc-v4-visuals.json'):
        course = json.loads(p.read_text())
        for section in course['sections']:
            for activity in section['activities']:
                vtc = activity.get('vtc', {})
                if vtc.get('kind') == 'lesson':
                    existing[vtc['ref']] = activity['title']
    questions = [q for s in data['sections'] for q in s['questions']]
    for q in questions:
        assert q['prompt'] and q['explanation'] and q['learning_points'] and q['answers'], q['id']
        assert set(q['lesson_refs']) <= existing.keys(), q['id']
        assert set(q['answers']) <= {o['id'] for o in q['options']}, q['id']
        assert q['status'] != 'historical' or q['update_note'], q['id']
    assets = ROOT/'elearning_native/vtc/assets/media/vtc/annales'
    assets.mkdir(parents=True, exist_ok=True)
    pdf = PdfReader(pdf_path)
    for page_index, name in [(7,'annales-2020-c-17.png'), (10,'annales-2020-d-texte.png')]:
        image = max(pdf.pages[page_index].images, key=lambda i:i.image.width*i.image.height)
        image.image.save(assets/name)
    output = ROOT/'elearning_native/vtc/annales/annales-2020.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'questions':len(questions),'active':sum(q['status']=='active' for q in questions),'historical':sum(q['status']=='historical' for q in questions),'qrc':sum(q['original_kind']=='qrc' for q in questions),'output':str(output)},ensure_ascii=False))


if __name__ == '__main__':
    build(Path(sys.argv[1]))
