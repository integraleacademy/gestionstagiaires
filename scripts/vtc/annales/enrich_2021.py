"""Pedagogical annotations of all 107 VTC questions from the supplied 2021 source.

Run after extract_2021.py; input is the extracted JSON, output the final bank.
No source PDF or identifying examination headers are committed.
"""
import json
import sys
from pathlib import Path

# Each row was reviewed against the current A–H lesson titles/content.
# Fields: module/number, lesson references, worked explanation / course supplement.
NOTES = """
A01|A.11,A.02|Les gendarmes et les policiers font partie des agents habilités à contrôler un conducteur de T3P. Le juge intervient dans le traitement judiciaire d'une affaire ; être agent de la SNCF ne confère pas à lui seul ce pouvoir de contrôle routier.
A02|A.12|L'appel d'un jugement correctionnel permet à la cour d'appel de réexaminer l'affaire. La Cour de cassation contrôle l'application du droit dans les décisions rendues en dernier ressort ; elle ne remplace pas cet appel ordinaire.
A03|A.01|Le T3P n'est pas réservé aux communes dépassant un nombre minimal d'habitants. Le chauffeur doit en revanche respecter les règles propres à son activité, notamment la réservation préalable pour un VTC.
A04|A.02,A.04|L'agrément d'un centre de formation T3P relève de l'autorité préfectorale. Il faut distinguer cet agrément du centre, la carte du conducteur et l'inscription de l'exploitant au REVTC.
A05|A.03|La demande de carte professionnelle relève du préfet compétent, ou du préfet de police dans son ressort. Le contrôle de l'honorabilité ne doit pas être confondu avec la délivrance du permis de conduire ou l'immatriculation de l'entreprise.
A06|G.03|L'exception d'ancienneté vise les véhicules VTC hybrides et électriques. Elle ne supprime pas les obligations générales de sécurité, d'assurance et de contrôle technique. Il faut vérifier l'éligibilité du véhicule avec ses caractéristiques exactes.
A07|G.05|Un justificatif de réservation peut être présenté sur papier ou sur support électronique. Il identifie l'exploitant et le client, ainsi que les dates, heures et lieu utiles pour établir que la commande a précédé la prise en charge. La liste de 2021 ne suffit pas pour établir un justificatif conforme aujourd'hui.
A08|G.05,A.11|La réservation doit pouvoir être justifiée par un document écrit, papier ou électronique, accessible lors du contrôle. Une simple affirmation orale du chauffeur ne remplace pas cette preuve.
A09|A.12,A.04|Le retrait de carte professionnelle peut être décidé par l'autorité administrative. Une condamnation pénale peut aussi faire perdre une condition d'honorabilité et conduire à la restitution ou au retrait de la carte ; il faut distinguer la condamnation de la décision administrative.
A10|A.05|Deux risques sont à couvrir : la circulation du véhicule utilisé pour transporter des personnes à titre onéreux et la responsabilité civile professionnelle de l'activité. Une assurance automobile pour usage privé ne remplace pas ces garanties professionnelles.
A11|A.01|Le Code des transports regroupe les règles spécifiques du transport public particulier de personnes. Le Code de la route et les autres codes continuent de s'appliquer dans leur domaine : la règle spécifique T3P ne remplace pas les règles générales.
A12|G.03|Un véhicule électrique peut bénéficier de dérogations à certaines caractéristiques techniques imposées aux VTC thermiques. Dire qu'il est « sans contraintes particulières » est trop large : la sécurité, l'assurance, la signalétique, les places autorisées et les autres obligations restent à vérifier.
A13|A.04|Pour une visite médicale professionnelle du permis B, la périodicité maximale dépend de l'âge : cinq ans avant 60 ans, deux ans de 60 à 75 ans et un an à partir de 76 ans. Le conducteur né le 12 mai 1950 avait 71 ans lors du sujet de 2021, mais 76 ans le 7 octobre 2026.
A14|A.04,A.12|La carte professionnelle suppose que les conditions de permis, d'aptitude et d'honorabilité restent remplies. L'annulation du permis ou certaines condamnations pénales incompatibles avec la profession peuvent ainsi conduire à sa restitution ou à son retrait.
A15|A.01,H.02|Il n'existe pas de plafond kilométrique général propre à une course de T3P. Une longue prestation exige néanmoins une préparation réaliste : pauses, fatigue, autonomie, itinéraire, prix convenu et règles applicables au trajet.
B01|B.05|Au régime réel, une dépense d'entretien professionnel et un loyer de crédit-bail constituent des charges, sous réserve des conditions de déductibilité. L'achat d'un véhicule durable est une immobilisation à amortir ; un prélèvement personnel de l'exploitant n'est pas une charge. En micro, les dépenses réelles ne se déduisent pas individuellement.
B02|B.04|Le résultat d'exploitation se calcule en soustrayant les charges d'exploitation des produits d'exploitation. Si les produits sont supérieurs aux charges, le résultat est un bénéfice d'exploitation ; il ne faut pas en déduire automatiquement que la trésorerie est positive.
B03|B.01|La durée fixée dans les statuts d'une société ne peut excéder 99 ans. Une prorogation décidée selon les règles applicables peut prolonger sa vie : 99 ans n'impose donc pas la disparition automatique définitive de toute société.
B04|B.02|L'extrait D1 était le justificatif d'immatriculation au Répertoire des métiers. Depuis le 1er janvier 2023, ce répertoire a été remplacé par le Registre national des entreprises : il faut rechercher l'attestation d'immatriculation au RNE.
B05|B.10|Un amortissement linéaire répartit la base amortissable de façon régulière sur la durée retenue. Avec les seules données de l'exercice, 21 000 € divisés par 3 ans donnent 7 000 € par an, soit un taux annuel de 33,33 %, hors prorata éventuel de première année.
B06|B.02,A.03|Le sujet ancien associait l'inscription artisanale à la qualification requise pour exercer le T3P. Aujourd'hui, l'immatriculation se fait au RNE via le guichet unique ; elle ne dispense ni de la carte professionnelle ni des autres conditions d'exercice.
B07|B.02|L'Insee attribue le code APE à partir de l'activité principale déclarée. Ce code permet de classer statistiquement l'entreprise ; il ne vaut pas à lui seul autorisation d'exercer une profession réglementée.
B08|B.01|SARL signifie société à responsabilité limitée. Le sigle décrit une forme juridique de société ; il ne désigne ni un régime fiscal unique ni une société anonyme.
B09|B.03|Un bilan est équilibré : le total de l'actif égale le total du passif. L'actif décrit les emplois et le passif les ressources, notamment les capitaux propres et les dettes. Le bénéfice se lit dans le résultat, pas dans un déséquilibre entre les deux côtés.
B10|B.01|Une personne morale est une entité dotée d'une personnalité juridique distincte de celle de ses membres. Une société peut donc avoir ses propres droits et obligations ; elle peut aussi être unipersonnelle, contrairement à l'idée qu'un regroupement de plusieurs personnes serait toujours nécessaire.
B11|B.01,B.12|Le président de SASU rémunéré au titre de son mandat relève du régime des assimilés salariés. Cette affiliation sociale n'établit pas, à elle seule, un contrat de travail et n'ouvre pas automatiquement droit à l'assurance chômage.
B12|B.12|CRDS signifie contribution pour le remboursement de la dette sociale. Il s'agit d'une contribution sociale nationale, à distinguer des cotisations et d'une éventuelle taxe locale.
B13|B.02|Le Répertoire des métiers concernait les entreprises artisanales selon la nature de leur activité et leur effectif. Il a été remplacé par le RNE en 2023 : une question utilisant encore le RM doit être datée et replacée dans son contexte historique.
B14|B.01,B.12|Le président de SAS rémunéré est assimilé salarié pour sa protection sociale. Un mandat social n'est pas automatiquement un emploi salarié : un véritable contrat de travail suppose notamment des fonctions distinctes et un lien de subordination.
B15|B.06|La TVA à décaisser correspond, dans le cas simple, à la TVA collectée sur les ventes moins la TVA déductible sur les achats. Si la TVA déductible est supérieure, l'entreprise dispose d'un crédit de TVA selon les règles applicables ; la TVA n'est pas le chiffre d'affaires HT.
B16|B.05,B.10|L'acquisition d'un véhicule utilisé durablement est un investissement et entre à l'actif en immobilisation. L'entretien courant, l'assurance et les honoraires d'expert-comptable relèvent en principe des charges de la période.
B17|B.06|La récupération de TVA n'est jamais automatique « dans tous les cas ». Elle suppose un droit à déduction, une dépense professionnelle justifiée et le respect des règles propres au carburant et à l'affectation du véhicule. Une entreprise en franchise de TVA ne récupère pas cette taxe.
B18|B.11|Les documents comptables et pièces justificatives doivent être conservés pendant dix ans. Organiser une archive lisible et accessible permet de retrouver les factures, les écritures et les comptes, même après un changement de logiciel.
C01|C.02|À vitesse constante, 100 km à 120 km/h prennent 50 minutes. À 130 km/h, le temps est 100 ÷ 130 × 60 = 46,15 minutes. Le gain théorique n'est que d'environ 3 min 51 s, donc quatre minutes, sans tenir compte du trafic.
C02|C.11,C.03|La pluie réduit l'adhérence et allonge la distance de freinage. La distance d'arrêt, qui ajoute la distance de réaction à celle de freinage, augmente donc aussi. Le temps de réaction ne s'allonge pas mécaniquement du seul fait que la chaussée est mouillée.
C03|C.09|L'usage d'un téléphone tenu en main au volant est sanctionné par le retrait de trois points, en plus de l'amende applicable. La bonne méthode consiste à préparer les communications avant de partir et à s'arrêter dans un endroit autorisé pour manipuler le téléphone.
C04|C.12|Après un accident purement matériel, le conducteur impliqué doit s'arrêter dès qu'il le peut sans créer un danger et communiquer son identité et son adresse aux autres personnes impliquées. L'appel aux forces de l'ordre n'est pas systématiquement obligatoire pour tout dégât matériel.
C05|C.04|Un piéton doit tenir compte de la visibilité ainsi que de la distance et de la vitesse des véhicules avant de traverser. Il doit utiliser un passage prévu à cet effet lorsqu'il en existe à moins de 50 mètres. Le conducteur reste tenu de respecter la priorité des piétons dans les conditions du Code de la route.
C06|C.08|La récidive légale de conduite après usage de stupéfiants expose à l'annulation du permis. La confiscation ou l'immobilisation du véhicule peut aussi intervenir selon les conditions prévues par les textes ; ces conséquences s'ajoutent aux autres sanctions du délit.
C07|C.01,C.10|Le voyant de réserve invite à rechercher rapidement une station accessible et à adopter une conduite souple limitant la consommation. Il ne justifie pas, à lui seul, un arrêt dangereux sur le bord de la chaussée ni l'usage des feux de détresse.
C08|C.01|Le pare-brise et les vitres latérales avant doivent transmettre au moins 70 % de la lumière, sous réserve des exceptions prévues. La règle de transparence ne se résume pas à la teinte visible : il faut considérer l'ensemble vitre et film.
C09|C.12|Un triangle de présignalisation se place à au moins 30 mètres de l'obstacle, et peut devoir être placé plus loin pour être visible. Il ne faut pas l'installer si cette action met manifestement la vie du conducteur en danger, notamment selon la situation sur autoroute.
C10|C.04|En agglomération, l'avertisseur sonore est réservé au danger immédiat. Saluer un collègue ou demander au client de descendre ne constitue pas un usage autorisé du klaxon.
C11|C.03|Le sujet attend l'ordre de grandeur de 80 mètres à 90 km/h, proche du repère pédagogique 9 × 9 = 81. Ce repère n'est pas une garantie de sécurité : réaction, adhérence, pneus, freins et conditions de circulation modifient la distance réelle d'arrêt.
C12|C.01,C.10|Un pneu sous-gonflé se déforme davantage, chauffe et peut s'endommager ; il augmente aussi la résistance au roulement et donc la consommation. Vérifier la pression à froid selon les indications du constructeur évite d'interpréter cette déformation comme une meilleure adhérence.
C13|C.02|Un excès de vitesse d'au moins 40 km/h et de moins de 50 km/h relève d'une contravention de quatrième classe et entraîne un retrait de quatre points. Il peut aussi entraîner des mesures ou peines complémentaires : ces deux réponses ne résument pas toutes les conséquences.
C14|C.03,C.07|Une seconde est un repère courant pour le temps de réaction d'un conducteur attentif. Pendant ce délai, le véhicule continue à avancer avant le début du freinage. Fatigue, alcool, stupéfiants et distraction peuvent allonger ce temps.
C15|C.12|La bande d'arrêt d'urgence sert aux situations d'urgence telles qu'une panne ou un accident. Elle n'est ni une aire de repos ni un emplacement autorisé pour téléphoner ; les occupants doivent se mettre à l'abri selon les possibilités de sécurité.
C16|C.05|Le chevauchement d'une ligne continue entraîne le retrait d'un point ; son franchissement est une infraction distincte qui entraîne trois points, hors dérogations prévues. Il faut donc identifier précisément le comportement décrit.
C17|C.11|Les feux de route doivent éclairer efficacement la route, par temps clair et de nuit, sur au moins 100 mètres. Leur portée ne dispense pas d'adapter la vitesse et de repasser en feux de croisement pour éviter d'éblouir.
C18|C.02,A.04|Pendant le permis probatoire, une infraction qui fait perdre au moins trois points en une seule fois entraîne l'obligation de suivre le stage après réception de la lettre 48N. Les cas de trois points et de quatre points proposés par le sujet sont donc tous deux concernés.
C19|C.04|Pour dépasser un piéton ou un cycliste, la distance latérale minimale est d'un mètre en agglomération et d'un mètre cinquante hors agglomération. Si les conditions ne permettent pas cette marge, il faut attendre pour dépasser.
C20|C.05|Le panneau triangulaire représenté annonce un cassis ou un dos-d'âne. Son symbole à deux bosses se distingue du panneau annonçant un ralentisseur de type dos-d'âne. À l'approche, ralentir avant l'irrégularité pour protéger les passagers.
D01|D.02,D.12|Dans le texte fourni, le Ford F-150 est présenté comme le numéro un de longue date sur le marché américain des pick-up. Pour répondre, repérer la comparaison explicite avec le concurrent plutôt que choisir un nom propre simplement mentionné ailleurs.
D02|D.07|Un prototype est un modèle d'essai ou d'étude servant à mettre au point un produit avant sa fabrication définitive. Il n'est ni le dernier exemplaire d'une série ni un modèle déjà diffusé à grande échelle.
D03|D.03,D.12|Le corrigé de l'annale retient le caractère électrique du pick-up comme obstacle possible pour la clientèle traditionnelle. Le passage final évoque les doutes des experts sur l'accueil du pick-up électrique ; il faut répondre selon le document et non selon les ventes actuelles.
D04|D.07,D.06|Dans « arborer un design élégant », arborer signifie montrer ou afficher avec évidence. L'annale admet « révéler » et « afficher », opposés à cacher et dissimuler ; replacer chaque proposition dans la phrase permet de contrôler le sens.
D05|D.02,D.10|Le véhicule était présenté comme très résistant aux attaques extérieures, mais sa vitre s'est cassée sous le jet d'une balle d'acier pendant la démonstration. La réponse attendue relie donc la promesse de résistance à l'échec constaté, sans confondre la vitre avec la carrosserie.
D06|D.02|Le texte indique que le même alliage serait utilisé pour la fusée spatiale de SpaceX. Blade Runner est une référence esthétique et le F-150 un pick-up concurrent : ces noms ne répondent pas à la question sur l'alliage.
D07|D.02,D.03|L'autonomie maximale annoncée dans cet article ancien est de 800 km pour le modèle supérieur, contre 400 km pour l'entrée de gamme. Il s'agit de lire une annonce de prototype dans le document, pas de mémoriser une caractéristique commerciale actuelle.
D08|D.06,D.10|L'affirmation citée associe l'identité de Tesla à la nouveauté et à la controverse. L'idée à reformuler est que son caractère inhabituel peut provoquer des réactions tout en attirant l'attention ; il ne s'agit pas d'une preuve que toute polémique améliore réellement les ventes.
D09|D.07,D.06|Dans « une allure futuriste et cyberpunk », allure désigne l'aspect ou le style du véhicule. Le mot peut ailleurs parler de vitesse, mais les adjectifs de cette phrase orientent vers l'apparence.
D10|D.02,D.10|Pour relever quatre caractéristiques, sélectionner quatre informations distinctes explicitement présentes : propulsion électrique, six places, acier inoxydable et allure futuriste, par exemple. Les chiffres annoncés concernent le prototype décrit dans cet article ancien.
E01|E.12|« Do you know when this historical monument was built? » demande la date de construction du monument. Dans cette question indirecte, l'ordre est « when + sujet + was built », sans inverser de nouveau le sujet et l'auxiliaire.
E02|E.12|« You will see » signifie « vous verrez ». Après will, le verbe est à la base verbale ; see convient à cette annonce générale, tandis que look demande souvent une direction et watch implique une observation prolongée.
E03|E.02,E.03|« Could you pick me up here tomorrow at 6, please? » est une demande polie de prise en charge. Le groupe verbal est pick up ; le pronom me se place entre pick et up. Here, tomorrow et at 6 précisent le lieu, le jour et l'heure.
E04|E.10|Dans le contexte du paiement, « ride » désigne la course et « keep the change » signifie « gardez la monnaie ». Change ne désigne pas ici une modification du trajet.
E05|E.01,E.12|« Do you enjoy your stay in France? » demande si le séjour se passe agréablement. « Do you like France? » pose une question générale sur le pays et perd l'idée de séjour.
E06|E.12|Au présent simple, un sujet à la troisième personne du singulier exige généralement un s : she speaks. Spoken est le participe passé et ne peut pas compléter seul cette phrase.
E07|E.12|« Have you come for the music festival? » se traduit par « Êtes-vous venus pour le festival de musique ? ». For indique le motif de la venue ; la phrase ne demande pas si les personnes ont déjà leur billet.
E08|E.10|« Would you like a receipt? » propose poliment un reçu. Receipt est une preuve de paiement, bill une facture ou une addition, et ticket peut désigner un titre de transport.
E09|E.08|Pour demander un prix moins élevé, on utilise « a lower price ». Lower est le comparatif de low et qualifie price ; reduction est un nom et less ne convient pas à cette construction.
E10|E.09|« The yellow vests are blocking the motorways » utilise le présent en be + ing parce que l'action se déroule en ce moment. Le présent simple évoque une habitude et le prétérit une action passée.
E11|E.05,A.09|« Disabled welcome » indique dans l'annale que les personnes handicapées sont accueillies. Pour communiquer avec respect aujourd'hui, préférer « Disabled passengers are welcome » ou « Passengers with disabilities are welcome », puis demander l'aide souhaitée sans la présumer.
E12|E.02,E.04|« Are you available to get me to the station? » demande si le chauffeur est disponible pour conduire le client à la gare. Available signifie disponible ; le mot français disponible ne remplace pas le mot anglais.
E13|E.10|Le groupe courant est « credit card », carte bancaire ou carte de crédit selon le contexte. Business card signifie carte de visite ; « blue card » n'est pas la traduction usuelle de carte bancaire.
E14|E.11|« I was told not to say anything concerning this new advert » signifierait « on m'a dit de ne rien dire de cette nouvelle publicité ». Dans l'énoncé fourni, le mot not manque : la traduction négative du corrigé ne peut donc pas être déduite de la phrase telle qu'elle est écrite.
E15|E.06|Une vérification effectuée trois fois par an est une habitude : « We check the motor three times per year ». En usage courant, engine est souvent préférable pour le moteur d'une voiture ; three times a year exprime la même fréquence.
E16|E.10|« You owe us 53 euros » signifie « vous nous devez 53 euros ». Owe exprime une dette ; must exprime une obligation et ne se construit pas directement avec une personne suivie d'un montant.
E17|E.07|Fast, rapide, est le contraire de slow, lent. Noisy signifie bruyant et dry signifie sec. Associer les mots à des situations de trajet aide à éviter une réponse fondée uniquement sur leur longueur.
E18|E.06|« It's forbidden to smoke in the car » indique l'interdiction de fumer. La construction est forbidden + to + verbe ; allowed exprimerait au contraire une autorisation.
E19|E.03,E.12|« She has been living in Paris for ten years » exprime une situation commencée dans le passé et toujours vraie. For introduit une durée, tandis que since introduit un point de départ, par exemple since 2016.
E20|E.09|« I took a taxi because the buses were on strike » signifie que les bus étaient en grève et que le taxi a été pris pour cette raison. Took et were situent les faits dans le passé ; on strike est l'expression pour « en grève ».
F01|F.03|Un prix très bas peut attirer des clients sans couvrir le coût complet de la prestation. Avant une remise, calculer la marge après approche, retour, commission et charges ; vérifier aussi l'effet possible du tarif sur l'image du service.
F02|F.03,F.12|Une marge peut être rapportée au chiffre d'affaires ou au coût de revient, mais le dénominateur doit être nommé. Pour un coût de 80 € et une vente de 100 €, la marge de 20 € représente 20 % du prix de vente ou 25 % du coût : les deux pourcentages décrivent le même montant.
F03|F.02|Les 4P du marketing mix sont Product, Price, Place et Promotion : produit ou service, prix, distribution et communication. Place ne désigne pas ici une place assise mais la manière de rendre l'offre accessible aux clients.
F04|F.06,F.08|La prospection peut être directe, par exemple un contact téléphonique avec un hôtel, ou numérique, par exemple une présentation de l'offre sur un site professionnel. Choisir le canal selon la clientèle recherchée et mesurer les contacts qui deviennent des réservations.
F05|F.01|La stratégie commerciale commence par l'analyse du marché : clients visés, besoins, concurrence et contraintes locales. Le positionnement, le marketing mix puis le plan d'action se construisent à partir de cette analyse.
F06|F.10,H.08|Si le client est fortement retardé, le contacter pour estimer son heure d'arrivée et vérifier les engagements suivants. Si l'attente compromet une autre course, proposer avec son accord une solution de remplacement ; expliquer les conditions d'attente convenues et garder une trace du nouvel accord.
F07|B.10,F.12|L'annale retient trois ans pour amortir le matériel informatique. Il s'agit d'une durée d'usage courante dans un exercice, et non d'une durée universelle imposée à tout matériel : la durée retenue doit correspondre à l'utilisation prévue et aux règles comptables applicables.
F08|B.06,F.04|Avec un taux de TVA de 10 %, le HT se calcule en divisant le TTC par 1,10. Pour 75 € TTC : 75 ÷ 1,10 = 68,18 € HT après arrondi ; la TVA est 75 − 68,18 = 6,82 €. Soustraire directement 10 % de 75 € donnerait un résultat erroné.
F09|B.04,B.06|Le corrigé ancien obtient 43 000 € par 50 000 − 10 000 + 8 000 − 5 000. Ce calcul ne suffit pas à établir un résultat comptable fiable : il manque notamment la valeur nette comptable du véhicule vendu et la nature HT/TTC des données. Une TVA reversée n'est pas en principe une charge de résultat lorsque la taxe est récupérable.
F10|F.10,H.06|La dépose de nuit doit préserver sécurité et discrétion. Dans la situation du sujet, attendre brièvement que la cliente entre dans son immeuble est l'attention attendue ; proposer spontanément de l'accompagner jusqu'à son appartement peut être intrusif. Respecter son souhait et stationner sans danger.
F11|F.04,G.09|Les CGV encadrent le prix, l'exécution, le paiement et les autres conditions du service. Elles doivent être communiquées au consommateur avant la conclusion du contrat ; entre professionnels, leur communication est requise sur demande. La seule référence à la loi Hamon ne remplace pas la vérification du droit actuel.
F12|G.07,H.04|Si le parking professionnel est saturé, chercher un stationnement public autorisé et informer les clients du point de rencontre. Les zébras et les emplacements réservés aux taxis ne deviennent pas utilisables par un VTC du seul fait de la saturation.
F13|F.10,H.04|Une réponse téléphonique professionnelle commence par une salutation et l'identification de l'entreprise. Le client sait ainsi immédiatement qui lui répond avant de communiquer les détails de sa réservation.
F14|F.12|Le panier moyen mesure le montant moyen des achats ou prestations par client ou commande selon la définition retenue. Il se calcule en divisant le chiffre d'affaires du périmètre par le nombre correspondant ; il faut conserver la même définition pour comparer les périodes.
F15|F.06|La prospection régulière renouvelle le portefeuille de clients et réduit la dépendance à quelques donneurs d'ordre. Elle doit être organisée, suivie et rapprochée du coût d'acquisition ainsi que de la rentabilité des prestations obtenues.
F16|F.07,F.01|B to B signifie business to business : une relation commerciale entre professionnels. Une entreprise qui réserve des transferts pour ses collaborateurs est un exemple ; la vente au particulier relève du B to C.
G01|G.03|Pour un VTC concerné par ces caractéristiques minimales, la longueur est de 4,50 m et la largeur de 1,70 m. Vérifier aussi les autres conditions et les dérogations applicables aux véhicules hybrides ou électriques : les dimensions seules ne suffisent pas.
G02|G.06,A.12|La prise en charge sans réservation préalable relève de la maraude interdite aux VTC. L'annale de 2021 évoque 15 000 € et la suspension du permis ; la loi du 25 juin 2026 a porté le plafond de l'article L3124-12 à trois ans d'emprisonnement et 45 000 € d'amende, sans supprimer les peines complémentaires.
G03|G.05,G.09|La réservation et les conditions convenues doivent pouvoir être prouvées. Un support électronique est admis : une impression papier n'est pas obligatoire par principe. Des CGV générales ne remplacent pas les éléments propres à la commande du client.
G04|G.03|La dérogation concernant certaines caractéristiques des VTC électriques découle du texte ; elle ne suppose pas une autorisation individuelle pour ignorer ces seules caractéristiques. Elle n'exonère pas le véhicule de toutes les exigences de sécurité, de capacité, d'assurance, de signalétique et de contrôle.
G05|G.07|Avec une réservation préalable, la durée maximale de stationnement avant l'horaire de prise en charge souhaité dans une gare ou un aéroport est d'une heure. Le chauffeur doit aussi respecter les règles du site et pouvoir présenter le justificatif de réservation.
G06|G.04|Le sujet de 2021 attend le retrait de la carte professionnelle lors de l'usage privé. Le texte actuel impose l'affichage de la carte pendant l'usage professionnel. Ne pas transposer automatiquement une ancienne règle d'occultation de la signalétique : cette phrase ne figure plus dans l'article R3122-8 en vigueur depuis juillet 2017.
G07|G.04|Un VTC en activité porte la signalétique réglementaire à l'avant et à l'arrière. La couleur de sa carrosserie n'est pas un signe légal d'identification et un seul macaron ne suffit pas.
G08|G.01|L'inscription de l'exploitant au registre des VTC donne lieu à une attestation et à son référencement dans la liste des exploitants. Il faut distinguer cette inscription de l'examen du conducteur et de sa carte professionnelle : aucun diplôme n'est délivré par cette inscription.
"""

