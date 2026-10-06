# Expenses

## Objectif

`apps.expenses` gère les dépenses opérationnelles internes d'un Business. Il ne gère ni caisse, ni gateway, ni comptabilité, ni paiement Mobile Money réel.

## ExpenseCategory

Une `ExpenseCategory` appartient à un seul Business et est identifiée publiquement par `EC` suivi de 10 caractères. Le code est unique par Business. Les catégories système sont protégées ; les catégories personnalisées peuvent être désactivées avec `is_active=false` plutôt que supprimées. Une catégorie inactive ne peut pas servir à créer ou modifier une Expense.

Les catégories standards sont : `RENT`, `ELECTRICITY`, `WATER`, `INTERNET`, `TRANSPORT`, `SALARY`, `MAINTENANCE`, `SUPPLIES`, `TAX`, `MARKETING` et `OTHER`.

## Initialisation

`create_business` crée le Business, son OWNER et les catégories standards dans la même transaction. Un échec annule l'ensemble. `ensure_default_expense_categories` est idempotent et ne remplace jamais une catégorie existante ayant un code réservé. La migration Expenses `0003` ajoute uniquement les catégories absentes aux Business préexistants.

## Expense

Une Expense porte un identifiant public `EX`, une catégorie, un montant décimal strictement positif, `currency` (`CDF` ou `USD`), `payment_method`, `expense_date`, description et référence optionnelle. La réponse expose aussi les métadonnées d'audit `created_by`, `created_at`, `updated_at`, ainsi que les champs d'annulation. `expense_date` est la date métier et n'est pas nécessairement `created_at`. Aucune conversion monétaire n'est effectuée.

`PaymentMethod` est une classification déclarative partagée avec Receivables : `CASH`, `MOBILE_MONEY`, `BANK_TRANSFER`, `CARD`, `OTHER`. Elle ne contacte aucun opérateur et n'exécute aucune transaction externe.

## Workflow et annulation

Une Expense est créée `ACTIVE`. `POST .../expenses/{EX}/cancel/` applique la seule transition `ACTIVE -> CANCELLED` via `cancel_expense`, qui verrouille la ligne et conserve auteur, date et motif. `CANCELLED` est terminal : une dépense annulée ne se modifie ni ne s'annule une seconde fois.

## Permissions et isolation

OWNER et MANAGER lisent, créent, modifient et annulent. EMPLOYEE lit seulement. Chaque accès est borné au Business de la membership active ; une ressource étrangère répond `404`.

## Filtres

La collection Expenses accepte `category`, `status`, `payment_method`, `currency`, `date_from` et `date_to`. Les dates utilisent `YYYY-MM-DD`; les valeurs invalides répondent `400`.

## Purchase n'est pas Expense

Une Purchase représente l'approvisionnement de marchandises, notamment destinées à la revente. Une Expense représente une charge opérationnelle. Le backend ne convertit jamais automatiquement une Purchase en Expense.

## Limites actuelles

Il n'existe pas encore de caisse, mouvement financier, comptabilité, conversion monétaire, gateway, API Mobile Money, justificatif, pièce jointe ou reporting financier.
