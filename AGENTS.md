# AGENTS.md — E-commerce Backend

## 1. Présentation du projet

Ce dépôt contient le backend d'une plateforme e-commerce multi-entreprises développée avec Django et Django REST Framework.

Technologies principales :

- Python 3.
- Django 5.2.
- Django REST Framework.
- PostgreSQL.
- Authentification OAuth 2.0 / OpenID Connect via Carri Account.
- JWT, HMAC et mécanismes de sécurité associés.
- Cloudinary pour les images et vidéos.
- API REST consommée principalement par un frontend Next.js.

Répertoires :

Backend :
`/home/mubaraka/Documents/Entreprise/ecommerce`

Application Django :
`/home/mubaraka/Documents/Entreprise/ecommerce/backend`

Frontend associé :
`/home/mubaraka/Documents/Entreprise/ecomfront`

Carri Account est un service d'authentification indépendant.

L'agent doit préserver l'architecture existante et ne jamais modifier un projet externe sans demande explicite.

---

## 2. Principes généraux

Avant toute intervention :

1. Lire les fichiers concernés.
2. Identifier les modèles, serializers, vues, services, permissions et routes impliqués.
3. Comprendre les règles métier existantes.
4. Examiner les tests correspondants.
5. Vérifier les dépendances entre applications Django.
6. Évaluer les impacts sur les API consommées par Next.js.

Ne pas supposer qu'un modèle, endpoint ou champ existe sans l'avoir vérifié.

Ne pas introduire de logique métier dupliquée.

Ne pas réécrire inutilement du code fonctionnel.

Privilégier des modifications minimales, maintenables et testables.

Préserver les modifications préexistantes du dépôt.

Ne pas effectuer de refactorisation hors périmètre sans justification.

---

## 3. Architecture Django

Respecter l'organisation existante du projet.

Séparer correctement les responsabilités :

- `models.py` : modèles de données et invariants.
- `serializers.py` : validation, sérialisation et désérialisation.
- `views.py` : orchestration HTTP et contrôle d'accès.
- `services.py` : logique métier complexe et réutilisable.
- `permissions.py` : autorisations.
- `selectors.py` : accès aux données, lorsque cette convention existe.
- `urls.py` : routage.
- `tests/` : tests automatisés.

Cette organisation est indicative : respecter les modules et conventions réellement présents dans chaque application.

Éviter les vues contenant une logique métier excessive.

Utiliser des transactions pour les opérations nécessitant une cohérence atomique.

Ne pas ajouter une abstraction uniquement pour déplacer quelques lignes de code.

---

## 4. Documentation du code Python

### 4.1 Règle générale

Le code doit être compréhensible par un développeur qui découvre le projet.

Documenter les décisions importantes sans surcharger le code de commentaires.

Les commentaires et docstrings doivent être rédigés en français, sauf lorsqu'une convention existante du module impose l'anglais.

Conserver les noms techniques, les identifiants et les contrats API dans leur langue actuelle.

### 4.2 Docstrings

Ajouter des docstrings aux fonctions, classes et méthodes dont le comportement n'est pas immédiatement évident.

Documenter particulièrement :

- Les règles métier complexes.
- Les calculs financiers.
- Les transactions.
- Les permissions.
- Les mécanismes cryptographiques.
- Les interactions avec les services externes.
- Les traitements asynchrones.
- Les validations complexes.

Utiliser un style de docstring cohérent avec le projet.

Exemple :

```python
def calculate_total_amount(unit_price, quantity, discount=0):
    """
    Calcule le montant total d'une ligne de vente.

    Args:
        unit_price: Prix unitaire du produit.
        quantity: Quantité vendue.
        discount: Réduction appliquée.

    Returns:
        Montant total après réduction.

    Raises:
        ValueError: Si la quantité est invalide.
    """
```

Ne pas ajouter de docstrings triviales à toutes les fonctions.

### 4.3 Commentaires

Expliquer pourquoi une décision technique est nécessaire, et non simplement ce que fait une instruction.

Éviter :

```python
# Ajouter 1 à la quantité
quantity += 1
```