QRC_CHOICES = {
'A04': ['Les préfectures.', 'Les chambres de métiers et de l’artisanat, sans décision préfectorale.', 'Les organismes assureurs du centre.'],
'A07': ['Un document papier ou électronique comportant notamment l’identité et les coordonnées de l’exploitant, ainsi que la date et l’heure de réservation et de prise en charge.', 'Un document papier comportant seulement le prix estimé et le modèle du véhicule.', 'Une confirmation orale du client avec le lieu de dépose.'],
'A08': ['Un document écrit sur papier ou support électronique.', 'Le témoignage oral du passager suffit dans tous les cas.', 'Un relevé des courses déjà terminées sans la commande concernée.'],
'A10': ['Une assurance du véhicule couvrant le transport de personnes à titre onéreux et une responsabilité civile professionnelle.', 'Une assurance automobile pour usage privé uniquement.', 'Une responsabilité civile professionnelle qui dispense de toute assurance circulation.'],
'A14': ['L’annulation du permis et certaines condamnations pénales incompatibles avec la profession.', 'Le remplacement du véhicule et un changement d’assureur déclaré.', 'Une baisse du chiffre d’affaires et la perte d’un contrat commercial.'],
'B05': ['21 000 ÷ 3 = 7 000 € par an.', '21 000 × 3 = 63 000 € par an.', '21 000 ÷ 36 = 583,33 € par an.'],
'B10': ['Une entité juridique distincte de ses membres, comme une société.', 'Toute personne physique majeure qui signe un contrat.', 'Un dirigeant dont les dettes personnelles sont toujours celles de son entreprise.'],
'D05': ['La vitre du prototype a cassé sous une balle d’acier malgré la résistance annoncée.', 'La fusée spatiale n’a pas décollé pendant le lancement du pick-up.', 'Le prix de vente annoncé était supérieur à celui de tous les concurrents.'],
'D08': ['La nouveauté et la controverse font partie de l’image de Tesla évoquée dans le texte.', 'Tesla ne commercialise que des modèles approuvés à l’unanimité.', 'Le texte démontre que le véhicule ne sera jamais vendu.'],
'D10': ['100 % électrique, six places, acier inoxydable et allure futuriste.', '100 % électrique, cinq places, aluminium et autonomie maximale annoncée de 400 km.', 'Motorisation hybride, six places, acier inoxydable et autonomie maximale annoncée de 800 km.'],
'F01': ['Le prix risque de réduire la rentabilité et d’altérer la perception de la qualité.', 'Le volume de clients suffit toujours à rendre rentable une course vendue sous son coût.', 'Le prix très bas garantit à lui seul une clientèle fidèle et solvable.'],
'F04': ['Prospection directe par téléphone ; prospection numérique par site web ou réseaux sociaux.', 'La prospection se limite aux appels téléphoniques ; un site internet ne peut attirer de nouveaux clients.', 'Le renouvellement automatique des contrats existants est la seule méthode de prospection commerciale.'],
'F06': ['Contacter le client, réévaluer l’attente et proposer un remplaçant si les engagements suivants l’exigent.', 'Partir sans contacter le client dès que l’horaire est dépassé.', 'Accepter de l’attendre sans limite sans vérifier les autres réservations.'],
'F08': ['HT = 75 ÷ 1,10 = 68,18 € ; TVA = 75 − 68,18 = 6,82 €.', 'TVA = 75 × 10 % = 7,50 € ; HT = 67,50 €.', 'HT = 75 × 1,10 = 82,50 € ; TVA = 7,50 €.'],
'G04': ['Aucune demande de dérogation individuelle pour les caractéristiques techniques dont le véhicule électrique est exempté.', 'Demander systématiquement au préfet une dérogation individuelle aux dimensions et à la puissance.', 'Déposer une demande de dérogation temporaire au REVTC avant chaque prestation.'],
'G06': ['Retirer la carte professionnelle, selon la réponse attendue dans le sujet de 2021.', 'Renvoyer la carte professionnelle à la préfecture avant chaque déplacement privé.', 'Conserver systématiquement la carte bien visible pour prouver le caractère privé.'],
}

