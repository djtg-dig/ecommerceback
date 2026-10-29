# ADR-001 — Caisse et facturation

**Statut : proposition à valider; ce document ne constitue pas une décision adoptée.**

## Contexte et problème

Le code utilise une entité `Sale` pour POS et factures. Le POS déduit au paiement total; une facture crée une créance et ne déduit actuellement qu’au premier règlement. Il faut définir si une facture impayée représente une simple demande de paiement, une réservation ou une livraison.

## Options

1. Conserver la déduction au premier paiement : comportement déjà implémenté, simple, mais sans réservation.
2. Déduire à l’émission : allocation garantie, mais nécessite règles d’annulation/restockage.
3. Réserver à l’émission puis déduire à livraison/paiement : reflète une préparation commerciale, mais requiert réservations, expiration et concurrence.

## Recommandation

Conserver l’entité commune et valider l’option 1 ou 3 avant toute évolution. L’option 3 est préférable si la facture engage réellement les produits; l’option 1 si elle n’est qu’une demande de règlement. Ne pas déduire à l’émission sans politique d’annulation et de livraison.

## Conséquences et validations restantes

Backend : conserver verrous, idempotence et écritures append-only; expliciter livraison/réservation. Frontend : présenter séparément document, créance, disponibilité et règlement; ne produire ticket/facture imprimable qu’après confirmation. À décider : réservation, événement de livraison, documents imprimables et durée de vie des brouillons.
