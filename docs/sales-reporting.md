# Rapports ventes et produits

Les endpoints OWNER/MANAGER `reports/sales/` et `reports/products/` agrègent côté serveur les ventes `COMPLETED` selon `completed_at`. Ils acceptent les périodes Dashboard et, respectivement, `group_by=day|week|month` et un `limit` de 1 à 50.

Le rapport ventes retourne CA et nombre de ventes distinctes. Le TOP produits regroupe les variantes sous leur Product parent et calcule revenue, COGS avec `unit_cost_snapshot`, marge et taux de marge. CA, encaissements et marge restent distincts.