SOURCES = {
'appel': ('Faire appel d’un jugement — Service Public', 'https://www.service-public.gouv.fr/particuliers/vosdroits/F1384'),
'formation': ('Code des transports — agrément des centres, R3120-9', 'https://www.legifrance.gouv.fr/codes/id/LEGISCTA000030048387'),
'reservation': ('Justificatif de réservation VTC — arrêté du 6 août 2025', 'https://www.legifrance.gouv.fr/loda/id/JORFTEXT000052153206/'),
'assurance': ('Assurance professionnelle VTC — Service Public', 'https://entreprendre.service-public.gouv.fr/vosdroits/F31027'),
'charge': ('Charges déductibles du résultat — Service Public', 'https://entreprendre.service-public.gouv.fr/vosdroits/F31973'),
'ape': ('Attribution et modification du code APE — Insee', 'https://www.insee.fr/fr/information/7614104'),
'crds': ('CSG et CRDS — Service Public', 'https://www.service-public.gouv.fr/particuliers/vosdroits/F2971'),
'tva': ('Déduire la TVA sur les achats — DGFiP', 'https://www.impots.gouv.fr/professionnel/questions/comment-deduire-la-tva-sur-mes-achats'),
'carburant': ('Franchise et absence de déduction — DGFiP', 'https://www.impots.gouv.fr/professionnel/tva'),
'feux': ('Feux de route — article R313-2', 'https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000042266184/2025-11-16'),
'probatoire': ('Stage obligatoire du permis probatoire — Service Public', 'https://www.service-public.gouv.fr/particuliers/vosdroits/F14208'),
'transporttva': ('Taux de TVA, transport de voyageurs — DGFiP', 'https://www.impots.gouv.fr/international-professionnel/fiscalite-des-entreprises'),
'vignette': ('Conditions d’utilisation des VTC — Préfecture du Nord', 'https://www.nord.gouv.fr/Demarches/Activites-et-professions-reglementees/Voiture-de-transport-avec-chauffeur-VTC/Les-conditions-d-utilisation'),
'signaletique': ('Code des transports — article R3122-8 actuel', 'https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000034389549/2026-05-03'),
'vtc': ('Devenir chauffeur de VTC — Service Public', 'https://entreprendre.service-public.gouv.fr/vosdroits/F31027'),
'conducteur': ('Code des transports — obligations des conducteurs', 'https://www.legifrance.gouv.fr/codes/id/LEGIARTI000054659821/2026-08-12'),
'carte': ('Code des transports — article R3120-6', 'https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000030048403/'),
'medical': ('Code de la route — article R221-11', 'https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000046217357/2026-01-02'),
'rne': ('Le Registre national des entreprises', 'https://www.registre.entreprises.gouv.fr/informer.php'),
'societe': ('Code civil — article 1838', 'https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000006444089/2013-11-28'),
'sasu': ('SASU — Service Public', 'https://entreprendre.service-public.gouv.fr/vosdroits/F37383'),
'sas': ('SAS — Service Public', 'https://entreprendre.service-public.gouv.fr/vosdroits/F37366'),
'comptes': ('Conservation des documents — Service Public', 'https://entreprendre.service-public.gouv.fr/vosdroits/F10029'),
'route': ('Code de la route — usage des voies', 'https://www.legifrance.gouv.fr/codes/section_lc/LEGITEXT000006074228/LEGISCTA000006129092/'),
'points': ('Barème des retraits de points — Service Public', 'https://www.service-public.gouv.fr/particuliers/vosdroits/F31551'),
'equipement': ('Équipements obligatoires — Service Public', 'https://www.service-public.gouv.fr/particuliers/vosdroits/F19459'),
'vitesse': ('Vitesse au volant — Service Public', 'https://www.service-public.gouv.fr/particuliers/vosdroits/F19460'),
'drogue': ('Code de la route — dispositions relatives au conducteur', 'https://www.legifrance.gouv.fr/codes/section_lc/LEGITEXT000006074228/LEGISCTA000006129084/2026-05-14/'),
'cgv': ('Conditions générales de vente — Service Public', 'https://entreprendre.service-public.gouv.fr/vosdroits/F33527'),
'fraude2026': ('Loi du 25 juin 2026 — article 28, sanctions T3P', 'https://www.legifrance.gouv.fr/eli/loi/2026/6/25/SFHT2521808L/jo/texte'),
}

