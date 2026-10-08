# Rapports dépenses et créances

`reports/expenses/` est réservé aux OWNER et MANAGER. Il agrège par période les dépenses `ACTIVE` selon `expense_date`, avec `group_by=day|week|month`. `Expense.amount` est une charge économique complète; `ExpensePayment` est un décaissement et ne crée jamais une charge supplémentaire.

`reports/receivables/` est une vue courante, paginée, des encours regroupés par client. Une créance ouverte ancienne reste incluse. Son solde est calculé par `original_amount - paid_amount - return_credit_amount`, où `paid_amount` agrège exclusivement les `ReceivablePayment` et `return_credit_amount` exclusivement les `ReceivableAdjustment.RETURN_CREDIT`. Un crédit de retour réduit donc la dette sans être présenté comme un encaissement et sans modifier le montant initial ni l'historique des paiements.

Les lignes client exposent séparément les montants initiaux, payés, crédités par retour et encore dus. Le résumé expose le total dû, le total des crédits retour, le nombre de créances ouvertes et le nombre en retard. Les créances `PAID` ou de solde nul sont exclues des impayés. Une créance restante est overdue lorsque sa `due_date` est antérieure à aujourd'hui. Les agrégats paiements et crédits retour utilisent des sous-requêtes indépendantes afin qu'une créance comportant plusieurs éléments de chaque type ne soit pas comptée plusieurs fois.

Les deux rapports agrègent côté serveur; le mobile reçoit des payloads compacts, sans dépenses, créances ou paiements bruts.
