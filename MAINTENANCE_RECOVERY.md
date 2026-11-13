# Maintenance sur les anciens liens Render

La passerelle du domaine `www.integraleconnect.com` protège la première visite
pendant une panne du serveur d'application. Le domaine Render historique reste
attaché à ce serveur et ne passe pas par cette passerelle.

En production, les pages HTML complètes installent automatiquement le service
worker existant à la racine. Il conserve uniquement la page publique
`static/maintenance.html`, autonome avec ses images intégrées. Les notifications
push existantes restent disponibles ; l'installation du secours ne demande
aucune autorisation de notification.

Pour un navigateur déjà équipé, une navigation GET qui reçoit 502, 503 ou 504,
ou une erreur réseau, est retentée une seule fois après 400 ms. Si elle échoue
encore, le secours affiche « Connexion interrompue » avec un statut 503,
sans annoncer une mise à jour qui n'a pas été constatée. Les appels API,
formulaires POST, ressources statiques et sondes `/healthz` ne sont pas
interceptés. Aucune page utilisateur, réponse API ou donnée de session n'est
mise en cache. Après une première attente de 12 secondes, la page vérifie
`/healthz`, puis charge l'URL d'origine avec la session de l'utilisateur. Le
retour n'est autorisé que si le contenu HTML complet est disponible et n'est
pas lui-même une page de secours. Les paramètres et le fragment sont conservés.
Les vérifications échouées s'espacent jusqu'à 30 secondes, sans quitter l'écran.
Les cookies restent sur le même domaine ; les redirections externes sont refusées.

Un marqueur temporaire dans `sessionStorage` protège la tentative de retour.
Il ne contient qu'un horodatage, aucune URL ni donnée utilisateur. Une vraie
page chargée l'efface. Si la navigation retombe immédiatement sur le secours,
les rechargements automatiques s'arrêtent et le bouton « Réessayer » apparaît.
Si le navigateur refuse ce stockage, le retour est également manuel. Un ancien
marqueur de plus de deux minutes n'empêche pas une future nouvelle tentative.

## Limites

- Une première visite doit réussir pour installer le secours. Un nouveau
  navigateur arrivant pendant la panne sur l'ancien domaine peut encore voir
  l'erreur Render. Le domaine Intégrale Connect reste à privilégier pour les
  nouveaux liens.
- Le navigateur doit accepter les service workers et conserver son stockage.
- Les pages ou formulaires déjà ouverts ne sont jamais rechargés de force.
- Le secours ne remplace pas le traitement des erreurs de soumission POST.

## Mise à jour et validation

La page est une copie de l'`index.html` de la branche
`infra/int-connect-secours-502`, avec une balise de validation
`integrale-maintenance-page`. Lors d'un changement de design, synchroniser la
copie et augmenter la version `MAINTENANCE_CACHE` dans `static/sw.js`.

Le workflow `Maintenance anciens liens` teste l'insertion du script et une
vraie installation du service worker dans Chromium contre un serveur local :
502/503/504, erreur passagère, perte de réseau, serveur sain mais page en panne,
validation du HTML complet, arrêt après un retour raté, reprise manuelle,
stockage refusé, redirections, paramètres et fragment, conservation du cookie,
absence de rejeu POST et contenu du cache.

```sh
python -m pytest -q tests/test_maintenance_recovery.py
node tests/maintenance-recovery.test.cjs
```

Pour un Chromium déjà installé, définir `CHROMIUM_EXECUTABLE` pour le second
test. Les tests navigateur ne contactent jamais le service réel.
