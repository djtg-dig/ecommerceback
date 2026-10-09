# P1-A3.1 — Audit des autorisations des API Niveau 1

Date de l'audit : 8 octobre 2026.

## Périmètre et méthode

L'inventaire vient des routes réellement enregistrées sous `/api/v1/`,
recoupées avec le résolveur Django, les vues, les services appelés et le registre
`BusinessMemberPermission.Permission`. Une ligne représente une opération HTTP :
une URL acceptant `GET` et `POST` compte donc deux endpoints d'autorisation.

Statuts utilisés :

- **conforme** : le comportement ne nécessite pas une permission individuelle
  supplémentaire ou utilise déjà la permission exacte ;
- **à migrer** : une permission existante correspond sans ambiguïté, mais la vue
  utilise encore un contrôle direct ou le helper transitoire
  `can_manage_business` ;
- **à clarifier** : le registre actuel ne permet pas d'exprimer le droit sans
  élargir excessivement l'accès.

Les routes d'authentification, de santé, de schéma et d'administration Django ne
font pas partie des domaines métier demandés. Les trois lectures de taxonomies
publiques sont incluses car elles appartiennent aux routes Businesses/Catalog.

## Registre de permissions disponible

L'audit réutilise exclusivement les permissions existantes :

`VIEW_MEMBERS`, `MANAGE_MEMBERS`, `UPDATE_BUSINESS`,
`MANAGE_PAYMENT_METHODS`, `VIEW_CATALOG`, `MANAGE_CATALOG`,
`VIEW_INVENTORY`, `MANAGE_INVENTORY`, `MANAGE_EXPENSE_CATEGORIES`,
`CREATE_EXPENSES`, `VIEW_EXPENSES`, `MANAGE_EXPENSES`, `VIEW_PURCHASES`,
`MANAGE_PURCHASES`, `USE_POS`, `MANAGE_SALES`, `MANAGE_SALE_RETURNS`,
`VIEW_RECEIVABLES`, `MANAGE_RECEIVABLES`, `VIEW_FINANCIAL_SUMMARY`,
`VIEW_DASHBOARD`, `VIEW_PROFITABILITY` et `VIEW_REPORTS`.

## Inventaire complet

### Businesses et référentiels plateforme — 10 opérations

| Méthode | Chemin | Vue ; service | Contrôle actuel | Permission cible | Statut |
|---|---|---|---|---|---|
| GET | `/businesses/` | `BusinessesView`; projection ORM | `accessible`: membership ACTIVE | appartenance active, lecture administrative | conforme |
| POST | `/businesses/` | `BusinessesView`; `create_business` | JWT ; crée son OWNER | aucune permission préalable | conforme |
| GET | `/businesses/{SH}/` | `BusinessDetailView`; projection ORM | `accessible`: membership ACTIVE | appartenance active, lecture administrative | conforme |
| PATCH | `/businesses/{SH}/` | `BusinessDetailView`; serializer, `replace_categories` | `require_permission(..., UPDATE_BUSINESS, write=True)` | `UPDATE_BUSINESS` | conforme — P1-A3.6 |
| GET | `/businesses/{SH}/members/` | `BusinessMembersView`; projection ORM | `require_permission(..., VIEW_MEMBERS)` | `VIEW_MEMBERS` | conforme — P1-A3.6 |
| GET | `/businesses/{SH}/payment-methods/` | `BusinessPaymentMethodsView`; projection ORM | membre actif ; `can_manage_business` révèle aussi les inactifs | permission de lecture absente | à clarifier |
| POST | `/businesses/{SH}/payment-methods/` | `BusinessPaymentMethodsView`; serializer | `require_permission(..., MANAGE_PAYMENT_METHODS, write=True)` | `MANAGE_PAYMENT_METHODS` | conforme — P1-A3.6 |
| GET | `/businesses/{SH}/payment-methods/{PM}/` | `BusinessPaymentMethodDetailView`; projection ORM | membre actif ; `can_manage_business` pour un moyen inactif | permission de lecture absente | à clarifier |
| PATCH | `/businesses/{SH}/payment-methods/{PM}/` | `BusinessPaymentMethodDetailView`; serializer | `require_permission(..., MANAGE_PAYMENT_METHODS, write=True)` | `MANAGE_PAYMENT_METHODS` | conforme — P1-A3.6 |
| GET | `/business-categories/` | `BusinessCategoriesView`; projection ORM | public `AllowAny` | aucune, taxonomie publique | conforme |

Les lectures liste/détail Business sont les informations administratives
minimales qu'un membre actif doit pouvoir consulter. Elles ne donnent aucun
droit métier. `BusinessMembersView` exige désormais `VIEW_MEMBERS` et applique
les erreurs canoniques du moteur centralisé.

### Catalog — 12 opérations

