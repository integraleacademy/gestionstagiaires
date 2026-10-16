"""Authored pedagogical corrections of papers supplied without answer keys."""
import json
from pathlib import Path
BASE=Path(__file__).parent

def data(letter, rows):
 result=[]
 for line in rows.strip().splitlines():
  number,answer,ref,explanation,*note=line.split('|')
  result.append(dict(number=int(number),answers=list(answer) if answer!='-' else [],lesson_refs=ref.split(','),explanation=explanation,status='historical' if note else 'active',update_note=note[0] if note else '',sources=[]))
 (BASE/f'recent-{letter.lower()}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 return result

def save(letter,result):
 (BASE/f'recent-{letter.lower()}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')

def opts(*texts):return [dict(id=chr(97+i),text=t) for i,t in enumerate(texts)]
def source(title,url):return dict(title=title,url=url)

E=data('E','''
1|c|E.12|« Watch » convient pour suivre attentivement un match ; « look » s’emploie avec « at ». « See a game » peut aussi désigner le fait d’assister à un match.|Le contexte « take me to the stadium » permet aussi « see the game ». Sans corrigé fourni, cette question ne départage pas équitablement les choix B et C : elle est étudiée hors score.
2|c|E.02|Le client veut vérifier l’identité du chauffeur réservé. « If you are Mr Martin, yes I am your driver » confirme la réservation en vérifiant le nom. « Book » est ici le verbe réserver, pas le nom livre.
3|a|E.03|« How long » interroge une durée. « Planning to stay » signifie compter rester. « How often » interrogerait la fréquence et « how » seul la manière.
4|a|E.11|« To demand » signifie exiger. Pour demander poliment, utilisez plutôt « to ask » ou « could you…? ». C’est un faux ami : il ne faut pas traduire automatiquement demander par demand.
5|abc|E.04|Les trois phrases peuvent demander comment aller au cinéma ; « Can you tell me the way to…? » est une demande d’itinéraire particulièrement claire et polie.|Les choix se recouvrent : « how do you go » peut aussi porter sur le moyen de transport. Cette formulation ne permet pas de fixer un corrigé unique sans précision ; entraînement hors score.
6|c|E.05|« Handbag » désigne un sac à main. « Hand luggage » signifie bagage à main ; « suitcase » est une valise. Repérez le type d’objet plutôt que le seul mot hand.
7|a|E.06|« Fasten your seat belt » demande d’attacher sa ceinture. « Unfasten » signifie détacher et « sit on » s’asseoir sur. Ajoutez « please » pour une consigne courtoise.
8|b|E.11|« A flat tyre » est un pneu crevé ou dégonflé. « Wheel » est la roue complète et « tired » signifie fatigué. Exemple : « We have a flat tyre; I will stop somewhere safe. »
9|b|E.07|« Choose the route » signifie choisir l’itinéraire ou le parcours. La destination se demande avec « Where would you like to go? ». Ne confondez pas le lieu d’arrivée et le chemin emprunté.
10|b|E.04|« Where » demande un lieu : une adresse répond à la question. « I used to… » évoque une ancienne habitude et « I like… » une préférence, sans fournir la destination demandée.
11|b|E.03|« Twenty past ten » signifie 10 h 20 ; « twenty to ten » signifie 9 h 40. « Tomorrow morning » désigne demain matin. Vérifiez séparément jour, moment de la journée et heure.
12|a|E.03|« How many people » demande un nombre de personnes. « No more than 3 » signifie pas plus de trois. « Since » introduit un point de départ dans le temps, « on Monday » un jour.
13|c|E.06|« Safety » est la sécurité. Expliquez la raison professionnelle : « Please fasten your seat belt for your safety. » « Goodness » ne signifie pas sécurité et une règle personnelle ne répond pas à la raison demandée.
14|c|E.09|La traduction la plus précise est « J’ai laissé ma carte de crédit à l’hôtel. Pourrions-nous y retourner, s’il vous plaît ? ». « Go back » signifie retourner ; cela ne prescrit pas une manœuvre immédiate de demi-tour.|Plusieurs propositions reformulent une demande très voisine. Sans indication demandant la traduction la plus littérale et sans corrigé fourni, cette question est étudiée hors score.
15|a|E.07|« Rush hour » désigne l’heure de pointe ; au pluriel, « rush hours ». Pour prévenir d’un ralentissement : « It is rush hour; the journey may take longer. »
16|c|E.12|« Lots of » se construit avec des noms dénombrables au pluriel comme places. « Many places » conviendrait aussi, mais « a many » et « a much » sont incorrects.
17|b|E.11|À la station-service, « Fill it up, please » demande le plein. Pour remplir un formulaire on emploie « fill in » ou « fill out the form ». Le contexte permet de choisir le sens.
18|a|E.12|« Better than » est le comparatif de good : meilleur que. « In English » précise le domaine comparé. La phrase ne parle ni de voyages en Angleterre ni de fautes plus nombreuses.
19|c|E.09|« Don’t worry » rassure : ne vous inquiétez pas, pas de souci. « I can drive you there » signifie je peux vous y conduire. « Pas de quoi » répond plutôt à un remerciement.
20|b|E.07|« Buy » signifie acheter, « bye » au revoir et « by » par/près de. Après « need to », on emploie le verbe à sa base : « need to buy a map ».
''')
D=data('D','''
1|c|D.02|Le texte rapproche les gains de Jorge des revenus locaux : l’activité de moto-taxi lui procure un revenu plus important. L’essence bon marché constitue un élément de contexte, pas la réponse principale sur son changement de métier.
2|b|D.02|Le texte indique 250 bolivars en moyenne et le double les bons jours, notamment lorsque le métro tombe en panne. Calcul : 250 × 2 = 500. Les 800 bolivars correspondent au salaire minimum mentionné.
3|b|D.07|Un fléau est un grand mal ou une calamité. Parmi ces choix, catastrophe s’en rapproche. Bonheur et aubaine ont un sens positif ; bouleversement n’implique pas nécessairement un dommage.
4|c|D.07|Vrombir décrit un bruit grave, continu et puissant, comme celui d’un moteur. Rugir est le synonyme le plus proche proposé. Accélérer décrit une action de conduite, trembler un mouvement.
5|a|D.06|Une ambiance bon enfant est simple, détendue et conviviale. Le mot enfant ne doit pas être interprété littéralement comme infantile ou capricieux : il faut comprendre l’expression entière.
6|a|D.03,D.10|Le texte relie la hausse du nombre de motos au manque de pièces, puis au développement d’un trafic de motos volées et revendues en morceaux. Une bonne réponse restitue cette chaîne de causes et mentionne les violences associées.
7|c|D.02|L’auteur dit « dangereux et cher, certes, mais rapide ». L’avantage retenu est la rapidité. Le connecteur mais oppose cet avantage aux défauts précédents.
8|b|D.07|Une horde est ici un groupe nombreux, présenté comme agité. Ce terme ne désigne ni un modèle de moto ni nécessairement une association organisée.
9|a|D.07,D.10|Le titre emploie nuées, le premier paragraphe hordes et le deuxième troupeau. Pour une question demandant plusieurs mots du texte, recherchez chaque occurrence et contrôlez le nombre d’éléments attendu.
10|a|D.06,D.10|Vendre un service à la criée signifie l’annoncer à voix haute pour attirer les clients. Il ne s’agit pas ici de vendre aux enchères ni d’établir une réservation écrite.
''')
D[5]['options']=opts('La pénurie de pièces favorise un trafic de motos volées et démontées, accompagné de violences.','La hausse du nombre de motos favorise surtout des importations légales de pièces et réduit les vols.','Les prix de l’essence rendent impossible l’achat d’une moto.')
D[8]['options']=opts('Nuées, hordes et troupeau.','Nuées, carrefours et capitale.','Hordes, gardien et bandits.')
D[9]['options']=opts('Annoncer le service à voix haute pour attirer les clients.','Vendre uniquement au client qui propose le prix le plus élevé.','Informer les clients exclusivement par un panneau écrit.')
for i in (5,8,9):D[i]['original_answer']=D[i]['options'][0]['text']
save('D',D)
B=data('B','''
1|d|B.07,B.12|Dans l’ancien cadre simplifié du sujet, la réponse visée était le bénéfice, contrairement au micro-social assis sur les recettes encaissées. Il faut aujourd’hui distinguer le revenu fiscal de l’assiette sociale des indépendants.|Réforme applicable aux revenus 2025 : l’assiette sociale unifiée est calculée sur le revenu brut social avec un abattement de 26 %, selon ses règles propres. L’ancienne réponse « bénéfice réalisé » est insuffisante pour enseigner le calcul actuel.
2|a|B.05|Une charge fixe varie peu avec le nombre de courses à court terme, par exemple le loyer mensuel du véhicule. Une charge variable évolue avec l’activité, par exemple le carburant lié aux kilomètres. Une charge peut aussi comprendre une part fixe et une part variable.
3|b|B.01|L’entrepreneur individuel répond des dettes professionnelles dans le cadre du patrimoine professionnel. L’EI n’a pas de capital social limitant mécaniquement sa responsabilité.|Depuis 2022, les patrimoines professionnel et personnel sont en principe séparés, avec des exceptions prévues par les textes. L’option affirmant leur confusion est obsolète ; l’option B est trop générale sans préciser ce périmètre. Question étudiée hors score.
4|b|B.04|EBE signifie excédent brut d’exploitation. Il sert à apprécier la performance de l’exploitation avant notamment amortissements et éléments financiers. Ce n’est pas le solde du compte bancaire.
5|a|B.03,B.04|Dans les hypothèses scolaires données, l’annuité du véhicule est 20 000 ÷ 4 = 5 000 €, celle de l’ordinateur 600 ÷ 3 = 200 €, soit 5 200 €. On raisonne sur une année entière et sur les bases amortissables indiquées, hors particularités fiscales non précisées.
6|d|B.06|Pour un transport soumis à 10 % de TVA, le prix HT est 30 ÷ 1,10 = 27,27 €. La TVA vaut 30 − 27,27 = 2,73 €. Calculer 10 % du TTC donnerait à tort 3 €. Vérifiez le taux applicable avant d’utiliser la formule.
7|b|B.08|Pour un chèque émis et payable en France métropolitaine, la durée d’encaissement est un an et huit jours à compter de la date inscrite. Cette durée ne doit pas être confondue avec la disponibilité réelle de la provision ni avec la durée de conservation des justificatifs.
8|ac|B.03,B.04|L’amortissement réduit la valeur nette de l’immobilisation au bilan ; sa dotation constitue une charge du compte de résultat. À règles fiscales constantes, une charge déductible diminue le résultat imposable.|L’énoncé mélange bilan, bénéfice et impôt : le bénéfice relève du compte de résultat et l’impôt ne baisse pas systématiquement. Sans ces hypothèses, les réponses A et C ne constituent pas un corrigé universel ; question étudiée hors score.
9|a|B.02|Le caractère artisanal dépend de la nature de l’activité et de ses conditions d’exercice. Le seul chiffre d’affaires ou la localisation géographique ne suffit pas. Il faut ensuite vérifier les critères d’immatriculation applicables.
10|a|B.02|La transmission peut être réalisée à titre onéreux par une vente ou à titre gratuit par une donation. Le décès peut aussi conduire à une transmission successorale. Distinguez la transmission d’une activité de sa cessation sans repreneur.
11|a|B.07,B.12|Les prélèvements privés du dirigeant ne constituent pas la base du calcul social ; le chiffre d’affaires brut n’est pas non plus la réponse générale au régime réel.|L’option « totalité du bénéfice » correspond à une présentation ancienne simplifiée. La réforme de l’assiette sociale applicable aux revenus 2025 impose d’enseigner l’assiette unifiée et l’abattement de 26 % : question historique hors score.
12|d|B.07|Le versement fiscal libératoire est une option du régime micro, sous conditions, notamment de revenu fiscal de référence. Il ne s’applique ni automatiquement à toutes les micro-entreprises ni aux entreprises relevant du régime réel.
13|c|B.06|La TVA collectée est la TVA facturée au client sur les ventes/prestations imposables. Pour une prestation de services, l’exigibilité suit en principe l’encaissement, sauf option ou règle particulière. TVA nette à reverser = TVA collectée exigible − TVA déductible, sous réserve des règles applicables.
14|b|B.01|SASU signifie société par actions simplifiée unipersonnelle : une société avec un seul associé. La lettre U décrit le nombre d’associés, pas un régime fiscal ni une simplification automatique de toutes les obligations.
15|c|B.04,B.05|Le carburant consommé dans l’activité est une charge du compte de résultat. Les produits correspondent aux recettes de l’activité. Un solde bancaire, une dette ou un stock relève d’une autre lecture comptable.
16|c|B.06|Le transport de voyageurs soumis à TVA relève en principe du taux de 10 % en France métropolitaine. Distinguez le taux du service et la situation d’un exploitant en franchise en base, qui ne facture pas la TVA tant que les conditions sont réunies.
17|cd|B.11|Les factures émises et les factures de carburant justifient les ventes et les dépenses professionnelles. Elles font partie des pièces comptables à conserver. Le justificatif d’immatriculation est un document d’entreprise d’une autre nature ; la taxe d’habitation personnelle ne justifie pas une course ou un achat de carburant.
18|c|B.07|Le régime micro-entreprise relève de l’impôt sur le revenu, selon les règles de la catégorie concernée et les options autorisées. Il ne signifie pas absence d’impôt. Une option vers un autre cadre fiscal doit être distinguée du maintien dans le régime micro.
''')
B[1]['options']=opts('Une charge fixe dépend peu du volume de courses à court terme ; une charge variable évolue avec l’activité.','Une charge fixe est toujours payée comptant ; une charge variable est toujours payée à crédit.','Une charge fixe correspond à tout achat de véhicule ; une charge variable correspond à toutes les factures mensuelles.')
B[9]['options']=opts('La vente et la donation.','L’amortissement et la déclaration de TVA.','Le paiement d’un fournisseur et le retrait du dirigeant.')
for i in (1,9):B[i]['original_answer']=B[i]['options'][0]['text']
for i in (0,10):B[i]['sources']=[source('Réforme de l’assiette sociale · DGFiP','https://www.impots.gouv.fr/la-reforme-de-lassiette-sociale')]
B[2]['sources']=[source('Entrepreneur individuel · Service Public','https://entreprendre.service-public.fr/vosdroits/F37396')]
B[6]['sources']=[source('Paiement par chèque · Service Public','https://www.service-public.gouv.fr/particuliers/vosdroits/F2402')]
for i in (5,12,15):B[i]['sources']=[source('TVA des transports de voyageurs · BOFiP','https://bofip.impots.gouv.fr/bofip/477-PGP.html')]
B[11]['sources']=[source('Régime fiscal de la micro-entreprise · Service Public','https://entreprendre.service-public.gouv.fr/vosdroits/F23267')]
save('B',B)
C=data('C','''
1|a|C.05|Le panneau triangulaire à deux bosses signale un cassis ou dos-d’âne (A2a). Le ralentisseur de type dos-d’âne est représenté par une seule bosse. Observez le dessin, pas seulement la forme triangulaire de danger.
2|ac|C.05|En agglomération, dans une rue à double sens, l’arrêt et le stationnement s’effectuent normalement du côté droit dans le sens de marche. Le côté gauche ne devient pas autorisé parce que l’arrêt est bref ; respectez aussi les interdictions locales.
3|ac|C.11|Pour une voiture, les feux de position peuvent suffire en agglomération lorsque l’éclairage permet de voir distinctement à une distance suffisante. Les feux de croisement sont également possibles. On ne circule pas sans éclairage la nuit ; par visibilité insuffisante, appliquez les exigences adaptées.
4|c|C.03,C.12|Un véhicule contraint de circuler à une allure fortement réduite avertit les autres avec ses feux de détresse. Dans une file ininterrompue, cette obligation concerne le dernier véhicule. Allumer les feux de détresse n’autorise pas à circuler sur la bande d’arrêt d’urgence.
5|b|C.01|Un témoin rouge signale généralement une alerte majeure imposant une réaction immédiate adaptée : se mettre en sécurité et consulter la notice. Orange signale le plus souvent une anomalie ou une vigilance ; bleu et vert renseignent habituellement sur un équipement en service.
6|b|C.08|Le pictogramme rouge niveau 3 signifie de ne pas conduire. La reprise exige l’avis d’un médecin. Niveau 1 : lire la notice ; niveau 2 : demander l’avis d’un professionnel de santé. Ne décidez pas de reprendre uniquement parce que vous ne ressentez pas de somnolence.
7|a|C.12|La bande d’arrêt d’urgence sert aux situations d’urgence, notamment panne ou accident. Un appel téléphonique ou une pause de confort ne justifie pas de s’y arrêter. Recherchez un emplacement sécurisé et suivez les consignes de protection.
8|c|C.04|En agglomération, lorsque le croisement avec un véhicule de transport en commun est difficile, le conducteur de la voiture facilite son passage et s’arrête si nécessaire. Anticiper l’encombrement évite de bloquer les deux véhicules.
9|b|C.12,A.05|Après un accident matériel, transmettez rapidement le constat à l’assureur et respectez le délai de déclaration prévu par le contrat, qui ne peut en principe être inférieur à cinq jours ouvrés. Le sujet abrège cette précision en « 5 jours » : il ne s’agit pas de cinq jours calendaires.
10|c|C.06|Le permis B permet au maximum huit passagers, soit neuf places conducteur compris, dans les limites de la catégorie du véhicule. Le nombre inscrit sur la carte grise et les conditions propres à l’activité peuvent réduire la capacité réellement utilisable.
11|c|C.11|Les feux de brouillard arrière s’utilisent en cas de brouillard ou de chute de neige ; la pluie seule ne les justifie pas et leur forte lumière peut éblouir les conducteurs suiveurs. Ne confondez pas leurs règles avec celles des feux avant.
12|c|C.04|Sur une route de montagne ou à forte déclivité, le véhicule descendant facilite le passage au véhicule montant et s’arrête d’abord lorsque le croisement est difficile. Si une marche arrière devient nécessaire, les règles dépendent aussi de la catégorie des véhicules et de la position des refuges : la priorité ne doit pas être appliquée aveuglément.
13|a|C.11|Dans un tunnel, même éclairé, utilisez les feux de croisement. Les feux de route peuvent éblouir et les feux de brouillard ne remplacent pas l’éclairage adapté au tunnel.
14|a|A.03,C.05|Après une invalidation pour solde de points nul, le nouveau permis est probatoire avec six points. Ne confondez pas la récupération progressive des points et le droit de reprendre immédiatement une activité professionnelle soumise à conditions.
15|c|C.05|Pour plusieurs infractions commises simultanément, le retrait est plafonné à huit points. Un permis probatoire disposant de six points peut néanmoins perdre tout son solde. Le plafond ne signifie pas qu’un conducteur conserve forcément son droit de conduire.
16|b|C.12|Le constat décrit les circonstances, positions et dommages de l’accident. L’assureur s’appuie sur ces faits pour déterminer les responsabilités et appliquer les garanties. Le document n’est ni un devis de réparation ni une décision de sanction pénale.
17|ac|C.01|Contrôlez le niveau sur terrain plat, moteur arrêté et selon le délai indiqué dans la notice, généralement moteur froid ou après un temps de repos suffisant. Ne contrôlez pas un niveau d’huile avec le moteur allumé. Ne dépassez pas le repère maximal.
18|bd|C.12|Choisissez un emplacement stable et plat, immobilisez le véhicule et desserrez légèrement les écrous avant de lever au point prévu par le constructeur. Ne vous placez jamais sous un véhicule tenu uniquement par un cric ; sur un lieu dangereux, privilégiez l’assistance.
19|ac|C.03|La distance d’arrêt est la distance parcourue pendant le temps de réaction, plus la distance de freinage. L’ABS est un équipement, pas l’une de ces deux composantes. Plus la vitesse augmente, plus les distances nécessaires augmentent.
20|c|C.05|Les lignes temporaires de circulation sont généralement jaunes et priment sur les lignes blanches lorsqu’elles organisent temporairement la circulation.|L’énoncé dit seulement « marquage jaune ». Certaines marques jaunes sont permanentes, notamment des interdictions d’arrêt ou de stationnement. Sans image ni précision « lignes temporaires de circulation », on ne peut pas généraliser ; question hors score.
''')
C[2]['sources']=[source('Code de la route · R416-6','https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000006842262/')]
C[8]['sources']=[source('Déclaration des dégâts matériels · Service Public','https://www.service-public.gouv.fr/particuliers/vosdroits/F2152')]
C[13]['sources']=[source('Permis probatoire · Service Public','https://www.service-public.gouv.fr/particuliers/vosdroits/F2390')]
C[14]['sources']=[source('Retrait simultané de points · Service Public','https://www.service-public.gouv.fr/particuliers/vosdroits/F11863')]
C[15]['sources']=[source('Constat amiable · Service Public','https://www.service-public.gouv.fr/particuliers/vosdroits/F2149')]
save('C',C)
A=data('A','''
1|a|A.02,A.12|Les sections disciplinaires donnent un avis ; la décision administrative relève de l’autorité compétente. Il faut distinguer l’avertissement et le retrait temporaire ou définitif de la carte des sanctions pénales décidées par un tribunal.|L’énoncé attribue directement la décision à la commission, alors que son rôle est consultatif. L’adaptation clarifie cette distinction et reste hors score pour ne pas valider cette imprécision.
2|a|A.04,G.11|Pour une voiture VTC, le contrôle technique est annuel, avec les échéances propres à sa mise en service et à son affectation. Il ne faut pas appliquer la périodicité ordinaire de deux ans des voitures particulières utilisées à titre privé. Le sujet emploie aussi l’attestation d’entretien pour d’autres catégories du T3P.
3|a|A.02|La commission locale comprend des représentants de l’État, des professionnels, des collectivités et, le cas échéant, des usagers ou associations prévus par les textes. Les personnes qualifiées invitées au titre de D3120-31 n’ont pas voix délibérative. Les sections disciplinaires ont une composition spécifique paritaire État/profession.
4|cd|A.11|Les policiers et les gendarmes habilités peuvent effectuer les contrôles routiers. Un juge exerce une fonction juridictionnelle et un agent SNCF ne devient pas, du seul fait de cet emploi, un agent habilité au contrôle routier général du T3P.
5|ad|A.11|Le permis et les justificatifs d’aptitude professionnelle/médicale doivent être vérifiés dans le cadre approprié. Les documents du conducteur, de l’exploitant, du véhicule et de la réservation répondent à des obligations distinctes.|La question mélange les pièces à détenir, à présenter et leur forme ; elle ne précise pas le statut de l’exploitant. Le PDF ne fournit pas de corrigé. Les choix A/D ne sont pas présentés comme liste officielle exhaustive et la question est hors score.
6|cd|A.05|La RC circulation couvre les dommages causés par le véhicule dans le cadre assuré. La responsabilité civile professionnelle concerne les préjudices liés à l’exécution du service, sous réserve des garanties et exclusions. Un retard ou une erreur de parcours ne déclenche pas automatiquement une indemnisation.|Les choix C/D dépendent du contrat, d’une responsabilité et d’un préjudice établi. Un retard causé par un passager n’engage pas automatiquement le chauffeur. Sans hypothèses ni corrigé, cette question reste hors score.
7|-|A.05,A.12|L’activité doit être couverte par une responsabilité civile professionnelle adaptée et les attestations doivent être tenues à jour. Ne confondez pas défaut d’assurance, absence de carte et absence d’inscription au registre : les textes et sanctions diffèrent.|Le PDF ne fournit pas de corrigé et les montants proposés ne permettent pas d’établir une réponse actuelle fiable à cette qualification d’infraction. Ce montant historique n’est pas enseigné comme une sanction générale de l’absence de RCP.
8|c|A.04|La formation continue du conducteur doit être renouvelée tous les cinq ans et donne lieu à une attestation. Sa date doit être suivie séparément des autres échéances : permis, aptitude médicale, assurances et contrôle du véhicule.
9|-|G.03,G.11|Un véhicule électrique utilisé en VTC doit satisfaire les règles applicables à l’activité ; certaines exigences techniques comportent des dérogations pour les véhicules électriques et hybrides. Cela ne dispense ni des formalités du véhicule ni des contrôles requis.|La formulation « validé par » ne désigne aucune procédure précise. Le PDF sans corrigé ne permet pas de retenir une autorité pour une validation générale : question hors score, à clarifier avec le référentiel de la session.
10|ac|A.03|L’honorabilité s’apprécie au regard des condamnations incompatibles énumérées par le Code des transports, avec leurs conditions de peine et d’inscription au bulletin n° 2. L’abus de confiance et l’escroquerie font partie des infractions à examiner.|Le libellé omet les conditions légales de peine et d’inscription. Il ne faut pas enseigner qu’une condamnation quelconque entraîne automatiquement l’interdiction : étude hors score avec les conditions actuelles.
11|a|A.03,A.11|Pour identifier une carte professionnelle, contrôlez notamment le nom, le prénom, la photographie et le numéro de la carte, puis sa catégorie d’activité et ses dates. Une carte d’une autre activité ou expirée n’autorise pas la mission.
12|-|A.03,A.12|Dans le cadre historique du sujet, le questionnaire combine une peine principale et des peines complémentaires. Il faut toujours distinguer sanction maximale encourue, peine effectivement prononcée et mesure administrative.|La loi du 25 juin 2026 a modifié L3124-12 : les prestations sans la carte correspondant à l’activité sont désormais visées par trois ans d’emprisonnement et 45 000 € d’amende, avec les peines complémentaires prévues. Les anciens choix ne forment plus un corrigé actuel : hors score.
13|b|A.01,A.02|Le Code des transports contient le cadre sectoriel du transport public particulier de personnes. Il s’articule avec d’autres textes, notamment Code de la route, assurances et droit pénal. La question recherche le code organisant spécifiquement le T3P.
14|b|G.06|Le taxi bénéficie de la possibilité de prise en charge et d’attente de clientèle sur la voie publique dans le périmètre et les conditions de son autorisation. Le VTC et le VMDTR ne bénéficient pas du même droit de maraude. Une réservation ou une zone autorisée pour un client identifié se distingue de l’attente indifférenciée de clientèle.
15|a|A.03|Le contrôle d’honorabilité se réfère au bulletin n° 2 du casier judiciaire et aux condamnations incompatibles prévues par les textes. Il ne faut pas remplacer cette exigence par « casier entièrement vierge », ni confondre le B2 avec le B3 remis à un particulier.
''')
A[0]['options']=opts('Avis pouvant conduire l’autorité compétente à un avertissement ou au retrait temporaire ou définitif de la carte.','Condamnation pénale et peine de prison prononcées directement par la commission.','Modification du contrat d’assurance décidée par la commission.')
A[1]['options']=opts('Tous les ans pour le contrôle technique d’une voiture VTC.','Tous les deux ans, comme une voiture particulière à usage privé.','Uniquement lors de la revente du véhicule.')
A[2]['options']=opts('Les membres des collèges prévus par les textes ; les personnes qualifiées invitées n’ont pas voix délibérative.','Tous les invités, y compris les personnes qualifiées, ont toujours un droit de vote.','Seuls les professionnels votent, les représentants de l’État étant uniquement observateurs.')
A[10]['options']=opts('Nom, prénom, photographie et numéro de la carte.','Nom de l’exploitant, numéro SIREN, assurance professionnelle et liste des véhicules.','Numéro de réservation, horaires du client, contrat d’assurance et facture du véhicule.')
A[14]['options']=opts('Le bulletin n° 2 du casier judiciaire.','Le bulletin n° 3 présenté par le conducteur remplace systématiquement le B2.','Le relevé des points du permis de conduire.')
for i in (0,1,2,10,14):A[i]['original_answer']=A[i]['options'][0]['text']
for i in (0,2):A[i]['sources']=[source('Commissions locales T3P · Code des transports','https://www.legifrance.gouv.fr/codes/id/LEGISCTA000034084258')]
A[1]['sources']=[source('Contrôle technique des transports de personnes · Service Public','https://entreprendre.service-public.gouv.fr/vosdroits/F22299')]
A[11]['sources']=[source('Loi du 25 juin 2026 · article 28','https://www.legifrance.gouv.fr/jorf/id/JORFTEXT000054309429')]
for i in (7,9,10,13,14):A[i]['sources']=[source('Devenir chauffeur VTC · Service Public','https://entreprendre.service-public.gouv.fr/vosdroits/F31027')]
save('A',A)
