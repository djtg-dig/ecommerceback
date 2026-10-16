# Registre Python des catégories produits

Les catégories nouvelles sont déclarées dans `backend/apps/catalog/registry.py`. Elles ne sont
jamais copiées dans `ProductCategory`, `AttributeDefinition` ou `AttributeOption`.

## Migration progressive

Un produit utilise exactement une source :

- `category` pour une catégorie PostgreSQL historique ;
- `category_code` pour une catégorie du registre Python.

La contrainte `catalog_product_exactly_one_category_source` garantit cette exclusivité. La
migration rend d'abord la clé étrangère nullable, ajoute `category_code`, vérifie que chaque ligne
historique possède encore sa clé étrangère, puis ajoute la contrainte. Elle ne convertit et ne
supprime aucune catégorie existante.

Le champ de sortie `category` reste le code résolu afin de préserver le contrat des anciens
clients. `category_source` vaut `legacy` ou `registry`, et `category_code` n'est renseigné que pour
le registre. La résolution commune est assurée par `resolve_product_category`.

## API

- `GET /api/v1/product-categories/registry/` liste les catégories du registre et leur module parent.
- `GET /api/v1/product-categories/registry/{code}/` retourne leurs attributs, types, options,
  unités, bornes, caractère obligatoire et axe de variante.
- Les anciennes routes `/api/v1/product-categories/` et
  `/api/v1/product-categories/{code}/attributes/` restent inchangées.
- La création et la modification d'un produit acceptent soit `category`, soit `category_code`,
  jamais les deux. `attributes` est validé et normalisé contre la source retenue.

Les valeurs décimales sont normalisées en chaînes JSON, les entiers et booléens conservent leur
type JSON, et les axes de variante sont validés séparément lors des écritures de variantes.

## Ajout d'une catégorie

Ajouter une `CategorySpec` au registre avec un code unique et des `AttributeSpec` uniques dans la
catégorie. Les types acceptés sont `string`, `integer`, `decimal`, `boolean`, `select` et
`multi_select`. Compléter les tests unitaires du registre et ne créer aucune migration de données
pour ces définitions.
