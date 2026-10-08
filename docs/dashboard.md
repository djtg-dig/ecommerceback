# Dashboard Niveau 1

`GET /api/v1/businesses/{SH}/dashboard/` fournit en un appel une synthèse compacte réservée aux OWNER et MANAGER. `period` accepte `today`, `last_7_days`, `last_30_days`; `date_from` et `date_to` forment une période personnalisée.

## Chiffre d’affaires

La section `sales` conserve `total` et `count`. `count` reste le nombre de ventes `COMPLETED` finalisées dans la période. `total` représente désormais le chiffre d’affaires net et reste compatible avec les clients existants. Trois champs rendent le calcul explicite :

- `sales_revenue` : somme des `SaleLine.line_total` selon `Sale.completed_at`;
- `returns_revenue` : somme des `SaleReturnLine.line_total` des retours `POSTED` selon `SaleReturn.returned_at`;
- `net_revenue` : `sales_revenue - returns_revenue`, identique à `total`.

Une vente et son retour peuvent appartenir à des périodes différentes. Le Dashboard utilise les montants historiques des lignes de retour et ne recalcule rien depuis le catalogue.

## Trésorerie et créances

La section `cash` agrège exclusivement les `FinancialMovement` de la période. Les `SALE_RETURN_REFUND` sont donc comptés une fois comme OUTFLOW; `refund_amount` n’est pas soustrait séparément. Un `ReceivableAdjustment RETURN_CREDIT` réduit une créance, mais ne constitue jamais une sortie de caisse.

`receivables.outstanding_amount` additionne les soldes ouverts réels : `original_amount - ReceivablePayment - ReceivableAdjustment`. Les statuts `OPEN`, `PARTIALLY_PAID` et `PAID` restent produits par les services métier; `open_count` inclut les deux premiers et `overdue_count` applique la date d’échéance aux créances encore ouvertes.

## Stock, achats et limites

Les formules Inventory et Purchases sont inchangées. Le stock affiché est l’état courant, déjà réintégré par le workflow de retour; la dette fournisseur conserve son calcul existant.

CA, cash et rentabilité restent des notions distinctes. Le Dashboard ne fournit ni cache, ni ETag, ni solde bancaire réel, ni détail low-stock, ni calcul de bénéfice. Ses agrégations SQL sont indépendantes afin d’éviter les doubles comptages et les requêtes N+1.
