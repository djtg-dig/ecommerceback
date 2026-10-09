# P1-A4.1 — Audit et conception de la gestion des membres

Date : 9 octobre 2026.

Ce document décrit l'existant et la cible recommandée. Il ne constitue pas une
implémentation. Les modèles, routes et services applicatifs n'ont pas été
modifiés pendant cet audit.

## 1. État actuel

### Modèles et invariants

| Composant | Fonctionnalités disponibles | Limites actuelles |
|---|---|---|
| `Business` | Identifiant public, statut `ACTIVE/SUSPENDED/ARCHIVED`, propriétaire créé atomiquement avec le Business. | Aucun cycle de vie d'équipe. |
| `BusinessMember` | Identité Carri, Business, propriété `is_owner`, titre descriptif, statut `ACTIVE/SUSPENDED`, unicité identité/Business et propriétaire unique. | Pas d'identifiant public, pas de statut de retrait, pas de métadonnées de suspension/retrait. |
| Protection OWNER | Le modèle refuse suppression, suspension ou perte de propriété du dernier OWNER actif. | Aucun endpoint d'administration ; le transfert de propriété n'est pas prévu au MVP. |
| `BusinessMemberPermission` | Registre centralisé, unicité membre/permission, aucune permission persistée pour l'OWNER, validation des membres actifs. | Aucun endpoint d'attribution ou révocation. |
| `CarriIdentity` | Projection minimale et immuable du claim OIDC `sub`; authentification mobile/web et JWT ecommerce. | Aucun e-mail, nom affiché ou claim `email_verified`; l'e-mail ne peut actuellement pas relier une invitation à une identité. |

Le champ legacy `BusinessMember.role` reste conservé pour compatibilité des
données. Il ne participe à aucune autorisation. Les titres sont descriptifs et
n'accordent aucun droit.

### Services et autorisations

- `membership_for`, `has_permission`, `require_permission` et
  `require_any_permission` constituent le moteur centralisé P1-A2 ;
- `create_business` crée atomiquement un OWNER actif intitulé `Gérant` ;
- `grant_permission` et `revoke_permission` existent, utilisent
  `transaction.atomic` et `select_for_update`, et sont réservés à l'OWNER actif ;
- une permission inconnue, une cible d'un autre Business, une cible suspendue ou
  une modification sur un Business inactif sont refusées ;
- aucun service n'existe pour inviter, modifier le titre, suspendre, réactiver ou
  retirer un membre.

`MANAGE_MEMBERS` existe déjà mais n'est utilisé par aucune route. `VIEW_MEMBERS`
protège la seule opération disponible.

### Serializers, vues et routes

L'unique route d'équipe est :

`GET /api/v1/businesses/{business_public_id}/members/`

Elle exige `VIEW_MEMBERS` et retourne `BusinessMemberSerializer`. La réponse
n'est pas paginée. Elle expose les UUID internes `id` et `identity_id`, le champ
legacy `role`, le titre, la propriété, le statut et toutes les permissions.

Le serializer calcule les permissions de chaque non-propriétaire avec une
requête relationnelle. Sans `prefetch_related` et une lecture explicite du cache
préchargé, une liste de membres peut produire un N+1.

Il n'existe actuellement aucun endpoint pour :

- consulter un membre isolé ;
- créer ou suivre une invitation ;
- accepter ou refuser une invitation ;
- modifier titre ou statut ;
- attribuer ou révoquer des permissions ;
- retirer un membre.

### Intégration Carri Account

Carri Account reste l'autorité d'identité. Ecommerce valide les preuves OIDC,
crée ou retrouve `CarriIdentity` uniquement à partir de `sub`, puis émet son JWT
interne. Le login web demande actuellement le seul scope `openid`; le flux
mobile n'enregistre que `sub`.

Une invitation par e-mail ne doit donc jamais créer un `CarriIdentity`, deviner
un `sub` ou considérer une adresse déclarée par le client comme vérifiée. Son
acceptation doit être effectuée par un utilisateur authentifié dont l'adresse a
été attestée par Carri Account.

## 2. Fonctionnalités manquantes et périmètre MVP

