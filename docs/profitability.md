# Rentabilité — Niveau 1

`GET /api/v1/businesses/{business_public_id}/profitability-summary/` fournit une vue économique compacte réservée aux OWNER et MANAGER. Les périodes `today`, `last_7_days`, `last_30_days` et `date_from`/`date_to` sont calculées côté serveur.

- `sales_revenue` : somme des `SaleLine.line_total` des ventes `COMPLETED` selon `Sale.completed_at`.
- `returns_revenue` : somme des `SaleReturnLine.line_total` des retours `POSTED` selon `SaleReturn.returned_at`.
- `net_revenue` : `sales_revenue - returns_revenue`.
- `sales_cogs` : somme de `SaleLine.quantity * SaleLine.unit_cost_snapshot` sur les ventes de la période.
- `returns_cogs` : somme de `SaleReturnLine.quantity * SaleReturnLine.unit_cost_snapshot` sur les retours de la période.
- `net_cogs` : `sales_cogs - returns_cogs`.
- `revenue` et `cost_of_goods_sold` restent présents pour compatibilité et valent respectivement `net_revenue` et `net_cogs`.
- `gross_margin` : `net_revenue - net_cogs`.
- `expenses` : somme des `Expense.amount` `ACTIVE` selon `expense_date`.
- `net_result` : `gross_margin - expenses`.

Le CA et les retours sont économiques : ils utilisent exclusivement les prix et coûts historiques des lignes de vente et de retour. Une modification ultérieure du Product ou ProductVariant ne recalcule pas ces montants. `FinancialMovement`, `ReceivableAdjustment`, `ReceivablePayment`, paiements de dépense, paiements fournisseurs et achats ne participent pas aux formules; un remboursement monétaire ne constitue donc pas un second retour économique.

Une vente est imputée à sa période de finalisation, tandis qu’un retour est imputé indépendamment à sa période économique `returned_at`. Une période peut ainsi présenter des montants nets négatifs si elle contient le retour d’une vente plus ancienne.

Cette vue est courante, pas une clôture comptable : modifier ou annuler ultérieurement une dépense ACTIVE peut modifier un rapport historique recalculé.
