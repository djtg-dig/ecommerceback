# Finance — fondation de devise

Chaque Business utilise une seule devise financière, choisie à la création puis immuable. Les montants de Sale, Purchase, Expense et Receivable conservent cette devise comme snapshot historique et doivent correspondre à `Business.primary_currency` lors de leur création.

Le futur ledger `FinancialMovement` suivra la même règle. Finance ne contiendra ni taux de change, ni conversion implicite, ni frais de conversion : ce sujet appartient à un futur domaine séparé.

Une Expense est une charge métier. Le futur domaine distinguera une Expense de son règlement réel (`ExpensePayment`) et du mouvement financier OUTFLOW qui en résultera.

# Finance — Lot 2 : journal financier interne

`FinancialMovement` est un journal append-only interne par `Business`. Il ne remplace ni une intégration bancaire ni une passerelle de paiement. Chaque entrée contient un montant positif, la devise primaire immuable du Business, un sens (`INFLOW` ou `OUTFLOW`), le moyen déclaré, l’événement source, l’horodatage et l’auteur.

Les événements actuellement admis sont `SALE_PAYMENT`, `RECEIVABLE_PAYMENT`, `EXPENSE_PAYMENT` et `EXPENSE_REVERSAL`. Les trois premiers doivent référencer exactement une source du type correspondant et de la même entreprise. `ReceivablePayment` est relié par une relation unique : un même paiement ne peut donc produire qu’un seul mouvement. Les opérations de création future devront appeler `create_financial_movement`, dans leur transaction métier, avec une clé d’idempotence stable lorsqu’elles peuvent être rejouées.

Une entrée ne se modifie ni ne se supprime. Cette version permet la correction d’un `EXPENSE_PAYMENT` par une unique écriture `EXPENSE_REVERSAL` opposée, avec motif obligatoire; elle ne modifie jamais l’original et interdit les chaînes de corrections.

La consultation est réservée aux OWNER et MANAGER actifs. Les endpoints lecture seule sont :

- `GET /api/v1/businesses/{SH}/financial-movements/`
- `GET /api/v1/businesses/{SH}/financial-movements/{FM}/`
- `GET /api/v1/businesses/{SH}/financial-summary/`

Les listes et le résumé acceptent `direction`, `event_type`, `payment_method`, `date_from` et `date_to` (`YYYY-MM-DD`). Le résumé retourne les totaux d’entrées, sorties, le flux net et le détail par moyen de paiement. Ce flux net est une information de reporting, pas un solde bancaire ni une réconciliation de caisse.

Finance ne crée aucun paiement HTTP dans ce lot. Les intégrations automatiques avec Sales, Receivables, Expenses et Purchases seront ajoutées explicitement dans leurs services, avec tests d’idempotence et transactions atomiques.

Décision préparée pour une évolution ultérieure : une **Expense** décrit une charge métier, un futur **ExpensePayment** décrira son règlement réel, et `FinancialMovement` décrira le mouvement financier de ce règlement. `ExpensePayment` n’existe pas dans ce lot et n’est donc ni créé ni intégré automatiquement.

# Finance — Lot 3 : encaissements Sales et Receivables

Le ledger n’enregistre que l’argent réellement encaissé. Une vente entièrement réglée produit un `SALE_PAYMENT`. Une vente partielle produit une créance, un paiement initial, puis un seul `RECEIVABLE_PAYMENT`; il n’existe pas de `SALE_PAYMENT` concurrent pour cet acompte. Une vente totalement à crédit ne produit aucun mouvement. Chaque paiement ultérieur de créance produit son propre `RECEIVABLE_PAYMENT`.

Sales et Receivables appellent exclusivement `create_financial_movement`; ils ne créent jamais directement un `FinancialMovement`. Toutes les créations concernées sont transactionnelles avec stock, Sale, Receivable et ReceivablePayment. Les remboursements et reversals de ventes ne sont pas implémentés : une Sale complétée reste terminale selon le workflow existant.

# Finance — Lot 4 : décaissements Expenses

Une `Expense` est une charge reconnue, sans mouvement de trésorerie implicite. Seul un `ExpensePayment` crée un `EXPENSE_PAYMENT` OUTFLOW, lié au paiement réel. Le reversal d’un paiement ajoute un INFLOW `EXPENSE_REVERSAL` : le ledger conserve donc les deux écritures et son net flow reflète la correction. Les ExpensePayment sont immuables, idempotents par Expense et verrouillent la dépense durant leur création.