Préférer les commentaires qui expliquent une contrainte métier ou une décision non évidente.

### 4.4 Typage

Utiliser les annotations de types Python lorsque cela améliore la lisibilité et la sécurité.

Privilégier les types explicites.

Éviter les annotations trompeuses ou inutilement complexes.

---

## 5. Documentation des API REST

### 5.1 Obligation de documentation

Toute API créée ou substantiellement modifiée doit être documentée.

Documenter :

- La méthode HTTP.
- L'URL.
- Le rôle de l'endpoint.
- Les paramètres de chemin.
- Les paramètres de requête.
- Les champs du corps de requête.
- Les champs de réponse.
- Les permissions nécessaires.
- Les codes HTTP.
- Les erreurs métier.
- Les contraintes de validation.
- Les règles de pagination et de filtrage, lorsque pertinentes.

### 5.2 OpenAPI

Privilégier une documentation OpenAPI 3.x générée à partir des serializers, vues et routes existants.

Si le projet utilise déjà `drf-spectacular`, `drf-yasg` ou une autre solution, conserver cette solution.

Ne pas installer une nouvelle bibliothèque de documentation sans vérifier les dépendances existantes.

La documentation doit correspondre au comportement réel des endpoints.

Ne pas inventer des champs ou des réponses.

### 5.3 Exemple de documentation d'endpoint

```text
POST /api/v1/businesses/{business_id}/products/

Description :
Créer un produit dans une entreprise.

Authentification :
Requise.

Autorisation :
Permission de création de produit dans l'entreprise.

Corps :
Champs définis par le serializer de création.

Réponses :
201 — Produit créé.
400 — Données invalides.
401 — Authentification absente ou invalide.
403 — Permission insuffisante.
404 — Entreprise introuvable ou inaccessible.
```

Cet exemple est illustratif : vérifier les statuts et contrats réels avant de les documenter.

### 5.4 Erreurs API

Utiliser les codes HTTP appropriés.

Conserver une structure d'erreur cohérente avec le contrat existant.

Ne pas transformer systématiquement toutes les erreurs en HTTP 500.

Distinguer :

- 400 : requête invalide.
- 401 : authentification nécessaire ou invalide.
- 403 : accès interdit.
- 404 : ressource inexistante ou inaccessible.
- 409 : conflit d'état, lorsque pertinent.
- 429 : limitation de requêtes.
- 500 : erreur serveur inattendue.
- 502/503 : indisponibilité ou erreur d'un service externe, lorsque pertinent.

Ne pas exposer de traces Python, secrets ou détails internes dans les réponses publiques.

### 5.5 Compatibilité API

Ne pas renommer ou supprimer un endpoint, champ ou code d'erreur existant sans analyser les consommateurs.

Avant une modification incompatible :

1. Identifier les usages dans le frontend.
2. Examiner les tests.
3. Proposer une stratégie de transition.
4. Préserver la compatibilité lorsque cela est possible.

Ne pas modifier silencieusement les contrats API.

---

## 6. Documentation fonctionnelle et technique

Lorsqu'une fonctionnalité importante est créée ou substantiellement modifiée, mettre à jour la documentation pertinente.

Documenter notamment :

- Les règles métier.
- Les modèles concernés.
- Les permissions.
- Les endpoints.
- Les flux de traitement.
- Les dépendances externes.
- Les variables d'environnement.
- Les procédures de test.
- Les limites connues.

Privilégier les documents existants.

Si nécessaire, organiser la documentation sous `docs/`, par exemple :

```text
docs/
├── architecture/
├── api/
├── authentication/
├── businesses/
├── catalog/
├── inventory/
├── sales/
├── payments/
└── deployment/
```

Ne pas créer automatiquement tous ces dossiers : ils servent d'exemple d'organisation.

Éviter les documents redondants.

Ne jamais documenter de secrets réels.

---

## 7. Sécurité et authentification

Carri Account est le fournisseur d'identité indépendant.

Respecter les mécanismes existants :

- OAuth 2.0.
- OpenID Connect.
- JWT.
- Validation des signatures.
- HMAC.
- Protection anti-rejeu.
- CSRF.
- Vérification des permissions.
- Gestion des sessions et tokens.
- Communications HTTPS en production.

