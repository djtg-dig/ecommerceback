# Créances clients

`apps.receivables` reste au Niveau 1 POS. Une créance provient exclusivement d’une Sale terminée partiellement ou totalement impayée et exige donc un Customer. `RC` identifie la créance, `RP` un paiement historique. `original_amount` est le total Sale; `paid_amount` et `balance` sont dérivés des paiements.

Sans `amount_paid`, complete conserve le comportement historique: paiement total et aucune créance. Un paiement partiel crée la créance et le paiement initial; un crédit complet crée une créance OPEN. Les paiements sont des déclarations internes CASH, MOBILE_MONEY, BANK_TRANSFER, CARD ou OTHER: aucune gateway ni caisse n’est intégrée. Les écritures utilisent une transaction et verrouillent la créance pour interdire le surpaiement.

PaymentMethod est défini canoniquement dans `apps.common.choices` et partagé avec Expenses. Ses valeurs restent des déclarations internes, sans intégration de paiement externe.

La devise d’une Receivable est héritée de sa Sale et doit donc correspondre à `Business.primary_currency`.

## Encaissements et idempotence

Chaque `ReceivablePayment` représente un encaissement réel, est immuable et produit atomiquement un unique `FinancialMovement` `RECEIVABLE_PAYMENT`. Le moyen de paiement et l’acteur sont conservés sur le paiement et le mouvement; leurs horodatages métier sont alignés.

`POST .../payments/` accepte optionnellement l’en-tête `Idempotency-Key`. Une répétition avec la même clé et le même payload retourne le paiement existant sans nouvel encaissement. La même clé avec un payload différent répond `409 Conflict`. La clé est persistée et unique par Business. Le verrou `select_for_update()` sur la créance reste en place pour éviter les dépassements du solde.
