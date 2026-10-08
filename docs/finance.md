# Finance — fondation de devise

Chaque Business utilise une seule devise financière, choisie à la création puis immuable. Les montants de Sale, Purchase, Expense et Receivable conservent cette devise comme snapshot historique et doivent correspondre à `Business.primary_currency` lors de leur création.

Le futur ledger `FinancialMovement` suivra la même règle. Finance ne contiendra ni taux de change, ni conversion implicite, ni frais de conversion : ce sujet appartient à un futur domaine séparé.

Une Expense est une charge métier. Le futur domaine distinguera une Expense de son règlement réel (`ExpensePayment`) et du mouvement financier OUTFLOW qui en résultera.

# Finance — Lot 2 : journal financier interne

`FinancialMovement` est un journal append-only interne par `Business`. Il ne remplace ni une intégration bancaire ni une passerelle de paiement. Chaque entrée contient un montant positif, la devise primaire immuable du Business, un sens (`INFLOW` ou `OUTFLOW`), le moyen déclaré, l’événement source, l’horodatage et l’auteur.

Les événements actuellement admis sont `SALE_PAYMENT`, `SALE_RETURN_REFUND`, `RECEIVABLE_PAYMENT`, `EXPENSE_PAYMENT`, `EXPENSE_REVERSAL`, `SUPPLIER_PAYMENT` et `SUPPLIER_PAYMENT_REVERSAL`. Chaque événement non reversal doit référencer exactement une source du type correspondant et de la même entreprise. `ReceivablePayment`, `SaleReturn`, `ExpensePayment` et `SupplierPayment` utilisent des relations uniques vers leur mouvement : une même source ne peut donc pas produire deux écritures équivalentes. Les services métier appellent `create_financial_movement` dans leur transaction et utilisent une clé d’idempotence stable lorsqu’ils peuvent être rejoués.

Une entrée ne se modifie ni ne se supprime. Cette version permet la correction d’un `EXPENSE_PAYMENT` par une unique écriture `EXPENSE_REVERSAL` opposée, avec motif obligatoire; elle ne modifie jamais l’original et interdit les chaînes de corrections.

La consultation est réservée aux OWNER et MANAGER actifs. Les endpoints lecture seule sont :

- `GET /api/v1/businesses/{SH}/financial-movements/`
- `GET /api/v1/businesses/{SH}/financial-movements/{FM}/`
- `GET /api/v1/businesses/{SH}/financial-summary/`

Les listes et le résumé acceptent `direction`, `event_type`, `payment_method`, `date_from` et `date_to` (`YYYY-MM-DD`). Le résumé retourne les totaux d’entrées, sorties, le flux net et le détail par moyen de paiement. Ce flux net est une information de reporting, pas un solde bancaire ni une réconciliation de caisse.

Finance ne crée aucun paiement directement depuis ses endpoints de lecture. Les intégrations automatiques avec Sales, Sale Returns, Receivables, Expenses et Purchases passent par leurs services métier, avec idempotence et transactions atomiques.

Décision préparée pour une évolution ultérieure : une **Expense** décrit une charge métier, un futur **ExpensePayment** décrira son règlement réel, et `FinancialMovement` décrira le mouvement financier de ce règlement. `ExpensePayment` n’existe pas dans ce lot et n’est donc ni créé ni intégré automatiquement.

# Finance — Lot 3 : encaissements Sales et Receivables

Le ledger n’enregistre que l’argent réellement encaissé. Une vente entièrement réglée produit un `SALE_PAYMENT`. Une vente partielle produit une créance, un paiement initial, puis un seul `RECEIVABLE_PAYMENT`; il n’existe pas de `SALE_PAYMENT` concurrent pour cet acompte. Une vente totalement à crédit ne produit aucun mouvement. Chaque paiement ultérieur de créance produit son propre `RECEIVABLE_PAYMENT`.

Sales et Receivables appellent exclusivement `create_financial_movement`; ils ne créent jamais directement un `FinancialMovement`. Toutes les créations concernées sont transactionnelles avec stock, Sale, Receivable et ReceivablePayment. Une Sale complétée reste terminale, mais un remboursement peut désormais être produit par un `SaleReturn`. Le reversal d’un remboursement de vente n’est pas implémenté.

## Remboursements de retours de vente

Après le crédit de la créance, le reliquat économique du retour peut devenir un remboursement. Le service calcule les encaissements réels depuis les `SALE_PAYMENT` de la vente et les `RECEIVABLE_PAYMENT` de sa créance, puis soustrait les `SALE_RETURN_REFUND` déjà effectués. Le montant est :

`refund_amount = min(return_total - receivable_credit_amount, collected_amount - already_refunded_amount)`

La disponibilité remboursable est bornée à zéro : aucun remboursement goodwill et aucun remboursement supérieur aux encaissements n’est possible. Si le résultat est nul, aucun mouvement Finance ni moyen de remboursement n’est requis.

Si le montant est positif, le client doit choisir un `BusinessPaymentMethod` actif appartenant au même Business. Le service crée un unique `FinancialMovement` `SALE_RETURN_REFUND`, `OUTFLOW`, relié par OneToOne au `SaleReturn`, ainsi que sa `PaymentTransaction`. Son `occurred_at` reprend `returned_at`. La création se trouve dans la même transaction que les lignes du retour, Inventory et Receivables; une erreur Finance annule tout le workflow. Aucun `SALE_RETURN_REFUND_REVERSAL` n’existe dans le Lot 1.

Les projections Dashboard, profitability-summary et reports ne sont pas encore ajustées pour retrancher les retours; ce travail appartient au Lot 2.

# Finance — Lot 4 : décaissements Expenses

Une `Expense` est une charge reconnue, sans mouvement de trésorerie implicite. Seul un `ExpensePayment` crée un `EXPENSE_PAYMENT` OUTFLOW, lié au paiement réel. Le reversal d’un paiement ajoute un INFLOW `EXPENSE_REVERSAL` : le ledger conserve donc les deux écritures et son net flow reflète la correction. Les ExpensePayment sont immuables, idempotents par Expense et verrouillent la dépense durant leur création.

## Supplier payments

`SUPPLIER_PAYMENT` est un OUTFLOW lié à SupplierPayment. Son reversal est un `SUPPLIER_PAYMENT_REVERSAL` INFLOW relié à l'écriture originale. Réception fournisseur et paiement sont volontairement deux journaux distincts : Inventory pour les marchandises, Finance pour l'argent.

## Caisse vendeur et synthèse financière

`financial-summary` est la projection de caisse vendeur du ledger `FinancialMovement` : elle agrège les entrées, sorties et net enregistrés dans l'application. Elle ne représente ni wallet, ni compte bancaire, ni solde Mobile Money réel. Les filtres de période utilisent `occurred_at` avec des bornes inclusives. Les mouvements historiques sans `PaymentTransaction` restent dans les totaux et catégories, et apparaissent sous `UNCLASSIFIED` pour la ventilation par mode.