| Méthode | Chemin | Vue ; service | Contrôle actuel | Permission cible | Statut |
|---|---|---|---|---|---|
| GET | `/product-categories/` | `ProductCategoryListView`; queryset | public `AllowAny` | aucune, taxonomie publique | conforme |
| GET | `/product-categories/{code}/attributes/` | `ProductCategoryAttributesView`; `effective_attributes` | public `AllowAny` | aucune, taxonomie publique | conforme |
| GET | `/businesses/{SH}/products/` | `ProductListCreateView`; queryset | `require_permission(..., VIEW_CATALOG)` | `VIEW_CATALOG` | conforme — P1-A3.4 |
| POST | `/businesses/{SH}/products/` | `ProductListCreateView`; `create_product` | `require_permission(..., MANAGE_CATALOG, write=True)` | `MANAGE_CATALOG` | conforme — P1-A3.4 |
| GET | `/businesses/{SH}/products/pos/search/` | `PosSearchView`; agrégations Catalog/Inventory | `require_permission(..., USE_POS)` | `USE_POS` | conforme — P1-A3.4 |
| GET | `/businesses/{SH}/products/{PR}/` | `ProductDetailView`; queryset | `require_permission(..., VIEW_CATALOG)` | `VIEW_CATALOG` | conforme — P1-A3.4 |
| PATCH | `/businesses/{SH}/products/{PR}/` | `ProductDetailView`; serializer | `require_permission(..., MANAGE_CATALOG, write=True)` | `MANAGE_CATALOG` | conforme — P1-A3.4 |
| POST | `/businesses/{SH}/products/{PR}/archive/` | `ProductArchiveView`; modèle | `require_permission(..., MANAGE_CATALOG, write=True)` | `MANAGE_CATALOG` | conforme — P1-A3.4 |
| GET | `/businesses/{SH}/products/{PR}/variants/` | `ProductVariantListCreateView`; queryset | `require_permission(..., VIEW_CATALOG)` | `VIEW_CATALOG` | conforme — P1-A3.4 |
| POST | `/businesses/{SH}/products/{PR}/variants/` | `ProductVariantListCreateView`; `ensure_can_create_variant`, `create_variant` | `require_permission(..., MANAGE_CATALOG, write=True)` | `MANAGE_CATALOG` | conforme — P1-A3.4 |
| GET | `/businesses/{SH}/products/{PR}/variants/{PV}/` | `ProductVariantDetailView`; queryset | `require_permission(..., VIEW_CATALOG)` | `VIEW_CATALOG` | conforme — P1-A3.4 |
| PATCH | `/businesses/{SH}/products/{PR}/variants/{PV}/` | `ProductVariantDetailView`; serializer | `require_permission(..., MANAGE_CATALOG, write=True)` | `MANAGE_CATALOG` | conforme — P1-A3.4 |

### Inventory — 5 opérations

| Méthode | Chemin | Vue ; service | Contrôle actuel | Permission cible | Statut |
|---|---|---|---|---|---|
| GET | `/businesses/{SH}/inventory/` | `InventoryListCreateView`; queryset | `require_permission(..., VIEW_INVENTORY)` | `VIEW_INVENTORY` | conforme — P1-A3.4 |
| POST | `/businesses/{SH}/inventory/` | `InventoryListCreateView`; `create_inventory_item` | `require_permission(..., MANAGE_INVENTORY, write=True)` | `MANAGE_INVENTORY` | conforme — P1-A3.4 |
| GET | `/businesses/{SH}/inventory/{IV}/` | `InventoryDetailView`; queryset | `require_permission(..., VIEW_INVENTORY)` | `VIEW_INVENTORY` | conforme — P1-A3.4 |
| GET | `/businesses/{SH}/inventory/{IV}/movements/` | `StockMovementListCreateView`; queryset | `require_permission(..., VIEW_INVENTORY)` | `VIEW_INVENTORY` | conforme — P1-A3.4 |
| POST | `/businesses/{SH}/inventory/{IV}/movements/` | `StockMovementListCreateView`; `apply_stock_movement` | `require_permission(..., MANAGE_INVENTORY, write=True)` | `MANAGE_INVENTORY` | conforme — P1-A3.4 |

### Purchases et fournisseurs — 19 opérations

