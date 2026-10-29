# ADR-001 — Caisse et facturation

**Statut : adopté.**

## Contexte et problème

Le code utilise une entité `Sale` pour POS et factures. Le POS déduit au paiement total; une facture crée une créance et ne déduit actuellement qu’au premier règlement. Il faut définir si une facture impayée représente une simple demande de paiement, une réservation ou une livraison.

## Options

1. Conserver la déduction au premier paiement : comportement déjà implémenté, simple, mais sans réservation.
2. Déduire à l’émission : allocation garantie, mais nécessite règles d’annulation/restockage.
3. Réserver à l’émission puis déduire à livraison/paiement : reflète une préparation commerciale, mais requiert réservations, expiration et concurrence.

## Décision retenue

Conserver l’entité commune et retenir l’option 1 : une facture impayée est une demande de règlement, pas une réservation ni une livraison. Le stock est contrôlé et déduit une seule fois lors du premier paiement réel. Les paiements suivants ne redéduisent jamais le stock.

## Conséquences et validations restantes

Backend : conserver verrous, idempotence et écritures append-only; l’échec de stock annule la transaction locale, y compris paiement et écriture financière. Cette atomicité ne peut annuler un débit déjà réalisé par un prestataire externe : un futur connecteur devra employer confirmation, idempotence fournisseur et compensation. Frontend : présenter séparément document, créance, disponibilité et règlement; avertir qu’une facture impayée ne réserve pas le stock. Restent à décider : documents imprimables et durée de vie des brouillons.