QUESTION_SOURCES = {
'A01':['conducteur'],'A02':['appel'],'A03':['vtc'],'A04':['formation'],'A05':['carte'],'A06':['vtc'],'A07':['reservation'],'A08':['conducteur','reservation'],'A09':['carte'],'A10':['conducteur','assurance'],'A11':['conducteur'],'A12':['vtc'],'A13':['medical'],'A14':['carte'],'A15':['vtc'],
'B01':['charge'],'B03':['societe'],'B04':['rne'],'B06':['rne','vtc'],'B07':['ape'],'B11':['sasu'],'B12':['crds'],'B13':['rne'],'B14':['sas'],'B15':['tva'],'B17':['carburant','tva'],'B18':['comptes'],
'C03':['points'],'C04':['route'],'C05':['route'],'C06':['drogue'],'C08':['equipement'],'C09':['equipement'],'C10':['route'],'C13':['vitesse'],'C15':['route'],'C16':['points'],'C17':['feux'],'C18':['probatoire'],'C19':['route'],
'F08':['transporttva'],'F09':['tva'],'F11':['cgv'],'F12':['vtc'],
'G01':['vtc'],'G02':['fraude2026'],'G03':['conducteur','cgv'],'G04':['vtc'],'G05':['conducteur'],'G06':['carte','signaletique'],'G07':['vtc','vignette'],'G08':['vtc'],
}

