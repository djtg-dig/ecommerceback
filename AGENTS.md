# Mission : nettoyer les anciennes adresses des entreprises E-commerce

## 1. Projets concernés

Backend Django :

`/home/mubaraka/Documents/Entreprise/ecommerce/backend`

Frontend Next.js :

`/home/mubaraka/Documents/Entreprise/ecomfront`

Lire et respecter les instructions `AGENTS.md` de chaque dépôt concerné avant toute intervention.

## 2. Objectif

Le backend possède désormais une architecture d'adresses internationales structurées :

- `Country`
- `AdministrativeArea`
- `Locality`
- `Address`
- `Business.structured_address`

L'ancien modèle `Business` possède toujours un champ texte historique `address`.

Nous souhaitons abandonner progressivement cet ancien champ au profit de `structured_address`, sans perdre les données existantes ni casser les fonctionnalités de la plateforme.

## 3. Audit des dépendances

Inspecter le backend et le frontend afin d'identifier toutes les références à l'ancien champ `Business.address`.

Examiner notamment :

- Modèles Django.
- Serializers.
- Vues, ViewSets et services.
- Permissions.
- Django Admin.
- Tests automatisés.
- Documentation API.
- Types et interfaces TypeScript.
- Formulaires de création et modification d'entreprise.
- Pages de détail des entreprises.
- Pages de détail des produits.
- Composants réutilisables.

Distinguer les champs d'adresse des entreprises de ceux appartenant à d'autres modèles.

Ne supprimer aucun champ homonyme sans rapport.

## 4. Audit et préservation des données historiques

Examiner les anciennes adresses des entreprises.

Préparer un mécanisme de migration des données existantes vers `structured_address`.

Contraintes :

- Ne supprimer aucune adresse historique sans sauvegarde.
- Ne pas inventer de pays, province ou ville.
- Ne pas attribuer automatiquement la RDC à toutes les entreprises.
- Ne pas écraser une adresse structurée déjà renseignée.
- Ne pas créer d'adresses géographiques incohérentes.
- Prévoir une procédure de migration idempotente et vérifiable.

Lorsqu'une ancienne adresse ne peut pas être convertie de manière fiable, conserver les données historiques et signaler l'entreprise comme nécessitant une vérification manuelle.

Produire un bilan indiquant le nombre d'entreprises analysées, migrées, sans adresse et nécessitant une intervention.

## 5. Nouvelle source officielle

Faire de `Business.structured_address` la source officielle des adresses des entreprises.

Les nouvelles créations et modifications doivent utiliser cette structure.

Éviter les doubles écritures entre `address` et `structured_address`.

Conserver temporairement une compatibilité avec l'ancien champ si des consommateurs actifs en dépendent encore.

## 6. Adaptation des API

Vérifier les endpoints de création, consultation et modification des entreprises.

Utiliser `structured_address` pour les données d'adresse.

Préserver :

- Les permissions.
- L'isolation multi-entreprises.
- Les validations métier.
- Les références existantes.
- Les structures JSON nécessaires aux consommateurs non encore migrés.

Mettre à jour la documentation API officielle et les schémas OpenAPI concernés.

Ne pas effectuer de changement incompatible sans stratégie de transition.

## 7. Adaptation du frontend

Modifier uniquement les composants concernés par les adresses d'entreprise.

Remplacer les utilisations de l'ancien champ texte par `structured_address`.

Conserver les fonctionnalités existantes, notamment :

- Création d'entreprise.
- Modification d'entreprise.
- Consultation des entreprises.
- Affichage des informations d'entreprise sur les pages produits.

Préserver le design et les autres champs commerciaux.

Ne pas ajouter de fonctionnalités hors périmètre.

## 8. Suppression de l'ancien champ

Supprimer définitivement `Business.address` uniquement si toutes les conditions suivantes sont remplies :

1. Les données historiques ont été migrées ou préservées sans perte.
2. Les consommateurs frontend ont été adaptés.
3. Les API ne dépendent plus de l'ancien champ.
4. Les tests backend réussissent.
5. Les tests frontend réussissent.
6. Aucune dépendance active ne nécessite encore le champ.
7. Les conséquences sur la compatibilité API ont été analysées et documentées.