| Méthode | Chemin | Vue ; service | Contrôle actuel | Permission cible | Statut |
|---|---|---|---|---|---|
| GET | `/businesses/{SH}/suppliers/` | `Suppliers`; queryset | `require_permission(..., VIEW_PURCHASES)` | `VIEW_PURCHASES` | conforme — P1-A3.3 |
| POST | `/businesses/{SH}/suppliers/` | `Suppliers`; serializer | `require_permission(..., MANAGE_PURCHASES, write=True)` | `MANAGE_PURCHASES` | conforme — P1-A3.3 |
| GET | `/businesses/{SH}/suppliers/{SU}/` | `SupplierDetail`; queryset | `require_permission(..., VIEW_PURCHASES)` | `VIEW_PURCHASES` | conforme — P1-A3.3 |
| PATCH | `/businesses/{SH}/suppliers/{SU}/` | `SupplierDetail`; serializer | `require_permission(..., MANAGE_PURCHASES, write=True)` | `MANAGE_PURCHASES` | conforme — P1-A3.3 |
| GET | `/businesses/{SH}/purchases/` | `Purchases`; queryset | `require_permission(..., VIEW_PURCHASES)` | `VIEW_PURCHASES` | conforme — P1-A3.3 |
| POST | `/businesses/{SH}/purchases/` | `Purchases`; serializer | `require_permission(..., MANAGE_PURCHASES, write=True)` | `MANAGE_PURCHASES` | conforme — P1-A3.3 |
| GET | `/businesses/{SH}/purchases/{PU}/` | `PurchaseDetail`; queryset | `require_permission(..., VIEW_PURCHASES)` | `VIEW_PURCHASES` | conforme — P1-A3.3 |
| PATCH | `/businesses/{SH}/purchases/{PU}/` | `PurchaseDetail`; serializer | `require_permission(..., MANAGE_PURCHASES, write=True)` | `MANAGE_PURCHASES` | conforme — P1-A3.3 |
| GET | `/businesses/{SH}/purchases/{PU}/lines/` | `Lines`; queryset | `require_permission(..., VIEW_PURCHASES)` | `VIEW_PURCHASES` | conforme — P1-A3.3 |
| POST | `/businesses/{SH}/purchases/{PU}/lines/` | `Lines`; modèle | `require_permission(..., MANAGE_PURCHASES, write=True)` | `MANAGE_PURCHASES` | conforme — P1-A3.3 |
| GET | `/businesses/{SH}/purchases/{PU}/lines/{PL}/` | `LineDetail`; queryset | `require_permission(..., VIEW_PURCHASES)` | `VIEW_PURCHASES` | conforme — P1-A3.3 |
| PATCH | `/businesses/{SH}/purchases/{PU}/lines/{PL}/` | `LineDetail`; serializer/modèle | `require_permission(..., MANAGE_PURCHASES, write=True)` | `MANAGE_PURCHASES` | conforme — P1-A3.3 |
| DELETE | `/businesses/{SH}/purchases/{PU}/lines/{PL}/` | `LineDetail`; modèle | `require_permission(..., MANAGE_PURCHASES, write=True)` | `MANAGE_PURCHASES` | conforme — P1-A3.3 |
| POST | `/businesses/{SH}/purchases/{PU}/confirm/` | `Confirm`; `transition` | `require_permission(..., MANAGE_PURCHASES, write=True)` | `MANAGE_PURCHASES` | conforme — P1-A3.3 |
| POST | `/businesses/{SH}/purchases/{PU}/receive/` | `Receive`; `receive_purchase` | `require_permission(..., MANAGE_PURCHASES, write=True)` | `MANAGE_PURCHASES` | conforme — P1-A3.3 |
| POST | `/businesses/{SH}/purchases/{PU}/cancel/` | `Cancel`; `transition` | `require_permission(..., MANAGE_PURCHASES, write=True)` | `MANAGE_PURCHASES` | conforme — P1-A3.3 |
| GET | `/businesses/{SH}/purchases/{PU}/payments/` | `PurchasePayments`; queryset | `require_permission(..., VIEW_PURCHASES)` | `VIEW_PURCHASES` | conforme — P1-A3.3 |
| POST | `/businesses/{SH}/purchases/{PU}/payments/` | `PurchasePayments`; `add_supplier_payment` | `require_permission(..., MANAGE_PURCHASES, write=True)` | `MANAGE_PURCHASES` | conforme — P1-A3.3 |
| POST | `/businesses/{SH}/purchases/{PU}/payments/{PP}/reverse/` | `SupplierPaymentReverse`; `reverse_supplier_payment` | `require_permission(..., MANAGE_PURCHASES, write=True)` | `MANAGE_PURCHASES` | conforme — P1-A3.3 |

### Sales, clients et retours — 12 opérations

| Méthode | Chemin | Vue ; service | Contrôle actuel | Permission cible | Statut |
|---|---|---|---|---|---|
| GET | `/businesses/{SH}/customers/` | `Customers`; queryset | membership ACTIVE direct | permission de lecture clients absente | à clarifier |
| POST | `/businesses/{SH}/customers/` | `Customers`; serializer | membership ACTIVE uniquement | permission de gestion clients absente | à clarifier |
| GET | `/businesses/{SH}/sales/` | `Sales`; queryset | membership ACTIVE direct | permission de lecture ventes absente | à clarifier |
| POST | `/businesses/{SH}/sales/` | `Sales`; serializer | `require_permission(..., USE_POS, write=True)` | `USE_POS` | conforme — P1-A3.2 |
| GET | `/businesses/{SH}/sales/{SA}/` | `SD`; queryset | membership ACTIVE direct | permission de lecture ventes absente | à clarifier |
| PATCH | `/businesses/{SH}/sales/{SA}/` | `SD`; serializer | `require_permission(..., USE_POS, write=True)` | `USE_POS` | conforme — P1-A3.2 |
| GET | `/businesses/{SH}/sales/{SA}/lines/` | `Lines`; queryset | membership ACTIVE direct | permission de lecture ventes absente | à clarifier |
| POST | `/businesses/{SH}/sales/{SA}/lines/` | `Lines`; modèle | `require_permission(..., USE_POS, write=True)` | `USE_POS` | conforme — P1-A3.2 |
| POST | `/businesses/{SH}/sales/{SA}/complete/` | `Complete`; `complete` | `require_permission(..., USE_POS, write=True)` | `USE_POS` | conforme — P1-A3.2 |
| POST | `/businesses/{SH}/sales/{SA}/cancel/` | `Cancel`; `cancel` | `require_permission(..., MANAGE_SALES, write=True)` | `MANAGE_SALES` | conforme — P1-A3.2 |
| GET | `/businesses/{SH}/sales/{SA}/returns/` | `SaleReturns`; queryset | `require_permission(..., MANAGE_SALE_RETURNS)` | `MANAGE_SALE_RETURNS` | conforme — P1-A3.2 |
| POST | `/businesses/{SH}/sales/{SA}/returns/` | `SaleReturns`; `create_sale_return` | `require_permission(..., MANAGE_SALE_RETURNS, write=True)` | `MANAGE_SALE_RETURNS` | conforme — P1-A3.2 |

