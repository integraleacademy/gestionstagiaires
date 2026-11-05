# Régulation du connecteur EDOF — Test V2

Le navigateur et le fournisseur restent verrouillés pendant chaque tâche. Les
requêtes métier du navigateur et celles de son client HTTP partagent une cadence
persistante : un départ toutes les 1,5 seconde au minimum. Ce réglage interne ne
représente pas un quota annoncé par EDOF. Les fichiers statiques ne sont pas ralentis.

Un HTTP 429 conserve le délai `Retry-After` du portail. Sans délai exploitable,
la pause progressive existante s'applique. La cadence double après un 429, jusqu'à
6 secondes, puis revient à sa valeur initiale après une heure sans nouveau 429.
Une pause active est vérifiée avant chaque appel, y compris avant une écriture.
Une vérification locale ne renouvelle jamais la pause.

La synchronisation complète rend la connexion après deux pages (100 dossiers par
page lorsque le portail accepte ce format). Le planificateur donne le prochain
créneau aux propositions manuelles puis reprend la lecture. Le point de reprise
est chiffré, lié au compte, au fournisseur, à sa révision et à la demande de
synchronisation ; il expire après 30 minutes. Une tentative d'écriture invalide
les points antérieurs, pour éviter de reprendre un catalogue déplacé par une
modification. Les contrôles de total, de doublons et de périmètre restent actifs.
Aucune liste partielle n'est publiée ni considérée comme un rattrapage terminé.

Les demandes À traiter sont relues toutes les 120 secondes, y compris entre les
lots d'une longue synchronisation. Les lots réutilisent la session vérifiée ; la
liste complète fournit aussi les dossiers acceptés, sans deuxième parcours.
Les vérifications du dossier avant et après chaque écriture sont conservées.

Les logs `EDOF_TRAFFIC` donnent le mode de tâche, le nombre d'appels par opération,
le temps d'espacement cumulé et, en cas de 429, l'opération, la méthode, le délai
interprété et l'échéance. Aucun nom, identifiant de dossier, URL complète, en-tête
d'authentification ou contenu métier n'est journalisé. `EDOF_DAY` indique la page
et le nombre de dossiers récupérés. Les étapes intermédiaires des lots ne créent
pas de notifications dans l'historique des automatisations.

Le plafond de 4 codes EFP entre 7 h et 19 h (Europe/Paris) reste inchangé. Ces
mesures réduisent les rafales ; elles ne garantissent pas l'absence de limitation
du portail. Une proposition en erreur n'est jamais retransmise automatiquement.