| Opération | État | Recommandation MVP |
|---|---|---|
| Lister les membres | Partiel | Obligatoire : pagination et projection publique compacte. |
| Consulter un membre | Absent | Obligatoire. |
| Inviter par e-mail | Absent | Obligatoire après résolution du contrat e-mail Carri. |
| Consulter les invitations | Absent | Obligatoire pour l'administrateur et l'invité authentifié. |
| Renvoyer une invitation | Absent | Obligatoire, avec rotation du jeton et limitation de fréquence. |
| Révoquer une invitation | Absent | Obligatoire. |
| Accepter/refuser | Absent | Obligatoire, avec authentification Carri et correspondance e-mail vérifiée. |
| Modifier le titre | Absent | Obligatoire ; aucun effet sur les permissions. |
| Suspendre/réactiver | Absent | Obligatoire. Les permissions restent dormantes pendant la suspension. |
| Attribuer/révoquer des permissions | Services seulement | Obligatoire : API OWNER-only pour le MVP. |
| Retirer un membre | Absent | Obligatoire, sous forme de retrait logique recommandé. |

Extensions futures : transfert de propriété, plusieurs propriétaires, rôles ou
modèles de permissions, opérations en masse, groupes, SCIM, limites d'équipe par
abonnement, journal d'audit exportable et délégation de l'administration des
permissions.

## 3. Architecture proposée

### 3.1 `BusinessMember`

Faire évoluer le modèle avec :

- `public_id` opaque et unique, préfixe recommandé `BM`, avec backfill ;
- un statut `REMOVED` terminal pour l'accès courant ;
- `suspended_at`, `suspended_by`, `removed_at` et `removed_by`, nullables ;
- conservation de `title`, `is_owner`, `joined_at` et `updated_at` ;
- conservation temporaire de `role`, sans jamais l'accepter dans un payload.

Le retrait logique est préférable à la suppression physique : il conserve la
traçabilité, évite de réinterpréter l'historique et permet de contrôler une
réinvitation. Lors d'un retrait, les permissions individuelles doivent être
supprimées dans la même transaction. Un membre `REMOVED` doit être traité comme
absent par les API métier (`404`), tandis qu'un membre `SUSPENDED` continue à
recevoir `403`.

Le contrat existant exposant les UUID ne doit pas être cassé silencieusement.
Le nouveau contrat utilisera `public_id`; les champs internes pourront être
dépréciés puis retirés dans une version ultérieure.

### 3.2 `BusinessMemberInvitation`

Créer un modèle dédié, sans relation anticipée vers une identité inexistante :

| Champ | Rôle |
|---|---|
| `id`, `public_id` | UUID interne et référence publique opaque, préfixe recommandé `MI`. |
| `business` | Tenant propriétaire de l'invitation. |
| `email`, `normalized_email` | Adresse de livraison et valeur canonique de comparaison. |
| `title` | Titre descriptif initial, valeur par défaut `Employé`. |
| `status` | `PENDING`, `ACCEPTED`, `DECLINED`, `REVOKED`, `EXPIRED`. |
| `token_hash` | Hash SHA-256 unique du secret envoyé ; le secret brut n'est jamais stocké. |
| `expires_at` | Expiration contrôlée côté serveur. |
| `invited_by` | `CarriIdentity` de l'administrateur. |
| `accepted_by`, `member` | Identité et membership créés lors de l'acceptation, nullables avant celle-ci. |
| `acted_at`, `last_sent_at`, `resend_count` | Traçabilité des transitions et renvois. |
| `created_at`, `updated_at` | Audit technique. |

Contraintes et index recommandés :

- une seule invitation `PENDING` pour `(business, normalized_email)` ;
- unicité de `public_id` et `token_hash` ;
- index `(business, status, created_at)` et `normalized_email` ;
- aucune permission initiale stockée dans l'invitation ;
- aucune propriété OWNER attribuable par invitation.

Le service de création doit expirer sous verrou une ancienne invitation arrivée
à échéance avant d'en créer une nouvelle. La contrainte conditionnelle protège
ensuite la course entre deux créations concurrentes.

### 3.3 Projection d'e-mail Carri vérifié

Deux solutions sont possibles :

1. enrichir `CarriIdentity` avec l'adresse principale observée, un indicateur
   `email_verified` et la date d'observation, alimentés exclusivement depuis des
   claims OIDC validés ;
2. exiger une preuve OIDC Carri fraîche lors de l'acceptation et comparer son
   `sub` à l'utilisateur ecommerce authentifié ainsi que son claim e-mail à
   l'invitation.

