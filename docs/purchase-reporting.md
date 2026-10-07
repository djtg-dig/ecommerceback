# Rapports achats et dettes fournisseurs

`reports/purchases/` agrège les achats `RECEIVED` par `received_at`; `confirmed_at` reste la date d'engagement. Les périodes et `group_by=day|week|month` sont traités côté serveur.

`reports/supplier-debts/` est une vue courante des achats `CONFIRMED` et `RECEIVED`, moins les `SupplierPayment` actifs non reversés. Les paiements reversés ne réduisent plus la dette. Les achats sans fournisseur sont inclus avec identifiant et nom `null`. Le classement est paginé, avec `page_size` maximal 50, et réservé aux OWNER/MANAGER.