HISTORICAL = {
'A07': 'Liste ancienne des mentions : le justificatif VTC est désormais régi par l’arrêté du 6 août 2025, entré en vigueur le 29 octobre 2025. Le numéro REVTC et le SIREN font notamment partie des mentions à contrôler. La question de 2021 est conservée pour comparaison, sans servir de formulaire actuel.',
'A12': 'Formulation trop générale : l’exemption de certaines caractéristiques des véhicules électriques ne signifie pas absence de toutes contraintes. La réponse D du corrigé ancien ne doit pas devenir une règle de conformité actuelle.',
'A13': 'L’âge est calculé dans le contexte de l’examen de 2021 : 71 ans, donc deux ans maximum. Au 7 octobre 2026, cette personne a 76 ans : la périodicité maximale est alors d’un an. Ne pas réutiliser cette question datée avec le même corrigé comme règle actuelle.',
'B04': 'Le Répertoire des métiers et son extrait D1 sont un dispositif ancien. Le RNE a remplacé le RM depuis le 1er janvier 2023 ; l’attestation RNE est le justificatif à rechercher aujourd’hui.',
'B06': 'Le Répertoire des métiers mentionné n’est plus le registre d’immatriculation actuel depuis le 1er janvier 2023. Les formalités RNE et les conditions spécifiques de conducteur/exploitant doivent être distinguées.',
'B13': 'Le sujet porte sur le Répertoire des métiers, remplacé par le RNE depuis le 1er janvier 2023. Les critères historiques ne constituent pas une description complète des formalités actuelles.',
'B14': 'Le corrigé retient le président de SAS comme « salarié », mais le statut précis est assimilé salarié. Un contrat de travail n’est pas automatique. Cette ambiguïté exclut la question du score actuel.',
'B17': 'Le corrigé ancien affirme une récupération totale « dans tous les cas », sans préciser régime de TVA, carburant ni affectation du véhicule. Cette généralisation est inexacte ; aucune des propositions universelles ne donne une règle actuelle suffisamment fiable.',
'E14': 'Le texte anglais fourni omet la négation not alors que le corrigé traduit une interdiction de parler. La phrase correcte serait « I was told not to say anything concerning this new advert ». Le texte original est conservé et non noté.',
'F07': 'Trois ans est la durée retenue par le corrigé, mais l’énoncé ne précise pas la durée d’utilisation attendue du matériel. La formulation « peut être amorti » rend d’autres durées possibles selon les circonstances ; question conservée hors score pour éviter une règle universelle trompeuse.',
'F09': 'Le calcul source 50 000 − 10 000 + 8 000 − 5 000 = 43 000 mélange flux et résultat. Il manque la valeur nette comptable du véhicule cédé et la précision HT/TTC. La TVA reversée n’est normalement pas une charge de résultat pour une opération ouvrant droit à déduction.',
'F11': 'Le corrigé ancien coche B et C mais ne retient pas D. « Facultatives en B to B » est ambigu : distinguer l’établissement des CGV de leur communication obligatoire lorsqu’un client professionnel les demande. La loi Hamon seule ne décrit pas toutes les obligations actuelles ; question exclue du score.',
'G02': 'La loi n° 2026-534 du 25 juin 2026, article 28, a relevé la peine de l’article L3124-12 de un an et 15 000 € à trois ans et 45 000 €. Les choix et le corrigé de 2021 restent visibles comme archive ; ils ne servent pas au score actuel.',
'G04': 'Le corrigé d’origine affirme sans nuance qu’un véhicule électrique n’a pas de caractéristiques techniques à respecter. La dérogation est limitée : ce texte ne doit pas faire oublier les exigences restantes. Adaptation explicitement nuancée et conservée hors score.',
'G06': 'Le corrigé ancien attend « retirer la carte professionnelle ». Le texte actuel consulté impose son affichage pendant l’usage professionnel mais ne formule pas cette consigne privée de la même façon. L’ancienne phrase sur l’occultation de la signalétique a disparu de R3122-8 en juillet 2017 ; l’ensemble des prescriptions d’usage privé nécessite confirmation avant d’en faire une question notée.',
}