Ne jamais désactiver une protection de sécurité pour contourner un bug.

Ne pas modifier Carri Account sans autorisation explicite.

Ne pas journaliser :

- Mots de passe.
- Access tokens.
- Refresh tokens.
- Secrets OAuth.
- Clés privées.
- Secrets HMAC.
- Clés Cloudinary.

Ne pas inclure de données personnelles sensibles dans les logs sans nécessité.

Toute opération sensible doit vérifier l'identité et les autorisations côté backend.

---

## 8. Isolation multi-entreprises

La plateforme est multi-entreprises.

L'isolation des données est une exigence fondamentale.

Toute requête métier doit respecter le contexte de l'entreprise concernée.

Vérifier :

- L'appartenance à l'entreprise.
- Les permissions de l'utilisateur.
- La portée des QuerySets.
- Les relations entre ressources.
- Les accès aux objets.
- Les opérations d'écriture.

Ne jamais se fier uniquement à un `business_id` fourni par le client.

Ne pas permettre à un utilisateur d'accéder aux données d'une autre entreprise sans autorisation.

Ajouter des tests de séparation entre entreprises pour les opérations sensibles.

Les permissions frontend ne remplacent jamais les permissions Django.

---

## 9. Modèles et intégrité des données

Les modèles Django représentent les données métier.

Respecter les contraintes existantes :

- Clés étrangères.
- Contraintes d'unicité.
- Index.
- Contraintes de validation.
- Politiques `on_delete`.
- Historique métier.
- Relations entre entreprises.

Ne pas supprimer des données protégées par des relations `PROTECT`.

Ne pas contourner les contraintes de la base.

Ne pas modifier directement les historiques métier immuables.

Pour les opérations critiques, utiliser `transaction.atomic()` lorsque nécessaire.

Utiliser `select_for_update()` lorsque le contrôle de concurrence l'exige.

Ne pas ajouter des transactions ou des verrous sans justification.

---

## 10. Migrations Django

### 10.1 Règle obligatoire

Ne jamais appliquer automatiquement une migration à une base de données existante sans autorisation explicite.

Les commandes suivantes nécessitent une autorisation avant toute application réelle :

```bash
python manage.py migrate
```

La génération de fichiers de migration peut être proposée ou réalisée si la tâche le nécessite, mais leur application doit être autorisée.

### 10.2 Avant une migration

Examiner :

- Les changements de schéma.
- Les données existantes.
- Les risques de perte de données.
- Les contraintes PostgreSQL.
- Les dépendances entre migrations.
- La compatibilité avec le code existant.

Ne jamais supprimer une colonne contenant des données sans stratégie explicite.

Ne pas modifier une migration déjà appliquée sans justification exceptionnelle.

### 10.3 Migrations de données

Pour les migrations de données :

- Prévoir la gestion des données historiques.
- Évaluer la réversibilité.
- Éviter les opérations destructives.
- Tester sur une base isolée lorsque possible.
- Documenter les risques.

---

## 11. Gestion des stocks

Les opérations de stock sont sensibles.

Respecter les règles existantes concernant :

- Entrées.
- Sorties.
- Ajustements.
- Transferts.
- Ventes.
- Retours.

Ne pas modifier directement les quantités lorsque le domaine impose la création de mouvements de stock.

Préserver la traçabilité.

Éviter les stocks négatifs lorsque les règles métier les interdisent.

Gérer correctement les opérations concurrentes.

Ne pas supprimer ou réécrire l'historique des mouvements pour corriger une erreur d'affichage.

---

## 12. Ventes, achats et finances

Les opérations financières doivent être exactes et traçables.

Privilégier `Decimal` pour les montants monétaires.

Éviter les calculs financiers avec `float`.

Respecter :

- La devise de référence.
- Les taux de change.
- Les règles d'arrondi.
- Les montants historiques.
- Les remises.
- Les taxes lorsque présentes.
- Les paiements.
- Les remboursements.

Ne pas recalculer silencieusement des montants historiques à partir de taux de change actuels.

