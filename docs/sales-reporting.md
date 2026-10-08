# Rapports ventes et produits

Les endpoints OWNER/MANAGER `reports/sales/` et `reports/products/` fusionnent côté serveur des agrégations indépendantes de ventes `COMPLETED` selon `Sale.completed_at` et de retours `POSTED` selon `SaleReturn.returned_at`. Ils acceptent les périodes Dashboard et, respectivement, `group_by=day|week|month` et un `limit` de 1 à 50.

Le rapport Sales expose dans `totals` et chaque ligne de `series` :

- `sales_revenue`, `returns_revenue` et `net_revenue`;
- `sales_cogs`, `returns_cogs` et `net_cogs`;
- `gross_margin = net_revenue - net_cogs`;
- `sales_count`, nombre de ventes distinctes finalisées dans la période, jamais diminué par un retour;
- `returns_count`, nombre de retours distincts imputés à la période.

Les champs historiques `revenue` et `cost_of_goods_sold` restent présents et valent respectivement `net_revenue` et `net_cogs`. Une série peut contenir une période avec uniquement des retours et des montants nets négatifs.

Le rapport Products regroupe les lignes Product et Variant sous le Product parent original. Il conserve `quantity_sold`, `revenue`, `cost_of_goods_sold`, `gross_margin` et `margin_rate`, et ajoute `sold_quantity`, `returned_quantity`, `net_quantity`, ainsi que les composantes brutes/retours/nettes du CA et du COGS. `quantity_sold` et `sold_quantity` sont la quantité brute historiquement vendue; `revenue` et `cost_of_goods_sold` sont désormais nets. Le tri et le `limit` s’appliquent après fusion, ce qui inclut un produit ayant un retour dans la période même sans nouvelle vente.

Tous les prix et coûts viennent des snapshots `SaleLine` et `SaleReturnLine`; le catalogue courant, les encaissements, remboursements, créances et mouvements Finance ne participent pas aux formules économiques. Les agrégations ventes/retours séparées évitent les doubles comptages et les requêtes N+1.