La seconde solution minimise les données persistées mais alourdit Flutter et le
backend. La première offre un meilleur parcours mobile et permet de lister les
invitations de l'utilisateur. Elle est recommandée si Carri garantit les claims
`email` et `email_verified`, avec le scope `openid email`.

L'e-mail reste une donnée de routage et de rapprochement, jamais l'identifiant
métier : le membership final référence toujours le `sub` immuable via
`CarriIdentity`.

### 3.4 Services métier

Créer des services explicites :

- `invite_member`, `resend_member_invitation`,
  `revoke_member_invitation` ;
- `accept_member_invitation`, `decline_member_invitation` ;
- `update_member_title` ;
- `suspend_member`, `reactivate_member`, `remove_member` ;
- réutiliser `grant_permission` et `revoke_permission` pour les permissions.

Chaque mutation doit ouvrir `transaction.atomic`, verrouiller le Business,
l'acteur et la cible ou l'invitation avec `select_for_update`, puis réévaluer
l'autorisation et les statuts après acquisition des verrous. Une validation
faite uniquement dans le serializer serait insuffisante contre les courses.

Les notifications doivent être déclenchées avec `transaction.on_commit`. Une
erreur de fournisseur ne doit ni créer deux invitations ni exposer le jeton dans
les logs. La stratégie de retry d'envoi devra distinguer l'état persistant de la
livraison effective.

## 4. Endpoints et permissions

Toutes les collections sont paginées, avec `page_size=20` par défaut et 50 au
maximum. Les objets sont filtrés par Business avant résolution de leur
`public_id`.

| Méthode et endpoint | Permission | Comportement |
|---|---|---|
| `GET /businesses/{SH}/members/` | `VIEW_MEMBERS` | Liste compacte, filtres `status` et recherche limitée. |
| `GET /businesses/{SH}/members/{BM}/` | `VIEW_MEMBERS` | Détail, titre, statut, propriété et permissions effectives. |
| `PATCH /businesses/{SH}/members/{BM}/` | `MANAGE_MEMBERS` | Modifie uniquement `title`; jamais propriété, rôle ou permissions. |
| `POST /businesses/{SH}/members/{BM}/suspend/` | `MANAGE_MEMBERS` | Refuse OWNER et auto-suspension. |
| `POST /businesses/{SH}/members/{BM}/reactivate/` | `MANAGE_MEMBERS` | Réactive un membre suspendu et ses permissions existantes. |
| `DELETE /businesses/{SH}/members/{BM}/` | `MANAGE_MEMBERS` | Retrait logique, refuse OWNER et auto-retrait, supprime les permissions. |
| `GET /businesses/{SH}/members/{BM}/permissions/` | `VIEW_MEMBERS` | Liste des permissions explicites ; pour OWNER, droits implicites en lecture. |
| `POST /businesses/{SH}/members/{BM}/permissions/` | OWNER actif uniquement | Attribue une permission serveur connue via le service existant. |
| `DELETE /businesses/{SH}/members/{BM}/permissions/{permission}/` | OWNER actif uniquement | Révoque une permission ; aucune auto-attribution possible. |
| `GET /businesses/{SH}/member-invitations/` | `MANAGE_MEMBERS` | Liste administrative incluant les états terminaux. |
| `POST /businesses/{SH}/member-invitations/` | `MANAGE_MEMBERS` | Crée une invitation sans permissions, jamais OWNER. |
| `GET /businesses/{SH}/member-invitations/{MI}/` | `MANAGE_MEMBERS` | Détail administratif sans jeton brut. |
| `POST /businesses/{SH}/member-invitations/{MI}/resend/` | `MANAGE_MEMBERS` | Rotation du jeton, nouvelle expiration et envoi après commit. |
| `POST /businesses/{SH}/member-invitations/{MI}/revoke/` | `MANAGE_MEMBERS` | Transition terminale idempotente. |
| `GET /me/business-invitations/` | JWT + e-mail Carri vérifié | Invitations `PENDING` correspondant à l'utilisateur. |
| `POST /me/business-invitations/{MI}/accept/` | JWT + e-mail vérifié + jeton | Crée ou réactive le membership sans permission. |
| `POST /me/business-invitations/{MI}/decline/` | JWT + e-mail vérifié + jeton | Refuse l'invitation sans créer de membership. |

