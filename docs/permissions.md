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

Un OWNER actif possède implicitement toutes les permissions connues, sans ligne
`BusinessMemberPermission`. Un autre membre actif ne possède que ses permissions
explicitement accordées. Une permission inconnue est refusée, y compris pour un
OWNER. Un membre suspendu ne dispose d'aucun droit.

L'absence d'appartenance produit une réponse `404`, afin de ne pas révéler les
données d'un autre tenant. Une appartenance existante sans droit suffisant,
y compris une appartenance suspendue, produit `403`.

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
périmètre de P1-A3. Jusqu'à cette migration, les contrôles existants continuent
d'utiliser les helpers transitoires adossés au même moteur.