Si une condition n'est pas remplie, conserver temporairement le champ et expliquer précisément le blocage.

Créer les migrations Django nécessaires, mais ne pas les appliquer sur une base existante sans autorisation explicite.

## 9. Tests et vérifications

Backend :

- Création d'entreprise avec adresse structurée.
- Modification de l'adresse.
- Consultation de l'adresse.
- Conservation des anciennes données.
- Permissions et isolation entre entreprises.
- Compatibilité des API.
- Absence de régression sur les produits.

Frontend :

- Formulaire de création d'entreprise.
- Formulaire de modification.
- Affichage des informations d'entreprise.
- Affichage des produits associés.
- Vérification TypeScript.
- ESLint.
- Tests pertinents.

Exécuter également les contrôles Django et Git prévus par `AGENTS.md`.

Ne pas annoncer comme réussis des tests qui n'ont pas été exécutés.

## 10. Contraintes

- Respecter les instructions `AGENTS.md`.
- Préserver les modifications préexistantes.
- Ne pas supprimer de données historiques.
- Ne pas modifier les modèles sans rapport.
- Ne pas toucher aux paiements.
- Ne pas modifier Carri Account ou Kisinet.
- Ne pas effectuer de migration en production.
- Ne pas effectuer de commit ou de push automatiquement.

## 11. Rapport final obligatoire

À la fin, fournir les sections suivantes :

1. **Diagnostic** : problème identifié et dépendances historiques.
2. **Modifications** : corrections effectuées.
3. **Fichiers** : fichiers créés ou modifiés.
4. **Documentation** : documentation API mise à jour.
5. **Tests** : commandes exécutées et résultats.
6. **Limites** : problèmes restants ou validations non réalisées.
7. **Commit proposé** : commandes Git complètes.

## 12. Format obligatoire du commit proposé

**Exigence impérative :**

Dans la section « Commit proposé », fournir un seul bloc de code Bash directement copiable dans le terminal.

Ce bloc doit contenir, dans cet ordre :

1. Le chemin absolu du projet avec `cd`.
2. La commande `git add --` avec la liste exacte de tous les fichiers créés ou modifiés par cette intervention.
3. La commande `git diff --cached --check`.
4. La commande `git diff --cached --stat`.
5. La commande `git commit -m` contenant un message Conventional Commits en anglais.

Exemple de présentation pour le backend :

```bash
cd /home/mubaraka/Documents/Entreprise/ecommerce

git add -- \
  backend/apps/businesses/models.py \
  backend/apps/businesses/serializers.py \
  backend/apps/businesses/tests/test_geography.py \
  docs/business-addresses.md

git diff --cached --check
git diff --cached --stat

git commit -m "refactor(businesses): migrate legacy addresses to structured addresses"
```

**Attention : cet exemple est illustratif.**

Ne pas recopier automatiquement cette liste.

L'agent doit déterminer les fichiers réellement modifiés en inspectant le travail effectué et l'état Git du dépôt.

Il doit également :

- Inclure les nouveaux fichiers et migrations réellement créés.
- Ne pas ajouter les fichiers non concernés.
- Ne pas inclure de secrets, fichiers temporaires ou artefacts de tests.
- Ne pas inclure les modifications préexistantes sans rapport.
- Vérifier le répertoire racine Git avant de construire les commandes.

### Si le backend et le frontend sont deux dépôts Git distincts

Fournir **deux blocs Bash séparés**, un pour chaque dépôt.

Chaque bloc doit contenir son propre :

- `cd`
- `git add --`
- `git diff --cached --check`
- `git diff --cached --stat`
- `git commit -m`

Ne jamais mélanger des fichiers appartenant à deux dépôts différents dans un même commit.

### Règle finale

**Ne pas exécuter les commandes `git commit` ou `git push`.**

Les fournir uniquement dans le rapport final afin que je puisse les copier-coller et effectuer moi-même les commits.

## 13. Critère de réussite

Le système doit utiliser `structured_address` comme source officielle des adresses des entreprises.

Aucune donnée historique ne doit être perdue.

L'ancien champ `Business.address` ne doit être supprimé que lorsque son retrait est techniquement sûr.

Le rapport final doit obligatoirement contenir les commandes Git complètes, directement copiables, avec les chemins, les fichiers concernés et les messages de commit.