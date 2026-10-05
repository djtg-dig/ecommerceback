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

`SALE`, `RETURN` et `TRANSFER` existent comme types réservés aux futurs services internes; le client ne peut pas les fabriquer. `reference_type` et `reference_id` sont également réservés aux futurs services Purchase/Sale/Return/Transfer et ne sont pas acceptés par l’API manuelle.

## Atomicité et concurrence

Toutes les mutations passent par `apply_stock_movement`. Une transaction `atomic` verrouille d’abord la ligne InventoryItem avec `select_for_update(of=("self",))`, calcule les valeurs avant/après, met à jour le solde et crée le mouvement dans la même transaction. Deux sorties concurrentes ne peuvent donc pas dépenser le même stock. Si l’une des deux écritures échoue, la transaction entière est annulée.

Les opérations manuelles ne reçoivent pas encore de clé d’idempotence. Les futurs mouvements automatiques issus de Sale, Purchase, Return ou paiement devront être idempotents avant leur introduction.

## Permissions

Les membres actifs OWNER, MANAGER et EMPLOYEE peuvent consulter les balances et l’historique. Seuls OWNER et MANAGER peuvent créer un InventoryItem ou appliquer un mouvement manuel. Les produits ou variantes archivés ne peuvent recevoir aucune nouvelle opération normale; leur historique reste lisible.