def enrich(data):
    metadata={}
    for line in NOTES.strip().splitlines():
        key,refs,explanation=line.split('|',2)
        metadata[key]=(refs.split(','),explanation)
    titles={'A':'Réglementation du T3P','B':'Gestion','C':'Sécurité routière','D':'Français','E':'Anglais','F':'Développement commercial et gestion spécifiques VTC','G':'Réglementation nationale spécifique VTC'}
    minutes={'A':45,'B':45,'C':30,'D':30,'E':30,'F':30,'G':20}
    for s in data['sections']:
        s.update(title=titles[s['module']],minutes=minutes[s['module']])
        for q in s['questions']:
            key=f'{s["module"]}{q["number"]:02}'
            refs,explanation=metadata[key]
            q.update(lesson_refs=refs,explanation=explanation,learning_points=[explanation],correction_origin='source',status='historical' if key in HISTORICAL else 'active',update_note=HISTORICAL.get(key,''),sources=[])
            for source in QUESTION_SOURCES.get(key,[]):
                title,url=SOURCES[source]; q['sources'].append({'title':title,'url':url})
            if q['original_kind']=='qrc':
                q['options']=[{'id':chr(97+i),'text':t} for i,t in enumerate(QRC_CHOICES[key])]
                q['adaptation_note']='Adaptation pédagogique en choix de réponse d’une question ouverte du sujet. L’énoncé et la réponse source sont conservés ; les choix ont été rédigés pour l’entraînement sans rédaction.'
            q['kind']='multiple' if len(q['answers'])>1 else 'single'
            if key=='C20':
                q['image']='media/vtc/annales/annales-2021-c-20.webp'
                q['context']='Panneau du document d’examen : triangle à bord rouge contenant une chaussée noire à deux bosses.'
            if s['module']=='D':
                q['image']='media/vtc/annales/annales-2021-d-context.webp'
                q['context']='Document de compréhension extrait du sujet de 2021, article de 2019 sur la présentation du prototype Cybertruck. Répondre selon ce document : ses annonces techniques ne décrivent pas le véhicule commercialisé aujourd’hui.\n\n'+FRENCH_CONTEXT
    data['reviewed_at']='2026-10-07'
    data['provenance_note']='Questions et corrigés du PDF fourni. QCM : repères jaunes de correction extraits des images, contrôlés contre les options ; QRC : rubrique « Indication/Right answer ». Titres et identifiants personnels d’examen non repris.'
    data['excluded_sections']=[
        {'title':'Réglementation nationale et gestion spécifiques TAXI','module':'G(T)','pages':[17,18],'question_count':15,'reason':'Spécialisation taxi, hors périmètre VTC.'},
        {'title':'Sécurité routière et réglementation spécifiques VMDTR','module':'F(M)','pages':[19,20],'question_count':16,'reason':'Spécialisation véhicules motorisés à deux ou trois roues, hors périmètre VTC.'},
        {'title':'Prise en charge et développement commercial VMDTR','module':'G(M)','pages':[21],'question_count':8,'reason':'Spécialisation véhicules motorisés à deux ou trois roues, hors périmètre VTC.'},
    ]
    return data