`USE_POS` convient aux mutations du ticket courant. Il ne suffit pas à justifier
une lecture globale de toutes les ventes historiques, d'où la décision requise
pour les trois GET Sales. De même, rattacher toute gestion client à `USE_POS`
donnerait au vendeur des droits de référentiel non explicitement décidés.

### Receivables — 5 opérations

| Méthode | Chemin | Vue ; service | Contrôle actuel | Permission cible | Statut |
|---|---|---|---|---|---|
| GET | `/businesses/{SH}/receivables/` | `ReceivableListView`; queryset | `require_permission(..., VIEW_RECEIVABLES)` | `VIEW_RECEIVABLES` | conforme — P1-A3.6 |
| GET | `/businesses/{SH}/receivables/{RE}/` | `ReceivableDetailView`; queryset | `require_permission(..., VIEW_RECEIVABLES)` | `VIEW_RECEIVABLES` | conforme — P1-A3.6 |
| PATCH | `/businesses/{SH}/receivables/{RE}/` | `ReceivableDetailView`; modèle | `require_permission(..., MANAGE_RECEIVABLES, write=True)` | `MANAGE_RECEIVABLES` | conforme — P1-A3.2 |
| GET | `/businesses/{SH}/receivables/{RE}/payments/` | `ReceivablePaymentsView`; queryset | `require_permission(..., VIEW_RECEIVABLES)` | `VIEW_RECEIVABLES` | conforme — P1-A3.6 |
| POST | `/businesses/{SH}/receivables/{RE}/payments/` | `ReceivablePaymentsView`; `add_payment` | `require_permission(..., MANAGE_RECEIVABLES, write=True)` | `MANAGE_RECEIVABLES` | conforme — P1-A3.2 |

### Expenses — 12 opérations

| Méthode | Chemin | Vue ; service | Contrôle actuel | Permission cible | Statut |
|---|---|---|---|---|---|
| GET | `/businesses/{SH}/expense-categories/` | `Categories`; queryset | `require_permission(..., VIEW_EXPENSES)` | `VIEW_EXPENSES` | conforme — P1-A3.3 |
| POST | `/businesses/{SH}/expense-categories/` | `Categories`; modèle | `require_permission(..., MANAGE_EXPENSE_CATEGORIES, write=True)` | `MANAGE_EXPENSE_CATEGORIES` | conforme — P1-A3.3 |
| GET | `/businesses/{SH}/expense-categories/{EC}/` | `CategoryDetail`; queryset | `require_permission(..., VIEW_EXPENSES)` | `VIEW_EXPENSES` | conforme — P1-A3.3 |
| PATCH | `/businesses/{SH}/expense-categories/{EC}/` | `CategoryDetail`; modèle | `require_permission(..., MANAGE_EXPENSE_CATEGORIES, write=True)` | `MANAGE_EXPENSE_CATEGORIES` | conforme — P1-A3.3 |
| GET | `/businesses/{SH}/expenses/` | `Expenses`; queryset | `require_permission(..., VIEW_EXPENSES)` | `VIEW_EXPENSES` | conforme — P1-A3.3 |
| POST | `/businesses/{SH}/expenses/` | `Expenses`; modèle | `require_permission(..., CREATE_EXPENSES, write=True)` | `CREATE_EXPENSES` | conforme — P1-A3.3 |
| GET | `/businesses/{SH}/expenses/{EX}/` | `ExpenseDetail`; queryset | `require_permission(..., VIEW_EXPENSES)` | `VIEW_EXPENSES` | conforme — P1-A3.3 |
| PATCH | `/businesses/{SH}/expenses/{EX}/` | `ExpenseDetail`; `update_expense` | `require_permission(..., MANAGE_EXPENSES, write=True)` | `MANAGE_EXPENSES` | conforme — P1-A3.3 |
| POST | `/businesses/{SH}/expenses/{EX}/cancel/` | `ExpenseCancel`; `cancel_expense` | `require_permission(..., MANAGE_EXPENSES, write=True)` | `MANAGE_EXPENSES` | conforme — P1-A3.3 |
| GET | `/businesses/{SH}/expenses/{EX}/payments/` | `ExpensePayments`; queryset | `require_permission(..., VIEW_EXPENSES)` | `VIEW_EXPENSES` | conforme — P1-A3.3 |
| POST | `/businesses/{SH}/expenses/{EX}/payments/` | `ExpensePayments`; `add_expense_payment` | `require_permission(..., MANAGE_EXPENSES, write=True)` | `MANAGE_EXPENSES` | conforme — P1-A3.3 |
| POST | `/businesses/{SH}/expenses/{EX}/payments/{EP}/reverse/` | `ExpensePaymentReverse`; `reverse_expense_payment` | `require_permission(..., MANAGE_EXPENSES, write=True)` | `MANAGE_EXPENSES` | conforme — P1-A3.3 |

### Finance — 3 opérations

