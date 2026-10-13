# Inventory / Stock

`apps.catalog` décrit les produits; `apps.inventory` décrit leurs quantités. Aucun champ de quantité n’est ajouté à Product ou ProductVariant. Une future architecture pourra rattacher les inventaires à `BusinessLocation`, sans modifier le principe actuel d’un solde par article vendable.

## InventoryItem

Un `InventoryItem` possède un UUID interne et un identifiant public immuable `IV` + 10 caractères. Il vise exactement un Product simple ou un ProductVariant, jamais les deux. La quantité est un `DecimalField(14, 3)`: jusqu’à 99 999 999 999.999 unités, avec trois décimales pour les futures ventes au poids ou au volume.

Un produit avec des variantes actives est géré uniquement au niveau des variantes. La création d’un InventoryItem produit est alors refusée. Inversement, créer une variante est refusé si un InventoryItem produit existe, afin de ne jamais introduire deux sources de vérité silencieusement. L’opérateur doit résoudre explicitement le solde produit avant de changer cette topologie.

`reserved_quantity` démarre à `0.000`; aucune réservation n’est créée dans cette étape. `available_quantity = quantity - reserved_quantity`. Les contraintes PostgreSQL imposent quantité et réservé non négatifs ainsi que `reserved_quantity <= quantity`. `low_stock_threshold` est optionnel; `is_low_stock` devient vrai lorsque le disponible est inférieur ou égal au seuil. Aucune notification n’est envoyée.

## Mouvements immuables

`StockMovement` est un événement historique avec son identifiant public immuable `SM` + 10 caractères. Il stocke type, delta, quantité avant/après, motif, auteur CarriIdentity et date. Il ne peut être modifié ni supprimé par API ou admin; une correction crée un nouvel `ADJUSTMENT`.

L’API manuelle n’accepte que :

- `IN` avec `quantity` strictement positive : ajoute au stock.
- `OUT` avec `quantity` strictement positive : retire du stock disponible; une sortie au-delà du disponible est refusée.
- `ADJUSTMENT` avec `target_quantity` : fixe une quantité absolue non négative et conserve le delta signé dans le mouvement.

`SALE` et `RETURN` sont des types réservés aux services internes actuels; `TRANSFER` reste réservé à une évolution future. Le client ne peut pas les fabriquer. `reference_type` et `reference_id` sont également réservés aux services système Purchase/Sale/Return et ne sont pas acceptés par l’API manuelle.

## Atomicité et concurrence

Toutes les mutations passent par `apply_stock_movement`. Une transaction `atomic` verrouille d’abord la ligne InventoryItem avec `select_for_update(of=("self",))`, calcule les valeurs avant/après, met à jour le solde et crée le mouvement dans la même transaction. Deux sorties concurrentes ne peuvent donc pas dépenser le même stock. Si l’une des deux écritures échoue, la transaction entière est annulée.

Chaque mouvement manuel exige désormais un en-tête `Idempotency-Key`. La clé est
unique par entreprise et liée à une empreinte du stock ciblé, du type, de la
quantité cible ou du delta et du motif. Un rejeu identique retourne le mouvement
déjà écrit sans modifier le solde; la même clé avec une autre intention répond
`409`. Les mouvements automatiques restent protégés par le verrouillage de leur
document métier; les retours utilisent en plus l’idempotence du `SaleReturn`.

## Permissions

La consultation des soldes, indicateurs et historiques exige
`VIEW_INVENTORY`. La création d’un `InventoryItem` et les mouvements manuels
exigent `MANAGE_INVENTORY`. Les titres et anciens rôles ne participent jamais à
l’autorisation; les permissions effectives Django sont l’unique autorité. Les
produits ou variantes archivés ne peuvent recevoir aucune nouvelle opération
normale; leur historique reste lisible.

## Purchase integration

Un brouillon ou un achat simplement confirmé ne modifie pas le stock. La
transition atomique `CONFIRMED → RECEIVED` crée une seule fois des mouvements
`IN` système avec `reference_type="PURCHASE"` et la ligne d’achat comme
référence. Elle peut créer le premier `InventoryItem` à zéro. Un achat reçu ne
peut plus être annulé par le workflow actuel, ce qui évite une restauration
physique implicite.

## Sales integration
La création d’un brouillon ne réserve ni ne retire de stock. La transition
atomique `DRAFT → COMPLETED` génère les mouvements `SALE`, refuse toute sortie
supérieure au disponible et annule également les effets financiers en cas
d’échec. Seuls les brouillons peuvent être annulés; une annulation financière
d’une vente terminée ne restaure donc jamais silencieusement les marchandises.

## Endpoints de consultation

- `GET /api/v1/businesses/{SH}/inventory/` accepte `q`, `status` (`AVAILABLE`,
  `LOW_STOCK`, `OUT_OF_STOCK`) et `ordering` (`quantity`, `-quantity`).
- `GET /api/v1/businesses/{SH}/inventory/summary/` retourne les produits suivis,
  en stock, en rupture, sous seuil, la quantité totale disponible et les dix
  derniers mouvements.
- `GET /api/v1/businesses/{SH}/inventory/movements/` retourne l’historique
  paginé et accepte `product`, `type`, `origin`, `date_from` et `date_to`.
- `POST /api/v1/businesses/{SH}/inventory/{IV}/movements/` exige
  `Idempotency-Key` et n’accepte que `IN`, `OUT` et `ADJUSTMENT`.

Les libellés et références exposés proviennent du catalogue du même tenant.
Aucune unité n’est affichée car le modèle Catalogue ne définit actuellement
aucun champ d’unité. La valorisation financière n’est pas calculée : les coûts
peuvent être absents et le prix de vente ne constitue pas un coût de stock.

## Sale Returns integration

Chaque `SaleReturnLine` réintègre exactement la quantité retournée sur l’`InventoryItem` du Product ou du ProductVariant enregistré par la `SaleLine`. Une variante crédite uniquement son propre stock, jamais celui de son Product parent. Le mouvement immuable est de type `RETURN`, avec `reference_type="SALE_RETURN_LINE"` et `reference_id` égal au `public_id` de la ligne de retour.

Un Product ou ProductVariant archivé après la vente reste retournable afin de corriger le stock historique exact; son statut ne change pas. Cet opt-in est réservé au workflow Sale Return : les mutations Inventory ordinaires sur une cible archivée restent refusées. Le mouvement et le solde sont écrits dans la transaction atomique du retour; une erreur Inventory, Receivables ou Finance les annule avec le retour entier.
