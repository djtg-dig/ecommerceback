# Rentabilité — Niveau 1

`GET /api/v1/businesses/{business_public_id}/profitability-summary/` fournit une vue économique compacte réservée aux OWNER et MANAGER. Les périodes `today`, `last_7_days`, `last_30_days` et `date_from`/`date_to` sont calculées côté serveur.

- `revenue` : somme des `SaleLine.line_total` des ventes `COMPLETED` selon `completed_at`.
- `cost_of_goods_sold` : somme de `quantity * unit_cost_snapshot` sur ces mêmes lignes.
- `gross_margin` : revenue moins cost_of_goods_sold.
- `expenses` : somme des `Expense.amount` `ACTIVE` selon `expense_date`.
- `net_result` : gross_margin moins expenses.

Le CA n’est ni un encaissement, ni une marge, ni un résultat, ni la caisse. Les mouvements financiers, créances, paiements de dépense, paiements fournisseurs et achats ne participent pas à ces calculs.

Cette vue est courante, pas une clôture comptable : modifier ou annuler ultérieurement une dépense ACTIVE peut modifier un rapport historique recalculé.