`MANAGE_MEMBERS` couvre le cycle de vie de l'équipe, mais pas l'administration
des autorisations. Pour le MVP, l'attribution et la révocation des permissions
restent réservées à l'OWNER, conformément aux services et à
`docs/permissions.md`. Cette séparation empêche un gestionnaire de membres de
s'accorder ou d'accorder des droits supérieurs.

### Payloads recommandés

Un membre doit être projeté sans objet Identity complet :

```json
{
  "public_id": "BMXXXXXXXXXX",
  "title": "Caissier",
  "is_owner": false,
  "status": "ACTIVE",
  "permissions": ["USE_POS"],
  "joined_at": "2026-10-09T10:00:00Z"
}
```

Une invitation administrative expose son e-mail, son titre, son état et ses
dates, mais jamais `token_hash`. La vue destinée à l'invité peut masquer
partiellement l'adresse et ne doit retourner que le nom/public_id du Business,
le titre proposé et l'expiration.

Pour éviter N+1, les listes de membres doivent utiliser `select_related` pour
Business/Identity si nécessaire et `Prefetch("permissions", to_attr=...)`. Le
serializer doit lire la collection préchargée au lieu d'appeler
`values_list()` pour chaque ligne. Les invitations n'ont besoin que de
`select_related("business", "invited_by")`.

## 5. Règles de sécurité et validation

### Membres

- le seul OWNER du MVP ne peut être suspendu, retiré, rétrogradé ni recevoir des
  lignes de permissions ;
- `is_owner`, `role`, `identity` et `business` sont toujours read-only ;
- un titre ne modifie jamais les droits ;
- un nouveau membre commence actif et sans permission ;
- une suspension conserve les permissions mais les rend inopérantes ;
- une réactivation restaure ces mêmes permissions ;
- un retrait supprime les permissions et coupe immédiatement tout accès ;
- un administrateur non OWNER ne peut pas agir sur lui-même pour suspension ou
  retrait ;
- un Business `SUSPENDED` ou `ARCHIVED` autorise les lectures administratives
  prévues par P1-A2 mais aucune mutation d'équipe ni acceptation d'invitation.

### Invitations

- normaliser l'adresse de façon déterministe avant toute comparaison ;
- refuser une invitation si un membership actif ou suspendu correspond déjà à
  l'identité e-mail vérifiée ;
- ne jamais révéler si l'adresse possède déjà un compte Carri ;
- le jeton doit être aléatoire, suffisamment entropique, hashé en base, à durée
  limitée et comparé en temps constant ;
- accepter ou refuser exige simultanément un JWT ecommerce, la correspondance
  d'un e-mail Carri vérifié et le jeton ;
- un jeton seul ne crée jamais de session ni de `CarriIdentity` ;
- une invitation acceptée crée un membre non propriétaire et sans permission ;
- invitation inexistante, autre e-mail ou autre tenant : `404` ; permission
  administrative absente : `403` ; payload invalide : `400` ; doublon actif :
  `409` ; expirée ou révoquée : `410` ;
- un retry d'acceptation par la même identité peut retourner le même membership
  sans duplication ; un état terminal incompatible retourne `409`.

L'accès administrateur aux invitations expirées, révoquées ou acceptées est
conservé pour audit. La liste de l'invité ne montre que ses invitations en
attente non expirées. Les transitions utilisent la date serveur.

### Concurrence et atomicité

Les scénarios suivants doivent être sérialisés sous verrou :

- deux invitations simultanées pour le même Business/e-mail ;
- acceptation concurrente avec révocation, expiration ou second accept ;
- suspension/réactivation/retrait concurrents ;
- retrait concurrent avec attribution de permission ;
- changement de statut du Business pendant une mutation d'équipe.

Les contraintes uniques `(identity, business)`, propriétaire unique,
`(member, permission)` et invitation `PENDING` unique constituent le dernier
rempart DB. Les services doivent convertir les `IntegrityError` attendues en
conflits métier stables, sans réponse 500.

## 6. Flux d'invitation recommandé

1. Un OWNER ou membre `MANAGE_MEMBERS` soumet une adresse et un titre.
2. Le service verrouille Business et acteur, vérifie que le Business est actif,
   normalise l'adresse et traite toute invitation expirée antérieure.
