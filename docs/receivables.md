# Créances clients

`apps.receivables` reste au Niveau 1 POS. Une créance provient exclusivement d’une Sale terminée partiellement ou totalement impayée et exige donc un Customer. `RC` identifie la créance, `RP` un paiement historique. `original_amount` est le total Sale; `paid_amount` est dérivé des paiements et `balance` soustrait également les ajustements de retour.

`amount_paid` est obligatoire lors de `complete`. Un paiement partiel crée la créance et le paiement initial; un crédit complet crée une créance OPEN. Les paiements sont des déclarations internes CASH, MOBILE_MONEY, BANK_TRANSFER, CARD ou OTHER: aucune gateway ni caisse n’est intégrée. Les écritures utilisent une transaction et verrouillent la créance pour interdire le surpaiement.

PaymentMethod est défini canoniquement dans `apps.common.choices` et partagé avec Expenses. Ses valeurs restent des déclarations internes, sans intégration de paiement externe.

La devise d’une Receivable est héritée de sa Sale et doit donc correspondre à `Business.primary_currency`.

## Encaissements et idempotence

Chaque `ReceivablePayment` représente un encaissement réel, est immuable et produit atomiquement un unique `FinancialMovement` `RECEIVABLE_PAYMENT`. Le moyen de paiement et l’acteur sont conservés sur le paiement et le mouvement; leurs horodatages métier sont alignés.

`POST .../payments/` accepte optionnellement l’en-tête `Idempotency-Key`. Une répétition avec la même clé et le même payload retourne le paiement existant sans nouvel encaissement. La même clé avec un payload différent répond `409 Conflict`. La clé est persistée et unique par Business. Le verrou `select_for_update()` sur la créance reste en place pour éviter les dépassements du solde.

## Crédits de retour

Un retour réduit d’abord le solde encore ouvert de la créance liée à la vente. Le crédit vaut `min(return_total, balance courant)`. S’il est positif, le service crée exactement un `ReceivableAdjustment` immuable de type `RETURN_CREDIT`, relié à la créance et au `SaleReturn`; `SaleReturn.receivable_credit_amount` conserve le même montant.

Le crédit ne modifie jamais `Receivable.original_amount` ni les `ReceivablePayment` historiques. `balance` devient `original_amount - paid_amount - adjusted_amount`, et le statut dérivé reste cohérent : `OPEN` sans encaissement et avec solde, `PARTIALLY_PAID` avec encaissement et solde, `PAID` lorsque le solde atteint zéro. Une vente sans créance ou une créance déjà soldée ne produit aucun ajustement.

Les retours successifs ne créditent que le solde restant. Le retry idempotent ne crée pas de second ajustement. Cette phase partage la transaction du retour avec Inventory et Finance : tout échec annule l’ajustement et les autres effets.
