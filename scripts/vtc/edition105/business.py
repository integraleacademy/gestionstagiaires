"""Business reasoning with explicitly fictional, internally consistent amounts."""
from .common import question as q, numbers, sorting, order, topic, money

INFO={
'B.01':('Choisir un cadre sans confondre les questions',
 'La forme juridique, le régime fiscal, le régime social et le régime de TVA répondent à des questions différentes. La micro-entreprise est un régime simplifié de l’entreprise individuelle, pas une société comparable à une SASU. Un choix doit tenir compte du projet : travail seul ou à plusieurs, niveau des frais, protection, financement et obligations de gestion. Une solution intéressante pour une personne ne l’est pas automatiquement pour une autre.',
 'Comparez des situations cohérentes. Dans une activité qui supporte un véhicule, du carburant, de l’assurance, de l’entretien et des commissions, regardez ce qui reste réellement après les sorties. Les cotisations ou le calcul fiscal d’un régime simplifié ne signifient pas que les dépenses ont disparu. Les seuils et taux légaux se vérifient au moment du choix avec les sources officielles et un interlocuteur compétent.',
 'Deux candidats prévoient le même chiffre d’affaires. L’un dispose d’un véhicule amorti et travaille en direct ; l’autre supporte une location élevée et des commissions. Leurs recettes identiques ne justifient pas une conclusion identique sur le régime à retenir.'),
'B.02':('Construire le dossier de démarrage',
 'La création administrative n’est qu’une étape de la mise en activité. Séparez les formalités de l’entreprise, l’inscription de l’exploitant, les conditions du conducteur et la mise en conformité du véhicule. Préparez aussi les procédures de devis, de réservation, de facturation et d’archivage. Chaque ligne du dossier doit avoir une preuve et un responsable de suivi.',
 'La trésorerie de départ finance les dépenses qui arrivent avant les premières recettes : acompte, équipement, assurance, charges fixes, communication et marge pour les imprévus. Distinguez les engagements irréversibles, les paiements différés et les réserves disponibles. Une prévision de chiffre d’affaires ne remplace pas de l’argent disponible le jour d’un prélèvement.',
 'Une entreprise a 4 000 € disponibles et 3 200 € de paiements de démarrage certains. Elle garde 800 € avant les recettes suivantes : ce solde ne permet pas d’ignorer les charges du mois à venir.'),
'B.03':('Lire une photographie de l’entreprise',
 'Le bilan présente la situation à une date. À l’actif figurent notamment les biens, les créances et la trésorerie. Au passif figurent les capitaux propres et les dettes qui financent cet ensemble. Un véhicule peut augmenter les moyens de l’entreprise alors qu’un emprunt augmente aussi son endettement. Posséder un actif ne signifie pas disposer de sa valeur en argent immédiatement utilisable.',
 'Les créances correspondent à des sommes dues par les clients : elles ne sont pas encore nécessairement sur le compte bancaire. La lecture utile rapproche donc les créances, leurs échéances et les dettes à payer. Les exercices qui suivent utilisent un bilan volontairement simplifié ; ils servent à comprendre l’équilibre et non à établir une comptabilité complète.',
 'Un véhicule vaut 25 000 €, les créances sont de 2 000 € et la banque de 3 000 €. L’actif total est 30 000 €. Avec 18 000 € de dettes, les capitaux propres représentent 12 000 € dans cet exemple simplifié.'),
'B.04':('Différencier le résultat et l’argent disponible',
 'Le résultat mesure la différence entre les produits et les charges d’une période. La trésorerie mesure l’argent disponible et ses mouvements. Une prestation facturée peut améliorer le résultat avant son paiement ; un emprunt peut augmenter le compte bancaire sans devenir un produit d’exploitation. Confondre ces deux lectures peut conduire à dépenser de l’argent nécessaire à une échéance.',
 'Avant de calculer, fixez la même période et la même base pour toutes les données. Ne mélangez pas une charge annuelle et une recette mensuelle, ni un montant HT et un TTC lorsque la TVA doit être traitée séparément. L’examen demande souvent une opération simple mais fondée sur une bonne sélection des données. Expliquez mentalement ce que représente chaque nombre avant d’utiliser la calculatrice.',
 'Sur le même mois, 6 200 € de produits et 4 650 € de charges donnent un résultat de 1 550 €. Si une partie des factures n’est pas encaissée, ce montant n’est pas forcément présent sur le compte.'),
'B.05':('Compter les coûts fixes et les kilomètres invisibles',
 'Les coûts fixes de l’exercice restent dus même si le véhicule roule moins : assurance, abonnements ou charges de structure selon le modèle. Les coûts variables évoluent avec l’activité, par exemple une consommation proportionnelle aux kilomètres. Certains coûts sont mixtes ou changent par palier ; la classification doit suivre les hypothèses du dossier.',
 'Le coût d’une mission ne se limite pas aux kilomètres avec le passager. Ajoutez l’approche, le déplacement vers la course suivante ou le retour lorsque votre analyse les attribue à la mission. Distinguez également le coût complet et la contribution : la recette diminuée des coûts variables sert encore à payer les coûts fixes. Une contribution positive n’est pas automatiquement un bénéfice net.',
 'Une course de 30 km nécessite 10 km d’approche et 20 km de retour. Avec une hypothèse de coût variable de 0,30 €/km, la dépense variable calculée est 60 × 0,30 = 18 €.'),
'B.06':('Passer du HT au TTC et revenir en arrière',
 'Pour appliquer un taux donné dans un exercice, transformez le pourcentage en nombre décimal. Le TTC vaut HT × (1 + taux). Le HT se retrouve en divisant le TTC par le même coefficient ; retirer simplement le taux du TTC donne une autre base et un résultat incorrect. La TVA correspond à la différence TTC − HT.',
 'Les exemples indiquent explicitement un taux pédagogique. Ils ne décident pas du régime réel de votre entreprise ni de la TVA applicable à une prestation composite. En situation professionnelle, il faut vérifier l’assujettissement, la franchise éventuelle, le droit à déduction et la nature de l’opération. On ne soustrait pas automatiquement toute taxe payée sur tout achat.',
 'Avec un taux donné de 10 %, 100 € HT donnent 110 € TTC et 10 € de taxe. Pour retrouver le HT de 110 €, le calcul est 110 ÷ 1,10 = 100, et non 110 − 11.'),
'B.07':('Ne pas confondre recettes et revenu disponible',
 'Dans le suivi d’un régime simplifié, identifiez les recettes à déclarer selon les règles applicables et la période. Un taux pédagogique permet de comprendre le mécanisme d’un prélèvement proportionnel, mais les taux et seuils réels dépendent du régime et doivent être vérifiés. Les charges supportées par le professionnel restent des sorties d’argent même lorsqu’elles ne sont pas déduites de la même manière dans le calcul fiscal.',
 'Construisez un tableau qui distingue les recettes, les commissions, les cotisations estimées, les frais du véhicule et les autres sorties. Une retenue prélevée par un intermédiaire ne permet pas de décider sans analyse que seule la somme versée sur votre compte constitue la bonne base déclarative. Le contrat et les règles du régime doivent être examinés.',
 'Pour un exercice utilisant une base de 4 000 € et un prélèvement hypothétique de 20 %, la réserve calculée est 800 €. Les 3 200 € restants doivent encore couvrir les dépenses indiquées dans le dossier.'),
'B.08':('Construire une trésorerie par date',
 'Commencez par le solde disponible, ajoutez les encaissements prévus à leur date et retirez les paiements à leur échéance. Le résultat d’un mois ne révèle pas toujours un creux au milieu du mois. Une facture payable le 30 ne finance pas automatiquement un prélèvement prévu le 10. Prévoyez donc une lecture hebdomadaire ou journalière pour les périodes tendues.',
 'Une réserve sert à absorber un écart : facture réglée plus tard, immobilisation du véhicule, réparation ou variation d’activité. Elle n’est pas identique à une ligne de crédit accordée, qui est un financement avec ses propres conditions. Dans les exercices, ne décalez pas une échéance à votre convenance : calculez d’abord l’écart puis identifiez la décision à prendre avant sa survenue.',
 'Le solde est 1 200 €. Un paiement de 1 500 € est prévu avant un encaissement de 900 €. La trésorerie passe temporairement à −300 €, même si elle remonte ensuite à 600 €.'),
'B.09':('Lire la marge avant le seuil de rentabilité',
 'Le seuil de rentabilité se calcule à partir des charges fixes et de la marge sur coûts variables. Avec un prix unitaire et un coût variable unitaires constants, la marge unitaire vaut prix − coût variable. Le nombre minimal de prestations doit couvrir les charges fixes ; lorsqu’il n’est pas entier, on arrondit au nombre supérieur. Un résultat arrondi vers le bas laisserait une partie des charges non couverte.',
 'Ce modèle suppose un niveau de prix, un coût variable et une capacité cohérents. Il ne suffit pas de calculer un nombre de courses si le planning ne permet pas de les réaliser. Il faut aussi analyser les approches, l’attente, les horaires et la demande. Une marge nulle ou négative ne permet pas de couvrir davantage de charges fixes en multipliant les mêmes prestations.',
 'Avec 900 € de charges fixes, un prix de 60 € et un coût variable de 24 €, la marge unitaire est 36 €. Le seuil simplifié est 900 ÷ 36 = 25 courses.'),
'B.10':('Comparer deux financements sur le même périmètre',
 'Un loyer mensuel plus faible n’est pas automatiquement une solution moins chère. Comparez la durée, l’apport, les paiements, les frais, les services inclus, les limites kilométriques, le prix final éventuel et les conditions de restitution. Un contrat peut aussi créer des contraintes d’usage ou d’entretien. Le coût total et la trésorerie mensuelle apportent deux informations complémentaires.',
 'Évitez de comparer 24 mois d’une offre avec 36 mois d’une autre comme si les services et la propriété finale étaient identiques. Les exercices précisent un périmètre simplifié : les calculs doivent respecter ces hypothèses. En pratique, le traitement fiscal, l’assurance, l’entretien et la valeur de revente doivent être examinés avec les documents contractuels.',
 'Dans un exemple limité aux paiements indiqués, un apport de 3 000 € et 36 mensualités de 450 € représentent 19 200 €. Un prix de rachat annoncé séparément s’ajoute si vous décidez de l’exercer.'),
'B.11':('Relier prestation, facture et encaissement',
 'Une facture décrit une opération et un montant dû. Elle ne prouve pas à elle seule que le paiement a été reçu. Le devis, la réservation, la prestation, la facture et le règlement correspondent à des étapes liées mais distinctes. Conservez les pièces de façon à pouvoir reconstituer cette chaîne en cas de question du client ou de contrôle.',
 'La cohérence porte sur l’identité des parties, la date, la nature du service, les montants, le traitement de la TVA et les mentions applicables. Une correction suit une procédure traçable ; on ne doit pas effacer discrètement une facture déjà émise pour faire disparaître une opération. Les exercices portent sur la lecture des documents, pas sur un modèle juridique complet prêt à l’emploi.',
 'Un transfert a été facturé 85 €. Le client paie 50 € puis 35 €. Le total réglé est 85 € et le reste dû est zéro, à condition que les deux règlements soient rapprochés de cette facture.'),
'B.12':('Mesurer le temps professionnel complet',
 'Le temps de travail d’une activité comprend plus que les minutes facturées : préparation, nettoyage, approches, retours, attente, administration et suivi client peuvent mobiliser le professionnel. Pour analyser un revenu horaire, choisissez un dénominateur cohérent. Diviser par les seules heures passager peut donner une image trompeuse de l’activité.',
 'Le planning doit aussi prévoir des marges, des pauses et les contraintes applicables au statut du conducteur. Les calculs pédagogiques qui suivent ne constituent pas une durée maximale légale. Ils servent à repérer les chevauchements et les temps oubliés. Une journée rentable sur le papier ne doit pas être organisée au détriment de la sécurité ou des obligations de repos.',
 'Six heures de transport, une heure d’approche, trente minutes de nettoyage et trente minutes de gestion représentent huit heures mobilisées. Avec 160 € de revenu de référence dans l’exercice, le ratio est 20 €/h, pas 26,67 €/h.'),
'F.01':('Choisir un segment sur des observations',
 'Un marché se décrit par des besoins : horaires, trajets, budget, fréquence, confort, bagages et contraintes d’accueil. Les voyageurs d’affaires, les touristes et les déplacements locaux ne sollicitent pas toujours le même service. Une observation de quelques demandes ne suffit pas à garantir un volume futur ; elle permet de formuler et tester une hypothèse.',
 'Comparez aussi le coût d’accès au segment : temps de prospection, stationnement, attentes, saisonnalité, commissions et capacité du véhicule. Le chiffre d’affaires potentiel doit être rapproché de la contribution réelle et des risques. Les exercices utilisent des données fictives pour apprendre à choisir les indicateurs et à éviter les conclusions excessives.',
 'Un hôtel demande dix transferts tôt le matin, alors que votre activité actuelle se termine tard. Le marché est intéressant, mais il faut vérifier la compatibilité du planning, des repos et des moyens avant de promettre la disponibilité.'),
'F.02':('Décrire une offre que le client peut comparer',
 'Une offre lisible précise le service, son périmètre, les conditions et les limites. Une formule « transfert premium » ne dit pas combien de voyageurs ou de bagages peuvent être transportés, quelle attente est incluse ni comment une modification sera traitée. Le client doit pouvoir comprendre ce qu’il achète et ce qui nécessitera un accord complémentaire.',
 'Mettez en avant des engagements observables : point de rendez-vous confirmé, véhicule propre, contact utile, facturation claire. Évitez les promesses absolues que vous ne maîtrisez pas, comme une arrivée garantie en toute circonstance. La qualité se prépare dans les procédures, pas uniquement dans le vocabulaire commercial.',
 'Une offre précise un transfert pour trois passagers et trois bagages selon la capacité du véhicule, le point de prise en charge, le prix convenu et les conditions d’attente. Le client peut la comparer sans deviner les inclusions.'),
'F.03':('Construire un prix à partir du coût réel',
 'Le prix soutenable tient compte des kilomètres et du temps réellement mobilisés, des coûts variables, d’une part des charges fixes et du revenu recherché. La commission d’un intermédiaire réduit la recette disponible. Une hausse du chiffre d’affaires accompagnée de trajets à vide et de fortes retenues ne garantit pas une meilleure rentabilité.',
 'Commencez par un coût estimé cohérent puis comparez plusieurs scénarios. Si une commission proportionnelle s’applique au prix, le prix nécessaire pour conserver une somme cible se calcule en divisant cette somme par le pourcentage restant. Ajouter simplement le taux au coût ne donne pas le même résultat. Les montants ci-dessous sont des hypothèses d’exercice, pas des tarifs recommandés.',
 'Pour conserver 80 € avant les autres dépenses avec une commission de 20 %, un prix de 100 € produit 80 €. Un prix de 96 € ne laisserait que 76,80 €.'),
'F.04':('Transformer le besoin en devis clair',
 'Un devis utile reprend le trajet, la date, les horaires, les voyageurs, les bagages, les inclusions, les conditions et la durée de validité lorsqu’elle s’applique. Les lignes doivent permettre de comprendre le total. Distinguez une remise du prix avant taxe, une réduction du TTC et un service retiré : les effets ne sont pas identiques.',
 'Lorsqu’un client modifie sa demande, identifiez ce qui change et obtenez l’accord sur la nouvelle proposition. Ne transformez pas un message vague en engagement précis à sa place. Les exercices font comparer des versions de devis afin de repérer le prix final, le périmètre et les ambiguïtés avant la confirmation.',
 'Deux transferts à 75 € donnent 150 €. Une remise contractuelle de 10 % sur ce total le ramène à 135 €. Un supplément d’attente convenu séparément s’ajoute uniquement dans les conditions prévues.'),
'F.05':('Lire la recette après intermédiaire',
 'Le chiffre affiché au client, la commission et le virement reçu ne représentent pas la même grandeur. Le relevé peut aussi inclure des ajustements ou des remboursements. Pour analyser une période, reconstituez le calcul et rapprochez les courses, les retenues et le virement. Une différence non expliquée appelle une vérification documentaire.',
 'La dépendance commerciale se mesure aussi autrement que par le montant des commissions : part de l’activité provenant d’un seul canal, conditions de suspension, délais de paiement et accès à la relation client. Les règles de chaque plateforme se lisent dans son contrat actualisé. Les exercices utilisent des taux fictifs et ne reproduisent pas une plateforme réelle.',
 'Pour 200 € de courses et une commission hypothétique de 20 %, la retenue est 40 € et la recette avant autres sorties est 160 €. Les kilomètres à vide restent à prendre en compte.'),
'F.06':('Prospecter avec une cible et une mesure',
 'Une prospection structurée définit les clients visés, le besoin auquel vous répondez, le canal approprié et l’étape suivante. Le taux de transformation dépend de son dénominateur : rendez-vous obtenus sur contacts, devis sur rendez-vous ou ventes sur devis sont trois ratios différents. Comparer des taux dont les bases diffèrent induit en erreur.',
 'Le nombre de messages envoyés ne mesure pas seul la qualité de la démarche. Observez les réponses utiles, le coût, le temps passé et la pertinence des demandes. Respectez les règles de prospection et les choix des personnes ; une relance utile n’est pas une répétition indiscriminée. Les exercices font choisir une action à partir de données limitées et explicites.',
 'Sur 40 contacts qualifiés, 10 rendez-vous sont obtenus et 4 contrats sont conclus. Le taux rendez-vous/contacts est 25 %, tandis que contrats/contacts vaut 10 %.'),
'F.07':('Préparer un partenariat exécutable',
 'Un partenariat hôtelier ou événementiel doit préciser les responsabilités : prise de réservation, transmission des informations, accueil, annulation, facturation et paiement. Un apport régulier de clients ne dispense pas des obligations du transporteur. La personne qui commande, celle qui voyage et celle qui règle peuvent être différentes ; le dossier doit permettre de les distinguer.',
 'Analysez le volume annoncé et les contraintes avant de vous engager : simultanéité des départs, amplitude, bagages, saisonnalité et capacité de remplacement. Un accord oral sur un prix ne suffit pas à résoudre tous les cas d’attente ou de modification. Les scénarios permettent d’identifier les points à formaliser sans demander au stagiaire de rédiger un contrat.',
 'Un hôtel commande pour un client et demande une facture à son nom. Le transporteur confirme qui est le cocontractant et quelles informations doivent figurer sur la réservation et la facture.'),
'F.08':('Communiquer avec des preuves et des engagements maîtrisés',
 'Une page ou une annonce doit expliquer le service proposé, les conditions et les moyens de contact. Les images et témoignages doivent être utilisés avec les autorisations nécessaires. Une photo de client ou un détail de trajet peut révéler des données personnelles. Une publication attractive n’autorise pas une promesse trompeuse.',
 'Mesurez une campagne avec un objectif défini : demandes pertinentes, devis acceptés ou clients acquis. Le nombre de vues peut être élevé sans aucune vente. Pour un calcul de coût d’acquisition, utilisez les dépenses et les nouveaux clients attribués dans l’exercice, en gardant à l’esprit les limites de l’attribution. Les montants proposés restent fictifs.',
 'Une campagne coûte 120 € et permet d’attribuer six nouveaux clients. Le coût d’acquisition calculé est 20 € par client ; il doit être comparé à la contribution générée, pas seulement au prix d’une course.'),
'F.09':('Fidéliser avec discrétion et consentement approprié',
 'La fidélisation commence par la qualité régulière : ponctualité préparée, information, propreté, réponse claire et traitement des difficultés. Retenir une préférence utile ne signifie pas constituer un dossier intime. Les usages de données pour le service et pour la prospection se distinguent ; il faut respecter le cadre applicable et les choix du client.',
 'Pour évaluer la fidélisation, définissez la population suivie et la période. Un taux de retour calculé sur des nouveaux clients ne se compare pas directement à un taux portant sur toute la base. Identifiez aussi les contraintes saisonnières. Les exercices demandent de tirer une conclusion mesurée, sans transformer une petite variation en preuve de causalité.',
 'Sur 50 nouveaux clients du trimestre, 15 réservent de nouveau dans la période observée. Le taux de retour défini par cet exercice est 30 %. Il ne décrit pas automatiquement toute la satisfaction de la clientèle.'),
'F.10':('Mesurer la qualité sans confondre les indicateurs',
 'La ponctualité, les réclamations, la satisfaction et la fidélisation éclairent des aspects différents. Un indicateur doit avoir une définition stable : arrivée au point convenu, retard supérieur à un seuil annoncé ou réclamation reçue dans une période. Sans définition, deux chiffres identiques peuvent décrire des situations différentes.',
 'Une moyenne masque parfois les cas les plus difficiles. Lisez aussi la distribution et les causes : une faible proportion de retards peut concentrer de lourdes conséquences pour certains clients. Une amélioration suppose une action concrète, par exemple vérifier les rendez-vous ou ajouter une marge de préparation, puis mesurer de nouveau avec la même méthode.',
 'Sur 80 prises en charge, 76 respectent le critère de ponctualité du tableau. Le taux vaut 95 %. Il reste à analyser les quatre écarts et leurs causes.'),
'F.11':('Traiter une réclamation en quatre temps',
 'Accueillez la demande, reformulez le problème, vérifiez les faits et proposez une réponse dans votre périmètre. Un client mécontent ne doit pas être accusé avant l’examen du dossier. À l’inverse, une excuse courtoise ne vous oblige pas à promettre une indemnisation que vous n’êtes pas autorisé à décider. Séparez l’écoute, l’enquête et la solution.',
 'La réponse doit être suivie : qui rappelle, dans quel délai annoncé et sur quel canal ? Un geste commercial peut être pertinent, mais il ne corrige pas une cause répétée. Conservez les informations nécessaires au traitement sans publier l’identité ou les détails du client. Les cas permettent de choisir une réponse et une action d’amélioration.',
 'Le client conteste une attente facturée. Le gestionnaire rapproche le devis, les horaires et les échanges, explique ce qui a été convenu et corrige une erreur éventuelle de manière traçable.'),
'F.12':('Lire un tableau de bord pour décider',
 'Un tableau de bord utile réunit peu d’indicateurs définis : recettes, contribution, kilomètres totaux et facturés, temps mobilisé, délais de règlement et incidents. Il doit permettre une décision, pas seulement afficher des chiffres. Pour comparer deux périodes, vérifiez le nombre de jours, le périmètre et les événements particuliers.',
 'Un chiffre d’affaires supérieur peut aller avec une contribution plus faible si les commissions, les approches ou les coûts augmentent. Un taux d’occupation se calcule sur une base précisée : kilomètres ou temps. Les exercices entraînent à choisir l’indicateur pertinent et à formuler mentalement une conclusion limitée à ce que les données montrent.',
 'Deux semaines produisent le même chiffre d’affaires. La seconde nécessite davantage de kilomètres à vide : la recette seule ne suffit pas à conclure que les performances sont équivalentes.'),
}

