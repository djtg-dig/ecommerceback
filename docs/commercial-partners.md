# Répertoire clients et fournisseurs

## Architecture réutilisée

Le répertoire ne crée aucun modèle parallèle. `sales.Customer` appartient à une
entreprise et reste protégé par les relations `Sale` et `Receivable` en
`PROTECT`. `purchases.Supplier` appartient également à une entreprise et reste
protégé par les relations `Purchase`. La désactivation avec `is_active` est donc
préférée à une suppression destructive.

Les ventes conservent leur lien vers le client après une modification de ses
coordonnées. Les achats conservent de la même manière leur fournisseur. Une
vente anonyme et un achat sans fournisseur restent autorisés.

## Permissions

- `VIEW_CUSTOMERS` : liste, recherche et informations générales des clients.
- `MANAGE_CUSTOMERS` : création et modification, y compris la désactivation.
- `VIEW_SALES` : historique des ventes dans une fiche client.
- `VIEW_RECEIVABLES` : capacité de consulter les créances via le module Finance.
- `VIEW_PURCHASES` : liste, recherche, fiche et historique fournisseur.
- `MANAGE_PURCHASES` : création et modification des fournisseurs.
- `VIEW_FINANCIAL_SUMMARY` : synthèses financières clients et fournisseurs.
- `USE_POS` : projection compacte des clients actifs pour la sélection lors
  d'une vente.

Le propriétaire conserve les droits implicites définis par le moteur de
permissions. Aucun titre ou ancien rôle n'est utilisé pour autoriser une action.

## API

- `GET/POST /api/v1/businesses/{SH}/customers/`
- `GET/PATCH /api/v1/businesses/{SH}/customers/{CU}/`
- `GET /api/v1/businesses/{SH}/customers/{CU}/profile/`
- `GET /api/v1/businesses/{SH}/customers/pos/search/`
- `GET/POST /api/v1/businesses/{SH}/suppliers/`
- `GET/PATCH /api/v1/businesses/{SH}/suppliers/{SP}/`
- `GET /api/v1/businesses/{SH}/suppliers/{SP}/profile/`

Les listes et historiques sont paginés. Les listes acceptent `q`, `ordering`,
`page` et `page_size`. Chaque ressource est filtrée simultanément par
l'entreprise de l'URL et son identifiant public.

## Données financières

La fiche client affiche, avec `VIEW_FINANCIAL_SUMMARY`, le total brut des ventes
finalisées, les encaissements nets issus du grand livre Finance et le solde des
créances après paiements et ajustements de retour. La fiche fournisseur limite
ses totaux aux achats confirmés ou réceptionnés et aux paiements non annulés.

Ces indicateurs utilisent uniquement les documents et écritures existants. Ils
ne créent ni solde parallèle, ni dette, ni écriture comptable.
