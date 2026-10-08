# Sales — Niveau 1 interne

`apps.sales` gère les ventes internes/POS du commerce, pas des commandes e-commerce. Customer est indépendant de CarriIdentity et une vente peut être anonyme. Sale utilise `SA`, Customer `CU` et SaleLine `SL`.

Une Sale DRAFT peut être modifiée sans changer le stock. COMPLETE verrouille la vente, utilise Inventory pour créer des mouvements `SALE`, retire le stock atomiquement et enregistre prix/coût snapshots; COMPLETED est terminal. CANCEL n’est possible que depuis DRAFT. Chaque `SaleLine` d’une vente `COMPLETED` possède obligatoirement `unit_cost_snapshot` : c’est le coût historique effectif figé lors de la finalisation, jamais recalculé depuis le `cost_price` courant. Il servira ultérieurement au calcul du COGS et de la marge.

`complete` exige `amount_paid`; une dette exige Customer et crée une créance atomiquement.

Les nouvelles ventes utilisent obligatoirement `Business.primary_currency`. Une devise différente envoyée par le client est refusée ; aucune conversion n’est appliquée.

## Encaissement et Finance

La finalisation est désormais explicite : `POST .../complete/` exige `amount_paid`. Si ce montant est positif, `payment_method` est obligatoire et doit être une valeur de `PaymentMethod`; si le montant est zéro, `payment_method` doit être absent. L’ancienne finalisation sans payload est donc refusée afin de ne jamais inventer un paiement CASH.

Une vente entièrement réglée crée un unique `FinancialMovement` `SALE_PAYMENT`. Une vente partielle crée une `Receivable`, puis un `ReceivablePayment` initial et son unique mouvement `RECEIVABLE_PAYMENT`; elle ne crée jamais de `SALE_PAYMENT` pour l’acompte. Une vente à crédit total crée seulement la créance. La finalisation, le stock, les snapshots, la créance, le paiement initial et le mouvement financier partagent une transaction atomique.

## Retours d’une vente terminée

Une vente `COMPLETED` reste terminale et conserve ce statut après un retour. Un `SaleReturn` `POSTED` et ses `SaleReturnLine` sont immuables. Les retours partiels, totaux et successifs sont admis, mais la somme retournée pour une `SaleLine` ne peut jamais dépasser sa quantité vendue. Chaque ligne copie `unit_price` et `unit_cost_snapshot` depuis la `SaleLine` historique : une modification ultérieure du catalogue ne change donc ni le prix, ni le coût, ni le total économique du retour.

La création d’un retour est un workflow unique et atomique : lignes de retour, réintégration Inventory, crédit éventuel de créance et remboursement Finance sont validés puis écrits dans la même transaction. La vente et ses lignes, la créance et les articles Inventory concernés sont verrouillés lorsque nécessaire. Toute erreur annule l’ensemble des effets.

Le service est idempotent par Business. Une même clé et une même intention normalisée retournent le `SaleReturn` existant sans nouvelle ligne, mutation de stock, réduction de créance ou sortie Finance. Réutiliser la clé avec un payload différent produit un conflit.

### API compacte

`POST` et `GET /api/v1/businesses/{business_public_id}/sales/{sale_public_id}/returns/` sont réservés aux OWNER et MANAGER actifs. Le POST exige l’en-tête `Idempotency-Key` et accepte `reason`, `returned_at`, un éventuel `refund_payment_method`, puis une liste de références publiques `SaleLine` et quantités. Le GET est paginé (20 éléments par défaut, `page_size` plafonné à 50) et ne retourne que les retours de la vente demandée.

La réponse expose les identifiants publics, le statut, la date économique `returned_at`, `return_total`, les parts créditées et remboursées, le moyen de remboursement et les snapshots compacts des lignes. Elle n’embarque pas les objets Product, Customer ou Business complets.

### Intégration reporting et limites du MVP

Dashboard, `profitability-summary` et les rapports Sales, Products et Receivables intègrent les retours `POSTED`. Les projections économiques imputent le retour selon `returned_at`, tandis que Finance comptabilise uniquement le remboursement monétaire comme OUTFLOW et que le crédit de créance reste non monétaire.

Le MVP ne propose ni modification, ni suppression, ni annulation d’un retour, ni reversal `SALE_RETURN_REFUND`, ni échange automatique. Les rapports sont des projections recalculées, pas une clôture comptable. Il n’existe pas encore de cache/offline complet pour le client mobile ni d’intégration à une passerelle externe de remboursement.
