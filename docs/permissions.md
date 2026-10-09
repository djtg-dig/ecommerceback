# Propriété, titres et permissions Business

L'autorisation d'un Business repose sur les données serveur de
`BusinessMember`. Trois notions restent indépendantes :

- `is_owner` représente la propriété administrative unique ;
- `title` décrit le métier sans accorder aucun droit ;
- `BusinessMemberPermission` contient les permissions individuelles explicites.

Le champ historique `role` reste disponible pendant la transition des données,
mais le moteur d'autorisation ne le consulte jamais.

## Moteur centralisé

`apps.businesses.permissions` fournit l'interface réutilisable par les API :

- `membership_for` recherche une appartenance dans le seul Business demandé ;
- `has_permission` évalue une permission enregistrée côté serveur ;
- `require_permission` renvoie le membre autorisé ou lève l'erreur API canonique.
- `require_any_permission` couvre les rares projections volontairement partagées
  entre deux capacités, sans consulter le titre ni le rôle historique.

Un OWNER actif possède implicitement toutes les permissions connues, sans ligne
`BusinessMemberPermission`. Un autre membre actif ne possède que ses permissions
explicitement accordées. Une permission inconnue est refusée, y compris pour un
OWNER. Un membre suspendu ne dispose d'aucun droit.

Chaque appartenance possède un identifiant public opaque préfixé `BM`. Le statut
`REMOVED` représente un retrait logique terminal : le membre est conservé pour
la traçabilité, ses permissions individuelles sont supprimées dans la même
transaction et il est ensuite traité comme absent par les API métier. Le retrait
physique d'un `BusinessMember` est interdit. Le propriétaire unique ne peut pas
être retiré, suspendu ou rétrogradé.

L'absence d'appartenance ou une appartenance retirée produit une réponse `404`,
afin de ne pas révéler les données d'un autre tenant. Une appartenance existante
sans droit suffisant, y compris une appartenance suspendue, produit `403`.

Les lectures administratives autorisées restent possibles lorsque le Business
est `SUSPENDED` ou `ARCHIVED`. Toute opération métier doit appeler le moteur avec
`write=True` ; elle est alors refusée tant que le Business n'est pas `ACTIVE`.

## Administration des permissions

Pour le MVP, seul le propriétaire actif peut appeler les services
`grant_permission` et `revoke_permission`. Ces services rechargent et verrouillent
le propriétaire, le membre cible et le Business dans une transaction. Ils
refusent les permissions inconnues, les cibles d'un autre Business, les cibles
suspendues et toute tentative de créer ou révoquer les droits implicites du
propriétaire. Un titre, un ancien rôle ou une valeur fournie par le client ne
peut donc pas provoquer d'élévation de privilèges.

La migration progressive des endpoints métier vers `require_permission` est le
périmètre de P1-A3. Les helpers transitoires fondés sur `UPDATE_BUSINESS` ont été
retirés à l'issue de P1-A3.7.

## Permissions des clients, ventes et moyens de paiement

- `VIEW_PAYMENT_METHODS` autorise la consultation administrative des moyens
  actifs et inactifs ;
- `MANAGE_PAYMENT_METHODS` autorise leur création et leur modification ;
- `VIEW_CUSTOMERS` autorise la consultation du référentiel client complet ;
- `MANAGE_CUSTOMERS` autorise la création administrative de clients ;
- `VIEW_SALES` autorise la liste des ventes, leur détail et leurs lignes ;
- `USE_POS` autorise le parcours d'encaissement, sans accorder les lectures
  administratives précédentes.

Un membre `USE_POS` peut consulter les moyens de paiement actifs sur
`GET /payment-methods/` et utiliser
`GET /customers/pos/search/`. Cette recherche est paginée et ne retourne que
`public_id`, `name` et `phone` pour les clients actifs. Elle n'expose ni notes,
ni adresse, ni historique de ventes. La création via `POST /customers/` exige
toujours `MANAGE_CUSTOMERS` ; `USE_POS` ne crée aucun client implicitement.

Les quatre permissions ajoutées par P1-A3.7 ne sont attribuées automatiquement
à aucun membre existant. L'OWNER actif les possède implicitement comme toutes
les permissions enregistrées ; les autres membres doivent recevoir chaque droit
explicitement du propriétaire.

## Consultation des membres

`GET /api/v1/businesses/{SH}/members/` et
`GET /api/v1/businesses/{SH}/members/{BM}/` exigent `VIEW_MEMBERS` et
projetent `public_id`, `title`, `is_owner`, `status`, `permissions` et
`joined_at`. La liste est paginée côté serveur (20 par défaut, 50 au
maximum) et exclut les membres `REMOVED`. Les permissions affichées sont les
permissions explicites du registre, préchargées en une requête ; l'OWNER voit
ses droits implicites. Aucune donnée Carri Account ni UUID interne n'est
exposée.

## Cycle de vie des membres

`PATCH .../members/{BM}/` (titre uniquement),
`POST .../members/{BM}/suspend/`,
`POST .../members/{BM}/reactivate/` et
`DELETE .../members/{BM}/` exigent `MANAGE_MEMBERS` avec un Business actif
(`write=True`). L'OWNER actif possède implicitement ce droit ; les autres
membres doivent le recevoir explicitement. Chaque service verrouille l'acteur,
la cible et le Business dans une transaction. Le propriétaire unique ne peut
être suspendu, retiré ni rétrogradé, et un administrateur ne peut agir sur
lui-même. La suspension conserve les permissions mais les rend inopérantes ;
la réactivation restaure les mêmes permissions sans élévation ; le retrait
supprime les permissions et est idempotent. Un membre `REMOVED` ne peut pas
être réactivé par l'endpoint ordinaire.