| Méthode | Chemin | Vue ; service | Contrôle actuel | Permission cible | Statut |
|---|---|---|---|---|---|
| GET | `/businesses/{SH}/financial-movements/` | `FinancialMovementListView`; queryset | `require_permission(..., VIEW_FINANCIAL_SUMMARY)` | `VIEW_FINANCIAL_SUMMARY` | conforme — P1-A3.5 |
| GET | `/businesses/{SH}/financial-movements/{FM}/` | `FinancialMovementDetailView`; queryset | `require_permission(..., VIEW_FINANCIAL_SUMMARY)` | `VIEW_FINANCIAL_SUMMARY` | conforme — P1-A3.5 |
| GET | `/businesses/{SH}/financial-summary/` | `FinancialSummaryView`; `financial_summary` | `require_permission(..., VIEW_FINANCIAL_SUMMARY)` | `VIEW_FINANCIAL_SUMMARY` | conforme — P1-A3.5 |

### Dashboard, rentabilité et rapports — 8 opérations

| Méthode | Chemin | Vue ; service | Contrôle actuel | Permission cible | Statut |
|---|---|---|---|---|---|
| GET | `/businesses/{SH}/dashboard/` | `DashboardView`; `build_dashboard` | `require_permission(..., VIEW_DASHBOARD)` | `VIEW_DASHBOARD` | conforme — P1-A3.5 |
| GET | `/businesses/{SH}/profitability-summary/` | `ProfitabilitySummaryView`; `build_profitability_summary` | `require_permission(..., VIEW_PROFITABILITY)` | `VIEW_PROFITABILITY` | conforme — P1-A3.5 |
| GET | `/businesses/{SH}/reports/sales/` | `SalesReportView`; `build_sales_series` | `require_permission(..., VIEW_REPORTS)` | `VIEW_REPORTS` | conforme — P1-A3.5 |
| GET | `/businesses/{SH}/reports/products/` | `ProductReportView`; `build_product_top` | `require_permission(..., VIEW_REPORTS)` | `VIEW_REPORTS` | conforme — P1-A3.5 |
| GET | `/businesses/{SH}/reports/expenses/` | `ExpensesReportView`; `build_expenses_report` | `require_permission(..., VIEW_REPORTS)` | `VIEW_REPORTS` | conforme — P1-A3.5 |
| GET | `/businesses/{SH}/reports/receivables/` | `ReceivablesReportView`; agrégations | `require_permission(..., VIEW_REPORTS)` | `VIEW_REPORTS` | conforme — P1-A3.5 |
| GET | `/businesses/{SH}/reports/purchases/` | `PurchasesReportView`; `build_purchases_report` | `require_permission(..., VIEW_REPORTS)` | `VIEW_REPORTS` | conforme — P1-A3.5 |
| GET | `/businesses/{SH}/reports/supplier-debts/` | `SupplierDebtsReportView`; `debt_queryset` | `require_permission(..., VIEW_REPORTS)` | `VIEW_REPORTS` | conforme — P1-A3.5 |

## Synthèse chiffrée

| Statut | Opérations |
|---|---:|
| Conforme | 79 |
| À migrer | 0 |
| À clarifier | 7 |
| **Total** | **86** |

## P1-A3.6 — classement des opérations restantes

### Opérations migrées avec les permissions existantes

| Méthode et endpoint | Permission | Autorisation avant P1-A3.6 | Risque corrigé et décision |
|---|---|---|---|
| `PATCH /businesses/{SH}/` | `UPDATE_BUSINESS` | `can_manage_business` | Un contrôle transitoire masquait la permission attendue. Migration vers `require_permission(..., write=True)`. |
| `GET /businesses/{SH}/members/` | `VIEW_MEMBERS` | `can_view_members` | La lecture des membres dépend maintenant exclusivement de la permission individuelle dédiée. |
| `POST /businesses/{SH}/payment-methods/` | `MANAGE_PAYMENT_METHODS` | `can_manage_business` | `UPDATE_BUSINESS` accordait indirectement une capacité financière distincte. Migration vers la permission dédiée avec `write=True`. |
| `PATCH /businesses/{SH}/payment-methods/{PM}/` | `MANAGE_PAYMENT_METHODS` | `can_manage_business` | Même risque de privilège indirect ; la mutation utilise maintenant le moteur centralisé et `write=True`. |
| `GET /businesses/{SH}/receivables/` | `VIEW_RECEIVABLES` | appartenance active directe | Tout membre actif pouvait lire les créances. La permission individuelle dédiée est désormais exigée. |
| `GET /businesses/{SH}/receivables/{RE}/` | `VIEW_RECEIVABLES` | appartenance active directe | La lecture détaillée sensible est désormais protégée et conserve l'isolation par Business. |
| `GET /businesses/{SH}/receivables/{RE}/payments/` | `VIEW_RECEIVABLES` | appartenance active directe | L'historique des encaissements n'est plus exposé aux membres sans droit explicite. |

Pour ces sept opérations, l'OWNER actif conserve l'accès total, une permission
explicite est nécessaire aux autres membres, un membre suspendu reçoit 403 et
un utilisateur sans appartenance reçoit 404. Les écritures sont refusées sur
un Business suspendu ou archivé ; les lectures administratives autorisées par
la politique P1-A2 restent disponibles aux membres habilités.

### Opérations analysées nécessitant un arbitrage

