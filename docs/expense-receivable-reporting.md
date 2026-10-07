# Rapports dépenses et créances

`reports/expenses/` est réservé aux OWNER et MANAGER. Il agrège par période les dépenses `ACTIVE` selon `expense_date`, avec `group_by=day|week|month`. `Expense.amount` est une charge économique complète; `ExpensePayment` est un décaissement et ne crée jamais une charge supplémentaire.

`reports/receivables/` est une vue courante, paginée, des encours clients. Une créance ouverte ancienne reste incluse : `outstanding = original_amount - paiements applicables`. Les créances `PAID` sont exclues et une créance est overdue lorsque sa `due_date` est antérieure à aujourd’hui.

Les deux rapports agrègent côté serveur; le mobile reçoit des payloads compacts, sans dépenses, créances ou paiements bruts.