3. Une invitation `PENDING` sans permission est créée ; un secret brut est
   généré, seul son hash est stocké.
4. Après commit, le fournisseur envoie un lien universel/deep link contenant
   `MI` et le secret. Aucun token Carri ou ecommerce n'est envoyé par e-mail.
5. L'utilisateur s'authentifie normalement chez Carri Account.
6. Ecommerce vérifie le `sub`, l'adresse Carri vérifiée et le secret de
   l'invitation.
7. Sous transaction et verrous, le service revalide statut, expiration,
   Business et absence de membership concurrent.
8. Il crée un `BusinessMember` non OWNER, sans permissions, puis marque
   l'invitation `ACCEPTED` dans la même transaction.
9. Le nouveau membre peut voir le Business mais n'exerce aucune opération métier
   avant attribution explicite de permissions par l'OWNER.

Le refus suit le même contrôle d'identité et place l'invitation en `DECLINED`
sans créer de membership.

## 7. Tests nécessaires

### Modèles et services

- identifiants publics et backfill ;
- unicité OWNER, membership, permission et invitation ouverte ;
- normalisation e-mail ;
- titre sans effet sur les droits ;
- nouveau membre sans permission ;
- suspension, réactivation et retrait logique ;
- OWNER impossible à suspendre, retirer ou rétrograder ;
- permissions supprimées au retrait et conservées à la suspension ;
- Business inactif ; isolation Business ; acteur révoqué pendant l'opération.

### Invitations

- création, doublon, expiration, renvoi avec rotation, révocation ;
- adresse Carri vérifiée correspondante/non correspondante ;
- token invalide, expiré, révoqué ou rejoué ;
- acceptation/refus et retry idempotent ;
- aucune identité créée par e-mail ;
- acceptation sans permission ;
- courses accept/revoke, double accept et double invitation ;
- échec d'envoi après commit sans corruption transactionnelle.

### API et performance

- OWNER, `VIEW_MEMBERS`, `MANAGE_MEMBERS`, aucun droit, ancien MANAGER, membre
  suspendu et autre Business ;
- 403/404/409/410 cohérents ;
- aucune auto-attribution et aucune élévation par payload ;
- pagination 20/50, filtres bornés et payload compact ;
- nombre de requêtes constant entre petit et grand jeux de membres ;
- OpenAPI sans jeton secret dans les réponses.

## 8. Plan d'implémentation par petits lots

État de P1-A4.2 : le lot de fondations livre `BusinessMember.public_id`, les
métadonnées de cycle de vie, le statut `REMOVED`, le retrait logique
transactionnel et le backfill. Conformément au périmètre validé pour ce lot, il
ne modifie pas Carri Account et n'introduit pas encore les invitations. Les API
de lecture paginées et leurs mesures anti-N+1 restent dans P1-A4.3 ; les routes
de cycle de vie restent dans P1-A4.6.

État de P1-A4.3 — lectures membres, livré le 9 octobre 2026 :

- `GET /api/v1/businesses/{SH}/members/` est paginé côté serveur
  (`page_size=20` par défaut, `page_size` de 1 à 50, paramètre `page`) et
  retourne `{count, next, previous, results}`. La projection compacte d'un
  membre est `{public_id, title, is_owner, status, permissions, joined_at}` :
  les UUID internes `id` et `identity_id`, le rôle legacy `role` et toute
  donnée Carri Account ne sont plus exposés. Les membres `REMOVED` sont
  exclus. L'ordre est `is_owner` descendant puis `joined_at` et `public_id`
  croissants, donc stable et déterministe.
- `GET /api/v1/businesses/{SH}/members/{BM}/` retourne la même projection
  pour un membre de l'entreprise, `404` pour un membre inexistant, retiré ou
  d'une autre entreprise.
- Les deux endpoints exigent `VIEW_MEMBERS` : OWNER actif implicite, membre
  actif avec la permission explicite, `403` pour un membre suspendu ou sans
  droit, `404` pour une appartenance absente ou retirée. Les lectures
  restent possibles sur un Business `SUSPENDED` ou `ARCHIVED`.
