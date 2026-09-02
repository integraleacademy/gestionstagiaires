# Intégrale Watch

Application Apple Watch autonome pour consulter les KPI agrégés de Gestion Stagiaires :

- chiffre d’affaires et ventes du jour ;
- chiffre d’affaires de la semaine ;
- objectif, progression et reste à vendre du mois ;
- chiffre d’affaires annuel ;
- ventes et chiffre d’affaires du mois par formation ;
- complications WidgetKit pour le cadran.

## Générer le projet Xcode

Pré-requis : macOS, Xcode et [XcodeGen](https://github.com/yonaskolb/XcodeGen).

```bash
cd apple-watch/IntegraleWatch
brew install xcodegen
xcodegen generate
open IntegraleWatch.xcodeproj
```

Dans Xcode, sélectionner l’équipe Apple Developer d’Intégrale Academy pour les quatre cibles. L’App Group `group.com.integraleacademy.IntegraleWatch` et le groupe Keychain `com.integraleacademy.IntegraleWatch.shared` doivent être autorisés par les profils de signature. Le jeton n’est jamais inclus dans le code source : il est créé après saisie du code temporaire affiché dans **Gestion Stagiaires → Suivi des ventes → Apple Watch**.

Le serveur ciblé par défaut est `https://gestionstagiaires-r5no.onrender.com`. La montre peut être révoquée à tout moment depuis la même page d’administration.

## Vérification sans signature

```bash
xcodebuild \
  -project IntegraleWatch.xcodeproj \
  -scheme IntegraleWatch \
  -sdk watchsimulator \
  -configuration Debug \
  CODE_SIGNING_ALLOWED=NO \
  build
```

La fréquence d’actualisation d’une complication reste décidée par watchOS. L’application tente une nouvelle lecture à chaque ouverture et WidgetKit demande une actualisation environ toutes les quinze minutes.