FRENCH_CONTEXT = """Gros fail et design douteux… Elon Musk présente le « cybertruck » 100 % électrique de Tesla
BLADE RUNNER — Cet engin électrique est censé résister à toute attaque extérieure (mais n’a pas résisté pendant le show).

Lignes (très) épurées et inox mat pour le nouveau véhicule Tesla. Elon Musk a fait un bond dans le futur en présentant jeudi soir près de Los Angeles son étrange « cybertruck », moitié véhicule blindé, moitié avion furtif et 100 % électrique. Un show à l’américaine… qui ne s’est pas déroulé comme prévu.
Elon Musk avait prévenu : son véhicule aurait une allure « futuriste » et « cyberpunk » inspirée par Blade Runner, le film de science-fiction de Ridley Scott […]. « Il ne ressemble à rien d’autre », a résumé fièrement le PDG de Tesla sur scène, désignant son pick-up massif aux lignes angulaires lors d’un show dans le centre de design du constructeur à Hawthorne (Californie). Un design rapidement moqué sur les réseaux sociaux.

Résistant… mais pas trop
À défaut d’arborer un design élégant, le « cybertruck » affiche sur le papier des performances impressionnantes, abondamment vantées par Elon Musk avec des démonstrations impliquant des coups de masse, des jets de boules en acier, voire des tirs d’arme à feu, ceux-là enregistrés en vidéo pour raisons de sécurité.
« C’est littéralement résistant aux balles de pistolet calibre 9 mm », a-t-il assuré. « C’est un alliage en acier inoxydable ultrarésistant que nous avons développé. Nous allons utiliser le même alliage pour la fusée spatiale que pour le “cybertruck” », a lancé Elon Musk en référence à l’activité de SpaceX, dont il est aussi le fondateur et le PDG.
Problème : lors de l’essai de l’envoi d’une balle d’acier sur scène, la démonstration rate, et la vitre du prototype casse (sans toutefois exploser). Rires dans la salle, sourire gêné pour Elon Musk. « Oh my f**king God. Bon… Peut-être que c’était un peu trop violent. On va arranger ça en post-production », blague le milliardaire.

Moins de 50.000 dollars
Le futur pickup de Tesla aura six places, pourra emporter plus de 1,5 tonne et sera capable de tracter sept tonnes, a-t-il détaillé. Le « cybertruck » sera décliné en trois modèles, 39.900 dollars et 400 km d’autonomie pour l’entrée de gamme, jusqu’à 69.900 dollars et 800 km d’autonomie annoncée pour le modèle supérieur. Et il pourra passer de 0 à 100 km/h en environ trois secondes, s’est réjoui le fantasque patron de Tesla.
Elon Musk avait promis que son fameux pick-up coûterait moins de 50.000 dollars, un prix dans la moyenne pour cette catégorie de véhicule, et qu’il surpasserait les performances du Ford F-150, numéro un aux États-Unis sur ce segment depuis longtemps.
Certains experts estiment que le pick-up électrique de Tesla aura du mal à séduire la clientèle traditionnelle pour ce type d’engins. « Même si le pick-up de Tesla ne séduit pas les amateurs habituels du F-150, il n’en a pas forcément besoin », relevait Jessica Caldwell, directrice de la prospective pour le guide automobile Edmunds, dans une déclaration transmise à l’AFP avant la présentation. « Si le pick-up Tesla n’était pas un peu polémique, ça ne serait pas une Tesla », estime-t-elle.

Source reproduite dans l’annale : 20 Minutes, 22 novembre 2019, article sur la présentation du Cybertruck (adresse visible sur le document)."""

if __name__=='__main__':
    output=enrich(json.loads(Path(sys.argv[1]).read_text()))
    Path(sys.argv[2]).parent.mkdir(parents=True,exist_ok=True)
    Path(sys.argv[2]).write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
