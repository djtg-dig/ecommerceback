# Paniers acheteur

Les paniers sont des brouillons privés, appartenant à une identité Carri et à une seule entreprise. Ils ne réservent pas de stock, ne créent aucune vente ni aucun paiement, et n'enregistrent aucun prix historique.

Toutes les routes exigent l'authentification de l'acheteur. Un panier d'un autre acheteur est retourné comme `404`.

- `GET /api/v1/carts/?business={business_public_id}` liste les paniers de l'acheteur, paginés (20 par défaut, `page_size` au plus 100).
- `POST /api/v1/carts/` crée un panier avec `business` et `name`.
- `GET`, `PATCH`, `DELETE /api/v1/carts/{reference}/` lisent, renomment ou suppriment un panier.
- `POST /api/v1/carts/{reference}/items/` ajoute `{product, quantity}`; une ligne existante est fusionnée.
- `PATCH`, `DELETE /api/v1/carts/{reference}/items/{product_public_id}/` modifient ou retirent une ligne.
- `POST /api/v1/carts/{reference}/clear/` vide un panier.
- `POST /api/v1/carts/items/` ajoute un produit en choisissant `cart` si nécessaire; sans panier brouillon pour cette entreprise, le serveur crée `Mon panier`, puis `Mon panier 2`, etc.
- `POST /api/v1/carts/transfers/` transfère `{source_cart, destination_cart, product, quantity}` entre deux paniers brouillons du même acheteur et de la même entreprise.

Les noms sont normalisés côté serveur (espaces superflus et casse), et sont uniques par triplet acheteur/entreprise/nom normalisé. Les unités indivisibles refusent les quantités fractionnaires; les unités qui le permettent acceptent au plus trois décimales.

`status`, `locked_at` et `locked_by` sont toujours en lecture seule. Un panier `LOCKED` répond à toute mutation acheteur avec `409` et `{ "code": "CART_LOCKED" }`. Aucun endpoint acheteur ne permet de verrouiller un panier : l'autorisation vendeur sera ajoutée ultérieurement.