| Méthode et endpoint | Permission attendue | Autorisation actuelle | Risque et décision |
|---|---|---|---|
| `GET /businesses/{SH}/payment-methods/` | droit de lecture des moyens de paiement, absent | membre actif ; `can_manage_business` pour inclure les inactifs | `UPDATE_BUSINESS` reste indirectement lié à la visibilité des références inactives. Ne pas migrer vers une permission sans rapport ; arbitrage requis. |
| `GET /businesses/{SH}/payment-methods/{PM}/` | même droit de lecture, absent | membre actif ; `can_manage_business` pour un moyen inactif | Même risque et même arbitrage que la liste. |
| `GET /businesses/{SH}/customers/` | droit de lecture des clients, absent | appartenance active directe | Tous les membres actifs lisent le référentiel client. Arbitrage requis avant restriction. |
| `POST /businesses/{SH}/customers/` | droit de gestion des clients, absent | appartenance active directe | Tout membre actif peut modifier le référentiel par création. Risque critique ; arbitrage requis. |
| `GET /businesses/{SH}/sales/` | droit de lecture globale des ventes, absent | appartenance active directe | Tout membre actif lit l'historique commercial. Arbitrage requis. |
| `GET /businesses/{SH}/sales/{SA}/` | même droit de lecture, absent | appartenance active directe | Exposition du détail d'une vente à tout membre actif. Arbitrage requis. |
| `GET /businesses/{SH}/sales/{SA}/lines/` | même droit de lecture, absent | appartenance active directe | Exposition des lignes et prix historiques à tout membre actif. Arbitrage requis. |

Ces sept opérations sont **clarifiées techniquement mais non arbitrées**. Leur
comportement actuel est conservé afin de ne pas remplacer une décision métier
manquante par `UPDATE_BUSINESS`, `USE_POS` ou une autre permission trop large.

## Contrôles legacy et dupliqués

Quatre familles de contrôles doivent disparaître progressivement des vues :

1. `can_manage_business`, helper transitoire fondé sur `UPDATE_BUSINESS`, reste
   utilisé par les 2 lectures de moyens de paiement à clarifier pour décider si
   les moyens inactifs sont visibles ;
2. les recherches directes `members__identity` + `members__status="ACTIVE"`
   sont répétées dans presque chaque mixin et contournent `membership_for` /
   `require_permission` ;
3. les 7 opérations ambiguës restent volontairement hors du moteur granulaire
   tant que leurs 4 permissions métier ne sont pas arbitrées ;
4. chaque domaine fabrique manuellement ses réponses `Forbidden`/`Not found`,
   parfois en renvoyant 404 pour une permission absente et parfois 403.

Aucune comparaison applicative `role == OWNER`, `role == MANAGER`,
`role in (...)` ou équivalent n'a été trouvée hors modèles, migrations, admin et
tests. Un ancien MANAGER ne récupère donc aucun droit du fait de son rôle. Il
peut toutefois utiliser les opérations protégées par la seule appartenance
active, exactement comme tout membre sans permission.

Les services métier des domaines Catalog, Inventory, Purchases, Sales,
Receivables, Expenses et Finance valident leurs invariants métier mais ne
réévaluent généralement pas `BusinessMemberPermission`. L'autorisation repose
donc sur la vue appelante. Ce choix impose que chaque vue migre avant qu'un
service sensible ne soit exposé par un nouveau point d'entrée.

## Permissions manquantes — quatre décisions requises

### 1. Lecture des moyens de paiement

Le POS et les flux financiers ont besoin de références actives, tandis que la
consultation des références inactives relève de l'administration. Les endpoints
concernés sont les deux `GET /payment-methods/` ci-dessus.

Options : conserver la lecture des références actives à tout membre actif ;
ajouter une permission dédiée `VIEW_PAYMENT_METHODS` et réserver les inactives
à `MANAGE_PAYMENT_METHODS` ; ou coupler artificiellement la lecture à `USE_POS`
ou à une permission financière. La recommandation est une permission de lecture
dédiée, avec `MANAGE_PAYMENT_METHODS` pour les références inactives. Elle exige
une décision de registre, une migration et l'attribution explicite du nouveau
droit. La décision bloque la centralisation des deux opérations.

### 2. Lecture des clients

`GET /customers/` expose le référentiel client complet. Les options sont de
maintenir cette lecture pour tout membre actif, de la rattacher à `USE_POS`, ou
d'ajouter un droit de lecture dédié. La recommandation est `VIEW_CUSTOMERS`, car
un lecteur de clientèle n'a pas nécessairement le droit d'encaisser et un
caissier n'a pas nécessairement besoin d'une extraction globale. Ce choix exige
une migration et des attributions explicites ; il bloque une opération.

### 3. Gestion des clients

`POST /customers/` est nécessaire à certains parcours de vente, mais modifie un
référentiel partagé. Les options sont de décider explicitement que `USE_POS`
inclut la création, d'utiliser `MANAGE_SALES`, ou de créer une capacité dédiée.
La recommandation est `MANAGE_CUSTOMERS`, sauf décision produit explicite de
faire de la création client une fonction POS. Cette décision modifie le registre
et les profils à attribuer ; elle bloque une opération et constitue le risque
résiduel le plus élevé.

### 4. Lecture globale des ventes