- Les permissions affichées sont les permissions explicites du registre
  `BusinessMemberPermission` (droits implicites complets pour l'OWNER),
  lues depuis un `Prefetch(..., to_attr="_prefetched_permissions")` : aucune
  requête supplémentaire par ligne. Le nombre de requêtes reste constant
  quelle que soit la taille de l'entreprise.
- Aucune mutation, invitation, suspension, réactivation ou modification de
  permission n'est introduite dans ce lot.

État de P1-A4.4 — administration du cycle de vie des membres, livré le
9 octobre 2026 :

- `PATCH /api/v1/businesses/{SH}/members/{BM}/` modifie uniquement
  `title` (payload `{title}`, non vide). `is_owner`, `role`, `status`,
  `identity`, `business` et les permissions restent read-only : une
  tentative d'élévation par payload est ignorée. Le titre du propriétaire
  peut être modifié sans affecter sa propriété.
- `POST /api/v1/businesses/{SH}/members/{BM}/suspend/` suspend un
  membre actif non propriétaire. La suspension conserve les permissions
  enregistrées mais les rend immédiatement inopérantes (`403` pour les
  lectures métier). Idempotente : une seconde suspension retourne le
  même statut sans duplication.
- `POST /api/v1/businesses/{SH}/members/{BM}/reactivate/` réactive un
  membre suspendu et restaure ses permissions existantes, sans accorder
  de nouveaux droits. Un membre actif reste actif (idempotent). Un
  membre `REMOVED` retourne `404` et ne peut pas être réactivé par cet
  endpoint.
- `DELETE /api/v1/businesses/{SH}/members/{BM}/` retire logiquement un
  membre non propriétaire : statut `REMOVED`, `removed_at`/`removed_by`
  renseignés, permissions supprimées dans la même transaction. Le retrait
  est idempotent (`204`). Le membre retiré reste absent des consultations
  administratives ordinaires.
- Les quatre opérations exigent `MANAGE_MEMBERS` avec `write=True` :
  OWNER actif implicite ou membre actif avec la permission explicite.
  Les anciens rôles ou titres ne confèrent aucun droit implicite. Un
  membre suspendu ou retiré reçoit `403`/`404`. Les mutations sont
  refusées (`403`) sur un Business `SUSPENDED` ou `ARCHIVED`.
- Protections du propriétaire unique : impossible de le suspendre, de le
  retirer ou de le rétrograder. Un administrateur non OWNER ne peut pas
  agir sur lui-même (auto-suspension, auto-retrait).
- Chaque service ouvre `transaction.atomic` et verrouille l'acteur, la
  cible et le Business avec `select_for_update` avant toute réévaluation
  d'autorisation et de statut, ce qui sérialise les opérations
  concurrentes (suspension/réactivation/retrait concurrents).
- Le nombre de requêtes reste constant quelle que soit la taille de
  l'entreprise. Aucune donnée Carri Account ni UUID interne n'est
  exposée dans les réponses.
- Les invitations et l'attribution/révocation de permissions ne sont pas
  introduites dans ce lot.

État de P1-A4.5 — administration des permissions individuelles, livré
le 9 octobre 2026 :

- `GET /api/v1/businesses/{SH}/members/{BM}/permissions/` liste les
  permissions explicites d'un membre (exige `VIEW_MEMBERS`). Pour
  l'OWNER, les droits implicites complets sont retournés en lecture
  sans ligne de registre. Réponse compacte `{permission}` par ligne,
  triée par permission, lues depuis le préchargement
  `_prefetched_permissions` sans requête supplémentaire.
- `GET /api/v1/businesses/{SH}/permissions/` expose le registre
  serveur complet `{permission, label}` (exige `VIEW_MEMBERS`),
  permettant à un client de découvrir les valeurs attribuables.
- `POST /api/v1/businesses/{SH}/members/{BM}/permissions/` attribue
  une permission (payload `{permission}`, réponse `201`). Seul le
  propriétaire actif peut appeler ; `MANAGE_MEMBERS` sans propriété
  reçoit `403`.
- `DELETE /api/v1/businesses/{SH}/members/{BM}/permissions/{permission}/`
  révoque une permission (réponse `204`). Seul le propriétaire actif
  peut appeler.
- Les deux mutations réutilisent les services transactionnels
  `grant_permission` et `revoke_permission` : `transaction.atomic`
  avec `select_for_update` sur l'acteur, la cible et le Business,
  validation du registre serveur, refus des permissions inconnues
  (`400`), refus d'attribuer à un membre retiré ou suspendu, refus
  de modifier les droits implicites du propriétaire. L'attribution
  répétée est idempotente (`get_or_create`, une seule ligne) ; la
  révocation répétée est idempotente (`204`).
- Les mutations sont refusées (`403`) sur un Business `SUSPENDED`
  ou `ARCHIVED`. L'isolation interentreprises est préservée
  (`404`). Aucun membre ne peut s'attribuer de permission et aucun
  rôle ou titre ne confère de droit implicite.
- Les permissions d'un membre suspendu sont conservées mais
  inopérantes ; celles d'un membre retiré sont supprimées et ne
  sont jamais restaurées automatiquement.
- Les invitations ne sont pas introduites dans ce lot.

1. **P1-A4.2 — Prérequis identité et modèles** : ajouter
   `BusinessMember.public_id`, les métadonnées de cycle de vie et le retrait
   logique, puis migration, backfill et tests. Le contrat e-mail Carri, la
   projection vérifiée et `BusinessMemberInvitation` sont reportés au lot
   d'invitations afin de ne pas modifier Carri Account dans ce lot.
2. **P1-A4.3 — Lectures membres** : liste/détail paginés, projections compactes,
   préchargement des permissions et mesures anti-N+1.
3. **P1-A4.4 — Cycle de vie membre** : titre, suspension, réactivation et
   retrait logique avec protections OWNER, services transactionnels verrouillés.
4. **P1-A4.5 — Administration des permissions** : consultation, attribution et
   révocation OWNER-only autour des services existants, registre exposé.
5. **P1-A4.6 — Administration des invitations** : créer/lister/détailler,
   révoquer/renvoyer, idempotence et adaptateur d'envoi après commit.
6. **P1-A4.7 — Parcours invité** : liste personnelle, acceptation/refus,
   vérification Carri et tests de concurrence.
7. **P1-A4.8 — Validation finale** : OpenAPI, performance, documentation Flutter,
   tests globaux et audit des événements sensibles.

Chaque lot doit être migrable et testable indépendamment. Les endpoints
d'invitation ne doivent pas être ouverts avant que l'e-mail Carri vérifié et la
livraison sécurisée soient disponibles.

## 9. Risques et décisions métier à arbitrer

| Décision | Recommandation | Caractère bloquant |
|---|---|---|
| Claims Carri `email`/`email_verified`, unicité et changement d'adresse | Confirmer le contrat Carri, demander `openid email`, conserver `sub` comme seule identité. | **Bloque invitations/acceptation.** |
| Fournisseur d'e-mail, URL/deep link et gestion des échecs | Adaptateur serveur + `transaction.on_commit`; aucun secret dans les logs. | **Bloque envoi/renvoi réel.** |
| Durée de validité | 72 heures, configurable. | Non bloquant si cette valeur est validée. |
| Limite de renvoi | Délai minimum de 60 secondes et plafond journalier par invitation/Business. | À valider avant exposition publique. |
| Normalisation d'e-mail | `trim` puis canonicalisation documentée et identique aux claims Carri ; ne pas modifier les alias arbitrairement. | Bloque la contrainte d'unicité exacte. |
| Portée de `MANAGE_MEMBERS` | Invitations et cycle de vie, mais jamais attribution de permissions. | Recommandation compatible avec P1-A2. |
| Administration des permissions | OWNER-only pour le MVP. Une délégation future exigera un plafond de droits. | Non bloquant si la règle actuelle est confirmée. |
| Retrait puis réinvitation | Conserver la ligne `REMOVED`, supprimer ses permissions, puis réactiver la même ligne sans restaurer les droits. | À valider avant le modèle final. |
| Auto-actions | Interdire auto-suspension et auto-retrait ; autoriser éventuellement son propre titre via une route de profil future. | Non bloquant. |
| Affichage du membre | `CarriIdentity` ne fournit ni nom ni avatar. Déterminer si Carri expose des claims de profil. | Ne bloque pas le contrôle d'accès, mais affecte l'UX. |

La conception est compatible avec le moteur P1-A2 et les permissions existantes
`VIEW_MEMBERS`/`MANAGE_MEMBERS`. Aucune nouvelle permission n'est nécessaire
pour le MVP proposé. Les deux prérequis réellement bloquants pour le parcours
d'invitation sont le contrat d'e-mail vérifié Carri et le canal de livraison.