def build():
    topics={};practices={}
    for ref,(title,p1,p2,example) in INFO.items():
        topics[ref]=topic(title,[p1,p2],example,
          ['Identifier la question, la période et l’unité attendue.','Sélectionner les données comparables et effectuer le calcul ou la vérification.','Contrôler le résultat et dire ce qu’il permet réellement de conclure.'],
          'Un résultat chiffré correct peut répondre à la mauvaise question si la base, la période ou le périmètre est mal choisi.')
        practices[ref]=[]
    add=lambda ref,ex:practices[ref].append(ex)
    for n in range(8):
        price=50+10*n;km=30+5*n;rate=.30;commission=20;cost=km*rate;net=price*.8;contribution=net-cost
        doc=[{'title':f'Fiche économique {n+1} · hypothèses','rows':[['Prix vendu',money(price)],['Commission contractuelle fictive','20 % du prix'],['Distance totale',f'{km} km'],['Coût variable donné','0,30 €/km']]}]
        context=f'Dossier {n+1}. Tous les montants du calcul sont sur la même base pédagogique. Approche, course et retour représentent {km} km. Le prix est {price} € et la commission hypothétique de 20 %. Aucun autre poste n’est déduit dans cette question.'
        for ref in ['B.05','F.03','F.05','F.12']:
            add(ref,numbers(ref,context,'Quelle recette reste après la commission ?',net,price*.2,price*1.2,
                f'Commission = {price} × 20 % = {money(price*.2)} ; recette après commission = {money(net)}. Ce n’est pas encore le bénéfice.',documents=doc))
            add(ref,numbers(ref,context,'Quelle contribution reste après la commission et le coût variable indiqué ?',contribution,net,price-cost,
                f'{money(price)} − {money(price*.2)} − ({km} × 0,30 €) = {money(contribution)}. Les charges fixes restent à couvrir.',documents=doc,
                calculator={'price':price,'km':km,'commission':20,'cost_km':.30} if n==0 else None))
        product=4000+n*500;charges=2800+n*300;result=product-charges;paid=product-600
        context=f'Mois fictif {n+1} : produits {product} €, charges {charges} €, dont toutes les charges sont réglées. Les clients ont versé {paid} € ; 600 € restent à encaisser. Solde initial : 1 000 €. Les bases sont homogènes, hors traitement de TVA dans cet exercice.'
        add('B.04',numbers('B.04',context,'Quel est le résultat de la période ?',result,paid-charges,result+1000,
             f'Le résultat utilise produits − charges : {product} − {charges} = {result} €. Le solde initial n’est pas un produit.'))
        add('B.04',numbers('B.04',context,'Quel est le solde final de trésorerie simplifié ?',1000+paid-charges,1000+result,result,
             f'La trésorerie suit les flux : 1 000 + {paid} − {charges} = {1000+paid-charges} €. Les 600 € non encaissés ne sont pas disponibles.'))
        asset=20000+2000*n;debt=12000+1000*n;cash=2000+n*100;receivables=1500+n*100;total=asset+cash+receivables
        context=f'Bilan simplifié au dernier jour du mois : véhicule {asset} €, banque {cash} €, créances clients {receivables} €, dettes {debt} €. Aucun autre poste dans ce dossier.'
        add('B.03',numbers('B.03',context,'Quel est le total de l’actif ?',total,asset+cash,total+debt,f'Actif = véhicule + banque + créances = {asset} + {cash} + {receivables} = {total} €.'))
        add('B.03',numbers('B.03',context,'Quels sont les capitaux propres dans ce bilan simplifié ?',total-debt,total+debt,cash,
           f'L’équilibre donne capitaux propres = actif − dettes = {total} − {debt} = {total-debt} €.'))
        ht=60+n*20;t=.10 if n%2==0 else .20;ttc=round(ht*(1+t),2);tax=round(ttc-ht,2)
        context=f'Exercice de mécanisme de TVA {n+1}. Taux imposé pour le calcul : {round(t*100)} %. Ce taux pédagogique ne décide pas du régime réel de l’entreprise. Base HT : {ht} € ; TTC indiqué sur une deuxième ligne : {ttc:.2f} €.'
        add('B.06',numbers('B.06',context,'Quel montant de TVA correspond à cette base HT ?',tax,ttc*t,ttc,
          f'TVA = {ht} × {t:.2f} = {money(tax)}. Appliquer le taux au TTC utiliserait une base différente.'))
        add('B.06',numbers('B.06',context,'En repartant du TTC indiqué, quel montant HT retrouve-t-on ?',ht,ttc*(1-t),ttc+tax,
          f'HT = {ttc:.2f} ÷ {1+t:.2f} = {money(ht)}. On divise par le coefficient de passage.'))
        receipts=2500+n*500;social=20;fees=700+n*80;reserve=receipts*.2;available=receipts-reserve-fees
        context=f'Simulation de réserve, sans valeur de taux légal : base pédagogique {receipts} €, prélèvement hypothétique 20 %, autres frais payés {fees} €. Tous les montants et postes sont donnés ; aucune autre déduction dans ce calcul.'
        add('B.07',numbers('B.07',context,'Quelle réserve correspond au prélèvement hypothétique ?',reserve,receipts*.8,fees,
          f'La réserve vaut {receipts} × 0,20 = {money(reserve)}. Le taux réel doit être vérifié selon le régime.'))
        add('B.07',numbers('B.07',context,'Que reste-t-il après cette réserve et les frais indiqués ?',available,receipts-reserve,receipts-fees,
          f'{receipts} − {money(reserve)} − {fees} = {money(available)}. Le calcul se limite aux postes du dossier.'))
        initial=1000+n*100;out=initial+300;inflow=900+n*50;final=initial-out+inflow
        context=f'Prévision fictive {n+1} : solde au 1er = {initial} € ; paiement le 5 = {out} € ; encaissement le 20 = {inflow} €. Aucun autre mouvement.'
        add('B.08',numbers('B.08',context,'Quel est le solde juste après le paiement du 5 ?',-300,final,initial+inflow,
          f'Le 5, l’encaissement du 20 n’est pas encore disponible : {initial} − {out} = −300 €.'))
        add('B.08',numbers('B.08',context,'Quel est le solde après l’encaissement du 20 ?',final,-300,initial+inflow,
          f'{initial} − {out} + {inflow} = {final} €. Un solde final positif n’efface pas le creux antérieur.'))
        fixed=800+n*100;price2=60+n*5;variable=20+n*2;margin=price2-variable
        import math
        count=math.ceil(fixed/margin)
        context=f'Modèle simplifié {n+1} : charges fixes {fixed} € par mois, prix uniforme {price2} € par course, coût variable {variable} € par course. Capacité suffisante supposée pour ce calcul.'
        add('B.09',numbers('B.09',context,'Quelle marge unitaire contribue aux charges fixes ?',margin,price2+variable,variable,
          f'Marge unitaire = {price2} − {variable} = {margin} €.'))
        add('B.09',numbers('B.09',context,'Combien de courses entières faut-il au minimum pour couvrir ces charges fixes ?',count,count-1,count+10,
          f'{fixed} ÷ {margin} = {fixed/margin:.2f} ; on retient {count} courses entières en arrondissant au supérieur si nécessaire.',unit=' courses'))
        down=2000+n*250;monthly=350+n*20;duration=36;buy=3000+n*100;total=down+monthly*duration+buy
        context=f'Offre fictive {n+1} : apport {down} €, 36 loyers de {monthly} €, option finale {buy} €. Frais, assurance et entretien exclus des chiffres. On suppose l’exercice de l’option.'
        add('B.10',numbers('B.10',context,'Quel total de paiements est indiqué avec l’option finale ?',total,monthly*36,down+monthly*36,
          f'Apport + loyers + option = {down} + 36 × {monthly} + {buy} = {total} €. Ce total ne comprend pas les postes exclus.'))
        add('B.10',q('B.10',context,'Quelle limite doit accompagner la comparaison ?','Les postes exclus et les conditions d’usage restent à examiner','Le loyer mensuel prouve le coût complet','L’option finale doit toujours être oubliée','Il faut comparer le même périmètre et tenir compte des contraintes du contrat.'))
        bill=80+n*10;first=30+n*5;balance=bill-first
        context=f'Facture fictive de {bill} € pour une prestation réalisée ; paiement partiel reçu {first} € ; aucun avoir et aucun autre règlement.'
        add('B.11',numbers('B.11',context,'Quel reste dû doit être rapproché de la facture ?',balance,bill,bill+first,f'Reste dû = {bill} − {first} = {balance} €. Une facture émise ne signifie pas automatiquement paiement complet.'))
        add('B.11',q('B.11',context,'Quelle pièce établit le paiement reçu ?','La preuve du règlement rapprochée de la facture','Le seul devis accepté','Le nom du conducteur dans le planning','Le devis, la facture et le règlement ont des fonctions distinctes.'))
        productive=240+15*n;approach=60;clean=30;admin=30;totalmin=productive+approach+clean+admin;revenue=180+10*n
        context=f'Journée fictive : {productive} min de courses, 60 min d’approches, 30 min de nettoyage et 30 min de gestion. Montant de référence à rapporter au temps : {revenue} €. Les pauses et le cadre légal se traitent séparément.'
        add('B.12',numbers('B.12',context,'Combien de minutes sont mobilisées dans le périmètre indiqué ?',totalmin,productive,productive+60,f'{productive} + 60 + 30 + 30 = {totalmin} minutes. Les temps non facturés font partie du périmètre.',unit=' min'))
        ratio=round(revenue/(totalmin/60),2)
        add('B.12',numbers('B.12',context,'Quel ratio horaire correspond à tous ces temps ?',ratio,round(revenue/(productive/60),2),revenue,
          f'Temps total = {totalmin/60:.2f} h ; ratio = {revenue} ÷ {totalmin/60:.2f} = {ratio:.2f} €/h.',unit=' €/h'))
        contacts=40+n*10;appointments=10+n*2;clients=4+n
        context=f'Campagne fictive {n+1} : {contacts} contacts ciblés, {appointments} rendez-vous, {clients} nouveaux clients, dépense {120+n*30} €.'
        add('F.06',numbers('F.06',context,'Quel est le taux rendez-vous / contacts ?',appointments/contacts*100,clients/contacts*100,clients/appointments*100,
          f'Le dénominateur demandé est le nombre de contacts : {appointments} ÷ {contacts} × 100 = {appointments/contacts*100:.2f} %. ',unit=' %'))
        add('F.08',numbers('F.08',context,'Quel coût d’acquisition par nouveau client attribué à la campagne obtient-on ?',(120+n*30)/clients,(120+n*30)/contacts,120+n*30,
          f'Dépense ÷ clients attribués = {120+n*30} ÷ {clients} = {(120+n*30)/clients:.2f} € par client.'))
        totalclients=50+n*10;returns=15+2*n
        context=f'Cohorte fictive : {totalclients} nouveaux clients suivis sur la même période ; {returns} réservent de nouveau pendant cette période.'
        add('F.09',numbers('F.09',context,'Quel est le taux de retour ainsi défini ?',returns/totalclients*100,100-returns/totalclients*100,100,
          f'{returns} ÷ {totalclients} × 100 = {returns/totalclients*100:.2f} %. Ce taux ne prouve pas à lui seul la cause du retour.',unit=' %'))
        rides=80+10*n;late=4+n;ontime=rides-late
        context=f'Tableau fictif : {rides} prises en charge, dont {late} dépassent le seuil de retard défini dans cet exercice. Toutes les autres sont à l’heure selon ce même critère.'
        add('F.10',numbers('F.10',context,'Quel est le taux de ponctualité ?',ontime/rides*100,late/rides*100,100,
          f'Prises en charge ponctuelles = {rides} − {late} = {ontime}. Taux = {ontime} ÷ {rides} × 100 = {ontime/rides*100:.2f} %. ',unit=' %'))
        quote=150+n*20;discount=.1;waiting=15+5*n;final=quote*.9+waiting
        context=f'Devis fictif accepté : total initial {quote} €, remise de 10 % sur ce seul total, attente supplémentaire convenue de {waiting} € sans remise. Tous les chiffres sont sur une même base.'
        add('F.04',numbers('F.04',context,'Quel total résulte des conditions indiquées ?',final,(quote+waiting)*.9,quote+waiting,
          f'On applique la remise sur la base convenue : {quote} × 0,90 + {waiting} = {final:.2f} €.'))
    qualitative={
      'B.01':[
       ('Deux candidats ont le même chiffre d’affaires mais des frais très différents.','Quelle analyse manque avant de choisir ?','Le niveau réel des charges et le projet de chacun','Uniquement le chiffre d’affaires identique','La couleur de leur logo','La forme et le régime se choisissent en tenant compte de plusieurs paramètres.'),
       ('Une fiche compare « micro-entreprise » et « SASU ».','Quelle distinction est essentielle ?','Un régime simplifié et une forme de société ne sont pas de même nature','Ce sont deux véhicules commerciaux','Les obligations sont toujours identiques','Il faut séparer forme juridique, fiscalité, cotisations et TVA.'),
       ('Un candidat pense que des frais non déduits dans un calcul fiscal ne coûtent rien.','Que faut-il rectifier ?','Les dépenses restent des sorties de trésorerie','Le carburant devient gratuit','Le loyer du véhicule est annulé','Le traitement fiscal ne supprime pas la dépense réelle.'),
       ('Un ancien tableau donne un seuil sans date.','Quelle précaution prendre ?','Vérifier la règle actuelle et son périmètre','L’appliquer définitivement','Utiliser la moyenne de seuils trouvés sur les réseaux','Les taux et seuils peuvent évoluer.')],
      'B.02':[
       ('La création de l’entreprise est enregistrée, mais le véhicule et l’assurance ne sont pas prêts.','Peut-on considérer tout le démarrage achevé ?','Non, les autres volets restent à préparer','Oui, l’immatriculation remplace tous les documents','Oui, si un client a versé un acompte','La création ne prouve pas seule que la prestation peut commencer.'),
       ('Le premier client paiera dans un mois et l’assurance doit être réglée demain.','Quelle ressource compter pour demain ?','La trésorerie effectivement disponible ou le financement confirmé','Le seul chiffre d’affaires prévisionnel','La valeur d’un devis non accepté','Une échéance se finance avec une ressource disponible à temps.'),
       ('Une pièce manque dans un dossier.','Quel suivi est utile ?','Nommer l’action, le responsable et la date de vérification','La marquer comme traitée sans preuve','Attendre sans échéance','Un suivi opérationnel doit conduire à la résolution concrète.')],
      'F.01':[
       ('L’hôtel demande dix départs très matinaux et votre chauffeur finit habituellement tard.','Que vérifier avant d’accepter ?','Les moyens et la compatibilité du planning et des repos','Seulement le prix unitaire','Le nombre d’étoiles suffit','Un volume commercial doit être réalisable dans des conditions sûres.'),
       ('Trois clients interrogés souhaitent un même service.','Que peut-on raisonnablement conclure ?','Une piste à tester, sans garantie de volume','Tout le marché achètera ce service','La rentabilité est déjà assurée','Un petit échantillon oriente une hypothèse, pas une certitude.'),
       ('Un segment paie davantage mais nécessite beaucoup d’attente.','Quel indicateur ajouter ?','Le temps mobilisé et la contribution','Uniquement le prix par course','La couleur du véhicule','Le prix doit être rapproché du coût et du temps réel.')],
      'F.02':[
       ('Une annonce promet « luxe, rapidité, meilleur prix » sans périmètre.','Quel ajout aidera réellement le client ?','Le service inclus, la capacité et les conditions','Des superlatifs supplémentaires','Une promesse d’arrivée en toute circonstance','La clarté porte sur des caractéristiques et engagements vérifiables.'),
       ('Le devis concerne trois passagers ; cinq se présentent.','Quelle limite doit être réexaminée ?','La capacité et l’accord sur la prestation','Seulement la musique','Le prix seul règle la capacité','L’offre doit rester matériellement réalisable et sûre.'),
       ('Le trafic peut être imprévisible.','Quelle formulation commerciale est maîtrisée ?','Un horaire préparé avec une marge et une information en cas d’aléa','Aucun retard possible quelles que soient les conditions','Arrivée garantie même si la route ferme','On ne doit pas promettre de maîtriser un aléa extérieur absolu.')],
      'F.07':[
       ('Un hôtel réserve, le client voyage et une entreprise doit régler.','Que préciser ?','Les rôles, la facturation et les conditions de paiement','Seulement le prénom du chauffeur','Supposer que le passager paiera forcément','Réservant, voyageur et payeur peuvent être différents.'),
       ('Dix départs simultanés sont demandés et trois véhicules sont disponibles.','Quelle réponse est professionnelle ?','Vérifier les moyens et proposer une organisation réalisable','Accepter tous les départs sans solution','Faire monter tous les clients dans trois véhicules au-delà de la capacité','La capacité réelle doit être cohérente avec l’engagement.'),
       ('Le partenaire prévoit des annulations de dernière minute.','Que formaliser avant le service ?','Le traitement des annulations et de l’attente','Uniquement la couleur du document','Rien tant que la relation est cordiale','Les cas prévisibles doivent être clarifiés avant qu’ils ne créent un conflit.')],
      'F.11':[
       ('Un client conteste vingt minutes d’attente facturées.','Quelle première vérification faire ?','Rapprocher les conditions acceptées et les horaires constatés','Le menacer immédiatement','Effacer la facture sans trace','Les faits et les conditions convenues permettent d’examiner la demande.'),
       ('Une erreur de l’entreprise est confirmée.','Quelle réponse convient ?','Corriger de manière traçable et informer le client','Nier malgré les éléments','Créer une nouvelle erreur pour compenser','La résolution doit être compréhensible et suivie.'),
       ('La même cause de réclamation revient plusieurs fois.','Que faire au-delà d’un geste commercial ?','Corriger la procédure qui produit l’erreur','Changer seulement le nom du dossier','Ignorer les réclamations suivantes','Une amélioration durable traite la cause et mesure son effet.'),
       ('Le dossier exige une décision que le chauffeur ne peut pas prendre.','Que promettre ?','Un traitement par le bon interlocuteur et un délai de retour réaliste','Un remboursement certain sans habilitation','Une absence totale de réponse','L’engagement doit rester dans le périmètre de décision disponible.')]
    }
    for ref,rows in qualitative.items():
        practices[ref].extend(q(ref,*row) for row in rows)
    for ref in practices:
        practices[ref].append(order(ref,'Organisez la résolution d’un dossier de gestion ou d’une décision commerciale à partir des éléments fournis.',[
         'Définir précisément la question et le périmètre.','Rassembler les informations utiles et comparables.','Effectuer le calcul ou choisir l’action justifiée.','Vérifier le résultat et organiser son suivi.']))
    return topics,practices