`GET /sales/`, `GET /sales/{SA}/` et `GET /sales/{SA}/lines/` lisent l'historique
commercial. Les options sont `USE_POS`, `MANAGE_SALES`, ou un droit de lecture
dédié. La recommandation est `VIEW_SALES` : `USE_POS` serait trop large en
lecture historique et `MANAGE_SALES` accorderait des mutations inutiles. Le
nouveau droit implique une migration et des attributions explicites ; la
décision bloque trois opérations.

Les noms recommandés décrivent les capacités à arbitrer. P1-A3.6 ne les ajoute
ni au modèle ni à une migration et ne réutilise pas `UPDATE_BUSINESS` comme
permission générique.

## Analyse de sécurité

### Garanties déjà présentes

- l'OWNER actif obtient toutes les permissions enregistrées via P1-A2 ;
- les titres et le champ legacy `role` ne sont consultés par aucune décision
  d'autorisation ;
- les querysets d'objets sont systématiquement rattachés au Business résolu,
  ce qui protège l'isolation tenant sur les routes examinées ;
- les membres suspendus sont exclus par les scopes actuels ;
- `can_manage_business` appelle désormais le moteur avec `write=True`, donc les
  opérations qui l'utilisent sont bloquées sur un Business suspendu ou archivé.

### Risques critiques

1. **Création de client sans permission — restant** : le POST Customer est
   accessible à tout membre actif, faute de permission de gestion client
   décidée. Les autres mutations Sales sont corrigées par P1-A3.2.
2. **Encaissement Receivable sans permission — corrigé P1-A3.2** : le POST
   paiement exige désormais `MANAGE_RECEIVABLES` avant `add_payment`.
3. **Business inactif mutable — corrigé pour P1-A3.2** : les neuf opérations
   migrées utilisent `write=True` pour leurs mutations ; `SUSPENDED` et
   `ARCHIVED` sont refusés.
4. **Lecture sensible trop large — partiellement corrigée P1-A3.6** : les
   créances exigent désormais `VIEW_RECEIVABLES`. Tout membre actif peut encore
   lire clients et ventes, faute de permissions de lecture arbitrées.

### Cohérence 403/404

Le moteur P1-A2 définit : absence de membership = 404 ; membership existant mais
non autorisé ou suspendu = 403. Les vues Sales/Receivables migrées en P1-A3.2 et
Purchases/Expenses migrées en P1-A3.3, Catalog/Inventory migrées en P1-A3.4 et
les projections financières migrées en P1-A3.5 ainsi que l'administration et
les lectures Receivables migrées en P1-A3.6 appliquent désormais cette
distinction en résolvant d'abord le Business puis en appelant
`require_permission`. Les 7 opérations en attente d'arbitrage restent à
harmoniser.

## Matrice fonctionnelle condensée

| Domaine / opération | Permission existante retenue |
|---|---|
| Modifier Business | `UPDATE_BUSINESS` |
| Consulter membres | `VIEW_MEMBERS` |
| Gérer moyens de paiement | `MANAGE_PAYMENT_METHODS` |
| Lire / gérer catalogue | `VIEW_CATALOG` / `MANAGE_CATALOG` |
| Rechercher au POS | `USE_POS` |
| Lire / gérer inventaire | `VIEW_INVENTORY` / `MANAGE_INVENTORY` |
| Lire / gérer achats, fournisseurs et règlements | `VIEW_PURCHASES` / `MANAGE_PURCHASES` |
| Créer/éditer/compléter un ticket POS | `USE_POS` |
| Annuler/gérer une vente | `MANAGE_SALES` |
| Lire/créer un retour | `MANAGE_SALE_RETURNS` |
| Lire / gérer créances et encaissements | `VIEW_RECEIVABLES` / `MANAGE_RECEIVABLES` |
| Lire dépenses | `VIEW_EXPENSES` |
| Créer dépense | `CREATE_EXPENSES` |
| Gérer catégories de dépense | `MANAGE_EXPENSE_CATEGORIES` |
| Modifier/annuler/régler/reverser dépense | `MANAGE_EXPENSES` |
| Lire journal et synthèse Finance | `VIEW_FINANCIAL_SUMMARY` |
| Dashboard | `VIEW_DASHBOARD` |
| Rentabilité | `VIEW_PROFITABILITY` |
| Tous les rapports `/reports/*` | `VIEW_REPORTS` |

## Plan de migration recommandé

### P1-A3.2 — Sales et Receivables critiques — terminé

Migrer d'abord les mutations `USE_POS`, `MANAGE_SALES`,
`MANAGE_SALE_RETURNS` et `MANAGE_RECEIVABLES`. Tester les effets Stock,
Receivable et Finance, l'idempotence, les Business inactifs et les 403/404.
Décider séparément les permissions de lecture Sales/Customers avant d'ouvrir ces
GET à autre chose qu'une politique explicitement validée.

Endpoints effectivement migrés :

- `POST /sales/`, `PATCH /sales/{SA}/`, `POST /sales/{SA}/lines/` et
  `POST /sales/{SA}/complete/` vers `USE_POS` ;
- `POST /sales/{SA}/cancel/` vers `MANAGE_SALES` ;
- `GET/POST /sales/{SA}/returns/` vers `MANAGE_SALE_RETURNS` ;
- `PATCH /receivables/{RE}/` et `POST /receivables/{RE}/payments/` vers
  `MANAGE_RECEIVABLES`.