Ne pas inventer des règles de conversion.

Pour les opérations financières critiques, ajouter des tests sur les arrondis, la concurrence et l'idempotence.

---

## 13. Cloudinary et fichiers médias

Les images et vidéos sont stockées sur Cloudinary.

Le backend doit :

- Valider les fichiers.
- Vérifier les permissions.
- Contrôler les limites métier.
- Gérer les erreurs du fournisseur.
- Enregistrer les métadonnées utiles.
- Préserver la cohérence entre Cloudinary et PostgreSQL.

Ne jamais enregistrer un média comme disponible si son téléversement a échoué.

Ne pas effectuer de véritable upload sans autorisation explicite pendant les tests ou diagnostics.

Les vidéos doivent être validées avec les outils existants, notamment `ffprobe` si cette dépendance est requise.

Ne pas imposer arbitrairement une résolution minimale excluant les smartphones peu performants.

Conserver les contrôles de sécurité sur les fichiers.

Ne pas supprimer de médias Cloudinary existants sans autorisation.

---

## 14. Performance et optimisation

Optimiser les accès PostgreSQL lorsque nécessaire.

Examiner :

- Les requêtes N+1.
- `select_related()`.
- `prefetch_related()`.
- Les index.
- La pagination.
- Les agrégations.
- Les transactions longues.
- Les appels externes bloquants.

Ne pas ajouter des index sans justification.

Éviter les requêtes inutiles dans les serializers.

Ne pas mettre en cache des données privées sans isolation correcte par utilisateur et entreprise.

Ne pas optimiser prématurément au détriment de la lisibilité.

---

## 15. Services externes

Toute intégration externe doit gérer :

- Les délais d'attente.
- Les erreurs réseau.
- Les réponses invalides.
- Les erreurs d'authentification.
- Les limitations du fournisseur.
- Les éventuelles tentatives de reprise.

Les retries doivent être limités et adaptés au caractère idempotent de l'opération.

Ne pas relancer automatiquement une opération financière non idempotente sans mécanisme de protection.

Ne pas exposer les secrets des services externes.

Utiliser des mocks ou des fakes dans les tests automatisés.

---

## 16. Tests automatisés

Toute correction fonctionnelle doit être accompagnée de tests adaptés.

Privilégier les outils déjà utilisés dans le projet.

Tester notamment :

- Les modèles.
- Les serializers.
- Les services.
- Les endpoints.
- Les permissions.
- Les règles métier.
- Les erreurs.
- Les cas limites.
- Les accès inter-entreprises.
- Les opérations concurrentes lorsque pertinentes.

### 16.1 Tests API

Vérifier :

- Les statuts HTTP.
- Les champs de réponse.
- Les erreurs structurées.
- Les permissions.
- La validation des données.
- L'isolation des entreprises.

### 16.2 Tests de sécurité

Tester les tentatives d'accès non autorisées.

Vérifier qu'un utilisateur d'une entreprise ne peut pas consulter ou modifier les données d'une autre entreprise.

Ne pas utiliser les services externes réels dans les tests unitaires.

### 16.3 Commandes

Depuis le répertoire `backend`, utiliser les commandes adaptées au projet :

```bash
../env/bin/python manage.py check
../env/bin/python manage.py test
../env/bin/python manage.py makemigrations --check --dry-run
git diff --check
```

Ne pas supposer que tous les tests sont exécutables sans PostgreSQL ou services de test.

Ne pas lancer de tests susceptibles de modifier une base non isolée.

Si la suite complète est trop longue, exécuter les tests ciblés et signaler ceux qui restent à lancer.

Ne jamais déclarer un test réussi s'il n'a pas été exécuté.

---

## 17. Qualité du code

Respecter les conventions Python et les outils déjà configurés dans le dépôt.

Privilégier :

- Des fonctions courtes et cohérentes.
- Des noms explicites.
- Des validations centralisées lorsque pertinent.
- Une gestion des exceptions précise.
- Des imports organisés.
- Des responsabilités clairement séparées.

Éviter :

