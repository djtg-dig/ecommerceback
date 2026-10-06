# Sales — Niveau 1 interne

`apps.sales` gère les ventes internes/POS du commerce, pas des commandes e-commerce. Customer est indépendant de CarriIdentity et une vente peut être anonyme. Sale utilise `SA`, Customer `CU` et SaleLine `SL`.

Une Sale DRAFT peut être modifiée sans changer le stock. COMPLETE verrouille la vente, utilise Inventory pour créer des mouvements `SALE`, retire le stock atomiquement et enregistre prix/coût snapshots; COMPLETED est terminal. CANCEL n’est possible que depuis DRAFT. Les prix et coûts snapshots permettent le calcul dérivé de marge `(unit_price - unit_cost_snapshot) * quantity` lorsque le coût est connu.

`complete` accepte `amount_paid` optionnel; une dette exige Customer et crée une créance atomiquement.

Les nouvelles ventes utilisent obligatoirement `Business.primary_currency`. Une devise différente envoyée par le client est refusée ; aucune conversion n’est appliquée.

## Encaissement et Finance

La finalisation est désormais explicite : `POST .../complete/` exige `amount_paid`. Si ce montant est positif, `payment_method` est obligatoire et doit être une valeur de `PaymentMethod`; si le montant est zéro, `payment_method` doit être absent. L’ancienne finalisation sans payload est donc refusée afin de ne jamais inventer un paiement CASH.

Une vente entièrement réglée crée un unique `FinancialMovement` `SALE_PAYMENT`. Une vente partielle crée une `Receivable`, puis un `ReceivablePayment` initial et son unique mouvement `RECEIVABLE_PAYMENT`; elle ne crée jamais de `SALE_PAYMENT` pour l’acompte. Une vente à crédit total crée seulement la créance. La finalisation, le stock, les snapshots, la créance, le paiement initial et le mouvement financier partagent une transaction atomique.
