# Finance — fondation de devise

Chaque Business utilise une seule devise financière, choisie à la création puis immuable. Les montants de Sale, Purchase, Expense et Receivable conservent cette devise comme snapshot historique et doivent correspondre à `Business.primary_currency` lors de leur création.

Le futur ledger `FinancialMovement` suivra la même règle. Finance ne contiendra ni taux de change, ni conversion implicite, ni frais de conversion : ce sujet appartient à un futur domaine séparé.

Une Expense est une charge métier. Le futur domaine distinguera une Expense de son règlement réel (`ExpensePayment`) et du mouvement financier OUTFLOW qui en résultera.
