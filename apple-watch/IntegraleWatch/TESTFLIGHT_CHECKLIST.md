# Mise en ligne TestFlight — Intégrale Watch 1.0

## Déjà prêt dans le dépôt

- App watchOS autonome, compatible Apple Watch Ultra 2 et watchOS 10 ou ultérieur.
- Bundle principal : `com.integraleacademy.IntegraleWatch`.
- Bundle Watch : `com.integraleacademy.IntegraleWatch.watchkitapp`.
- Extension : `com.integraleacademy.IntegraleWatch.watchkitapp.watchkitextension`.
- Widget : `com.integraleacademy.IntegraleWatch.watchkitapp.widget`.
- Version `1.0`, build `1`.
- Icônes complètes jusqu’au format Ultra 49 mm et icône marketing 1024 px sans transparence.
- Manifeste de confidentialité pour le stockage partagé app/complications.
- Déclaration d’utilisation du chiffrement exempté pour éviter le questionnaire à chaque build.
- Trois complications : CA du jour, CA du mois, objectif mensuel.
- Jumelage à usage unique, jeton stocké dans le trousseau et révocation depuis Gestion Stagiaires.
- Enregistrement du jeton APNs sans exposition dans l’administration.
- Compilation non signée et tests backend exécutés automatiquement dans GitHub Actions.

## À faire dès que l’organisation Apple est validée

1. Accepter le contrat Apple Developer Program et régler l’adhésion.
2. Dans Xcode, sélectionner l’équipe **INTEGRALE SECURITE FORMATIONS** sur les quatre cibles.
3. Créer ou laisser Xcode créer les quatre identifiants d’app ci-dessus.
4. Activer l’App Group `group.com.integraleacademy.IntegraleWatch` pour l’app, l’extension et le widget.
5. Activer Keychain Sharing avec `com.integraleacademy.IntegraleWatch.shared` pour l’extension et le widget.
6. Activer **Push Notifications** pour l’extension Watch.
7. Archiver la configuration Release puis envoyer le build dans App Store Connect.
8. Ajouter Clément comme testeur interne TestFlight et installer l’app sur l’Apple Watch Ultra 2.
9. Dans Gestion Stagiaires, ouvrir **Suivi des ventes → Apple Watch**, générer le code et jumeler la montre.

## Fiche TestFlight prête à copier

- **Nom** : Intégrale
- **Sous-titre** : Vos ventes au poignet
- **Description bêta** : Tableau de bord privé d’Intégrale Academy pour consulter le chiffre d’affaires, les ventes et les objectifs de Gestion Stagiaires depuis une Apple Watch.
- **Notes de test** : Jumeler la montre avec le code temporaire généré dans Gestion Stagiaires. Vérifier le CA du jour, le CA du mois, l’objectif mensuel, la liste des formations et les trois complications du cadran.
- **Compte requis** : aucun identifiant saisi sur la montre ; accès par code temporaire administrateur.
- **Données stagiaires** : aucune identité ni coordonnée n’est transmise à la montre.

## Activation des alertes de vente

Après création de la clé APNs dans le compte Apple, ajouter sur Render les paramètres APNs de l’organisation et activer l’émetteur serveur. La montre est déjà capable de demander l’autorisation, d’enregistrer son jeton et d’actualiser les complications à la réception d’une notification. Aucun secret APNs ne doit être ajouté au dépôt Git.