- `except Exception` sans justification.
- Les exceptions silencieusement ignorées.
- Les valeurs magiques non documentées.
- La duplication de logique.
- Les dépendances circulaires.
- Les requêtes SQL inutiles.
- Les effets secondaires cachés.

Ne pas ajouter de nouveaux outils de linting ou de formatage sans nécessité.

---

## 18. Git et messages de commit

### 18.1 Règle obligatoire

Après chaque intervention comportant des modifications, proposer au moins un message de commit.

Ne jamais effectuer automatiquement :

- `git commit`
- `git push`
- `git reset --hard`
- `git clean -fd`
- Une réécriture destructive de l'historique Git.

Ces opérations nécessitent une autorisation explicite.

Préserver les modifications préexistantes.

### 18.2 Convention Conventional Commits

Utiliser :

`type(scope): description`

Types recommandés :

- `feat` : nouvelle fonctionnalité.
- `fix` : correction de bug.
- `refactor` : restructuration.
- `perf` : optimisation.
- `docs` : documentation.
- `test` : tests.
- `style` : formatage.
- `chore` : maintenance.
- `build` : configuration de compilation.
- `ci` : intégration continue.

Utiliser `fix` pour les corrections de sécurité, avec un scope explicite tel que `security` ou `auth`.

Scopes possibles :

- `auth`
- `api`
- `businesses`
- `catalog`
- `products`
- `inventory`
- `sales`
- `purchases`
- `payments`
- `finance`
- `currencies`
- `media`
- `permissions`
- `database`
- `docs`
- `config`

Messages en anglais, concis et précis.

Exemples :

```text
feat(catalog): support dynamic product attributes
fix(media): accept product videos at any resolution
fix(auth): validate HMAC signatures consistently
feat(inventory): add stock transfer validation
fix(sales): prevent duplicate sale processing
perf(products): optimize catalog queries
docs(api): document product media endpoints
test(permissions): cover cross-business access
refactor(payments): isolate payment provider logic
```

### 18.3 Commits logiques

Si plusieurs changements indépendants sont réalisés, proposer plusieurs commits distincts.

Ne pas mélanger les modifications frontend et backend dans un même commit si les projets sont dans des dépôts différents.

Ne pas inclure de fichiers temporaires, secrets ou artefacts de tests dans les commits proposés.

---

## 19. Rapport obligatoire après chaque intervention

À la fin de chaque tâche, fournir :

### Diagnostic

Décrire le problème identifié ou le besoin traité.

### Modifications

Résumer les corrections ou fonctionnalités réalisées.

### Fichiers

Lister les fichiers créés ou modifiés.

### Documentation

Indiquer les docstrings, commentaires ou documents API ajoutés ou mis à jour.

### Tests

Préciser les commandes exécutées et leurs résultats.

### Limites

Indiquer ce qui n'a pas été testé ou ce qui reste à vérifier.

### Commit proposé

Fournir un ou plusieurs messages de commit Conventional Commits.

Ne jamais annoncer qu'une fonctionnalité est validée si seuls les tests statiques ont réussi.

---

## 20. Restrictions opérationnelles

Sans autorisation explicite :

- Ne pas modifier Carri Account.
- Ne pas modifier Kisinet.
- Ne pas modifier le frontend hors périmètre.
- Ne pas supprimer des données.
- Ne pas appliquer de migrations.
- Ne pas réinitialiser PostgreSQL.
- Ne pas effectuer d'opérations destructives.
- Ne pas effectuer d'uploads réels vers Cloudinary.
- Ne pas déclencher de paiements réels.
- Ne pas exposer les variables d'environnement sensibles.
- Ne pas effectuer de commit ou de push.

Ne pas modifier les règles de sécurité ou les permissions pour faire passer artificiellement un test.

---

## 21. Priorités du projet

En cas de choix entre plusieurs solutions, privilégier :

1. Sécurité.
2. Intégrité et isolation des données.
3. Exactitude des règles métier.
4. Compatibilité API.
5. Fiabilité.
6. Performance.
7. Maintenabilité.
8. Documentation.
9. Simplicité.

Le backend doit être conçu comme un système de production, capable de gérer plusieurs entreprises et leurs données de manière sécurisée et fiable.