Les mutations utilisent `write=True`, donc un Business suspendu ou archivé est
refusé. Les tests couvrent OWNER, ancien MANAGER sans permission, permission
explicite, révocation implicite des droits liés au titre, membre suspendu,
isolation tenant et invariants transactionnels existants. `POST /customers/`
reste volontairement inchangé jusqu'à la décision sur `MANAGE_CUSTOMERS`.

### P1-A3.3 — Expenses et Purchases financiers — terminé

Migrer lectures, écritures, paiements et reversals vers leurs permissions
granulaires. Vérifier que les services transactionnels ne sont appelés qu'après
autorisation et que les historiques financiers restent inchangés.

Endpoints effectivement migrés :

- les 4 opérations fournisseurs et les 15 opérations achats, lignes,
  transitions, règlements et reversals utilisent respectivement
  `VIEW_PURCHASES` et `MANAGE_PURCHASES` ;
- les 5 lectures dépenses/catégories/règlements utilisent `VIEW_EXPENSES` ;
- la création de dépense utilise `CREATE_EXPENSES`, les 2 mutations de
  catégories utilisent `MANAGE_EXPENSE_CATEGORIES` et les 4 autres mutations
  dépenses/règlements utilisent `MANAGE_EXPENSES`.

Toutes les mutations utilisent `write=True`, donc elles sont refusées sur un
Business suspendu ou archivé. Les tests couvrent l'OWNER, l'ancien MANAGER sans
permission, les permissions explicites et indépendantes, le membre suspendu,
l'isolation tenant et les statuts inactifs du Business. Aucun service
transactionnel ni historique financier n'a été modifié.

### P1-A3.4 — Catalog, POS search et Inventory — terminé

Remplacer les mixins dupliqués par le moteur central, distinguer
`VIEW_CATALOG`, `MANAGE_CATALOG`, `USE_POS`, `VIEW_INVENTORY` et
`MANAGE_INVENTORY`, puis tester produits archivés et isolation Business.

Endpoints effectivement migrés :

- les 4 lectures produits/variantes utilisent `VIEW_CATALOG` et les 5 mutations
  produits/variantes utilisent `MANAGE_CATALOG` avec `write=True` ;
- la recherche compacte POS utilise exclusivement `USE_POS` ;
- les 3 lectures Inventory/StockMovement utilisent `VIEW_INVENTORY` et les 2
  créations utilisent `MANAGE_INVENTORY` avec `write=True`.

Les tests couvrent l'OWNER, l'ancien MANAGER sans droit implicite, chacune des
permissions explicites, le membre suspendu, l'isolation tenant et les Business
suspendus ou archivés. Les règles existantes des produits archivés sont
préservées. Le coût SQL de l'autorisation POS ajoute deux requêtes fixes, sans
N+1 : le nombre de requêtes reste identique entre petit et grand jeux de données.

### P1-A3.5 — Finance, Dashboard, rentabilité et rapports — terminé

Remplacer `UPDATE_BUSINESS` par les permissions de lecture dédiées. Tester chaque
projection, l'absence de fuite financière, les périodes et le comportement des
Business inactifs.

Endpoints effectivement migrés :

- les 3 lectures du journal et de la synthèse Finance utilisent
  `VIEW_FINANCIAL_SUMMARY` ;
- Dashboard utilise `VIEW_DASHBOARD` et la synthèse de rentabilité utilise
  `VIEW_PROFITABILITY` ;
- les 6 rapports Sales, Products, Expenses, Receivables, Purchases et dettes
  fournisseurs utilisent `VIEW_REPORTS`.

Les tests couvrent l'OWNER, l'ancien MANAGER sans permission, chaque permission
explicite, les titres sans effet, le membre suspendu, l'isolation tenant et les
Business suspendus ou archivés. Les calculs et agrégations métier sont inchangés
et les mesures existantes confirment l'absence de N+1.

### P1-A3.6 — Administration Business et lectures Receivables — partiel

Les sept opérations disposant déjà d'une permission exacte ont été migrées :
modification Business, lecture des membres, création/modification des moyens de
paiement et trois lectures Receivables. Les quatre arbitrages détaillés plus
haut restent nécessaires pour les deux lectures des moyens de paiement, les
deux opérations Customer et les trois lectures Sales.

### P1-A3.7 — Harmonisation finale

Supprimer les usages API de `can_manage_business`, centraliser les mixins de
résolution, harmoniser OpenAPI et les erreurs 403/404, puis exécuter la matrice
transversale OWNER / permission accordée / révoquée / aucune permission /
suspendu / autre Business / Business inactif.

Chaque lot conserve les routes et payloads, n'ajoute pas de logique métier aux
serializers, et peut être validé indépendamment avant le suivant.

## Conclusion

L'isolation par Business est globalement présente et aucun rôle ou titre legacy
ne confère de privilège. Après P1-A3.6, aucune opération ne reste à migrer avec
une permission existante : 79 opérations sont conformes. Les 7 autres sont
classées et analysées, mais leurs 4 décisions de granularité restent ouvertes.
La création de client, les lectures Customer/Sales et les lectures des moyens de
paiement constituent les risques résiduels documentés. P1-A3 ne peut pas être
déclaré entièrement terminé tant que ces arbitrages ne sont pas rendus et que
les derniers contrôles directs ou transitoires correspondants ne sont pas
remplacés par le moteur centralisé.
