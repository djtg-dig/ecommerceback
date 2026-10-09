# P1-A3.1 — Audit des autorisations des API Niveau 1

Date de l'audit initial : 8 octobre 2026. Finalisation P1-A3.7 : 9 octobre 2026.

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
`VIEW_PAYMENT_METHODS`, `MANAGE_PAYMENT_METHODS`, `VIEW_CUSTOMERS`,
`MANAGE_CUSTOMERS`, `VIEW_CATALOG`, `MANAGE_CATALOG`,
`VIEW_INVENTORY`, `MANAGE_INVENTORY`, `MANAGE_EXPENSE_CATEGORIES`,
`CREATE_EXPENSES`, `VIEW_EXPENSES`, `MANAGE_EXPENSES`, `VIEW_PURCHASES`,
`MANAGE_PURCHASES`, `USE_POS`, `VIEW_SALES`, `MANAGE_SALES`, `MANAGE_SALE_RETURNS`,
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
| GET | `/businesses/{SH}/payment-methods/` | `BusinessPaymentMethodsView`; projection ORM | `require_any_permission(VIEW_PAYMENT_METHODS, USE_POS)` ; `USE_POS` limité aux actifs | `VIEW_PAYMENT_METHODS` ou projection POS `USE_POS` | conforme — P1-A3.7 |
| POST | `/businesses/{SH}/payment-methods/` | `BusinessPaymentMethodsView`; serializer | `require_permission(..., MANAGE_PAYMENT_METHODS, write=True)` | `MANAGE_PAYMENT_METHODS` | conforme — P1-A3.6 |
| GET | `/businesses/{SH}/payment-methods/{PM}/` | `BusinessPaymentMethodDetailView`; projection ORM | `require_any_permission(VIEW_PAYMENT_METHODS, USE_POS)` ; inactif masqué au POS | `VIEW_PAYMENT_METHODS` ou projection POS `USE_POS` | conforme — P1-A3.7 |
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

### Sales, clients et retours — 13 opérations

| Méthode | Chemin | Vue ; service | Contrôle actuel | Permission cible | Statut |
|---|---|---|---|---|---|
| GET | `/businesses/{SH}/customers/` | `Customers`; queryset | `require_permission(..., VIEW_CUSTOMERS)` | `VIEW_CUSTOMERS` | conforme — P1-A3.7 |
| POST | `/businesses/{SH}/customers/` | `Customers`; serializer | `require_permission(..., MANAGE_CUSTOMERS, write=True)` | `MANAGE_CUSTOMERS` | conforme — P1-A3.7 |
| GET | `/businesses/{SH}/customers/pos/search/` | `PosCustomerSearch`; projection compacte paginée | `require_permission(..., USE_POS)` | `USE_POS`, clients actifs seulement | conforme — P1-A3.7 |
| GET | `/businesses/{SH}/sales/` | `Sales`; queryset | `require_permission(..., VIEW_SALES)` | `VIEW_SALES` | conforme — P1-A3.7 |
| POST | `/businesses/{SH}/sales/` | `Sales`; serializer | `require_permission(..., USE_POS, write=True)` | `USE_POS` | conforme — P1-A3.2 |
| GET | `/businesses/{SH}/sales/{SA}/` | `SD`; queryset | `require_permission(..., VIEW_SALES)` | `VIEW_SALES` | conforme — P1-A3.7 |
| PATCH | `/businesses/{SH}/sales/{SA}/` | `SD`; serializer | `require_permission(..., USE_POS, write=True)` | `USE_POS` | conforme — P1-A3.2 |
| GET | `/businesses/{SH}/sales/{SA}/lines/` | `Lines`; queryset | `require_permission(..., VIEW_SALES)` | `VIEW_SALES` | conforme — P1-A3.7 |
| POST | `/businesses/{SH}/sales/{SA}/lines/` | `Lines`; modèle | `require_permission(..., USE_POS, write=True)` | `USE_POS` | conforme — P1-A3.2 |
| POST | `/businesses/{SH}/sales/{SA}/complete/` | `Complete`; `complete` | `require_permission(..., USE_POS, write=True)` | `USE_POS` | conforme — P1-A3.2 |
| POST | `/businesses/{SH}/sales/{SA}/cancel/` | `Cancel`; `cancel` | `require_permission(..., MANAGE_SALES, write=True)` | `MANAGE_SALES` | conforme — P1-A3.2 |
| GET | `/businesses/{SH}/sales/{SA}/returns/` | `SaleReturns`; queryset | `require_permission(..., MANAGE_SALE_RETURNS)` | `MANAGE_SALE_RETURNS` | conforme — P1-A3.2 |
| POST | `/businesses/{SH}/sales/{SA}/returns/` | `SaleReturns`; `create_sale_return` | `require_permission(..., MANAGE_SALE_RETURNS, write=True)` | `MANAGE_SALE_RETURNS` | conforme — P1-A3.2 |

`USE_POS` convient aux mutations du ticket courant mais n'autorise aucune
lecture globale de l'historique Sales ni du référentiel client complet. Sa
recherche client dédiée ne retourne que `public_id`, `name` et `phone` des
clients actifs. La création client reste distincte derrière `MANAGE_CUSTOMERS`.

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
| Conforme | 87 |
| À migrer | 0 |
| À clarifier | 0 |
| **Total** | **87** |

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

### P1-A3.7 — arbitrages appliqués

| Méthode et endpoint | Permission appliquée | Risque corrigé |
|---|---|---|
| `GET /businesses/{SH}/payment-methods/` | `VIEW_PAYMENT_METHODS`, ou `USE_POS` limité aux actifs | Suppression du couplage à `UPDATE_BUSINESS` et de la lecture implicite par simple appartenance. |
| `GET /businesses/{SH}/payment-methods/{PM}/` | même politique ; un moyen inactif est masqué au POS | Les références inactives ne sont plus visibles sans droit administratif. |
| `GET /businesses/{SH}/customers/` | `VIEW_CUSTOMERS` | Le référentiel client complet n'est plus lisible par tout membre actif. |
| `POST /businesses/{SH}/customers/` | `MANAGE_CUSTOMERS`, `write=True` | `USE_POS` et l'ancien titre MANAGER ne permettent aucune création implicite. |
| `GET /businesses/{SH}/sales/` | `VIEW_SALES` | L'historique commercial global exige un droit explicite. |
| `GET /businesses/{SH}/sales/{SA}/` | `VIEW_SALES` | Le détail d'une vente est protégé par le même droit de lecture. |
| `GET /businesses/{SH}/sales/{SA}/lines/` | `VIEW_SALES` | Les lignes et prix historiques ne sont plus exposés par simple appartenance. |

Le nouveau `GET /customers/pos/search/` préserve la sélection client nécessaire
au POS sans rouvrir le référentiel administratif : `USE_POS`, clients actifs,
pagination 20/50 et projection limitée à `public_id`, `name` et `phone`.

## Contrôles legacy et dupliqués

L'audit final ne trouve plus aucun appel API à `can_manage_business` ou
`can_view_members`, ni aucune comparaison de rôle ou titre pour autoriser une
opération. Les deux helpers transitoires ont été retirés.

La recherche directe `members__identity` + `members__status="ACTIVE"` subsiste
uniquement dans `accessible`, pour `GET /businesses/` et
`GET /businesses/{SH}/`. Cette exception est justifiée : ces routes fournissent
les informations administratives minimales permettant à un membre actif de
sélectionner son tenant, sans donner accès à une ressource métier.

Aucune comparaison applicative `role == OWNER`, `role == MANAGER`,
`role in (...)` ou équivalent n'a été trouvée hors modèles, migrations, admin et
tests. Un ancien MANAGER ne récupère donc aucun droit du fait de son rôle.

Les services métier des domaines Catalog, Inventory, Purchases, Sales,
Receivables, Expenses et Finance valident leurs invariants métier mais ne
réévaluent généralement pas `BusinessMemberPermission`. L'autorisation repose
donc sur la vue appelante. Ce choix impose que chaque vue migre avant qu'un
service sensible ne soit exposé par un nouveau point d'entrée.

## Décisions P1-A3.7 appliquées

Les quatre permissions `VIEW_PAYMENT_METHODS`, `VIEW_CUSTOMERS`,
`MANAGE_CUSTOMERS` et `VIEW_SALES` sont enregistrées. La migration de choix ne
crée aucune attribution : les permissions existantes sont préservées et aucun
ancien MANAGER ou EMPLOYEE ne reçoit automatiquement les nouveaux droits.

## Analyse de sécurité

### Garanties déjà présentes

- l'OWNER actif obtient toutes les permissions enregistrées via P1-A2 ;
- les titres et le champ legacy `role` ne sont consultés par aucune décision
  d'autorisation ;
- les querysets d'objets sont systématiquement rattachés au Business résolu,
  ce qui protège l'isolation tenant sur les routes examinées ;
- les membres suspendus sont exclus par les scopes actuels ;
- les écritures métier passent `write=True` au moteur et sont bloquées sur un
  Business suspendu ou archivé.

### Risques critiques

1. **Création de client sans permission — corrigé P1-A3.7** : le POST Customer
   exige `MANAGE_CUSTOMERS` et reste interdit à un membre uniquement `USE_POS`.
2. **Encaissement Receivable sans permission — corrigé P1-A3.2** : le POST
   paiement exige désormais `MANAGE_RECEIVABLES` avant `add_payment`.
3. **Business inactif mutable — corrigé pour P1-A3.2** : les neuf opérations
   migrées utilisent `write=True` pour leurs mutations ; `SUSPENDED` et
   `ARCHIVED` sont refusés.
4. **Lecture sensible trop large — corrigée P1-A3.7** : clients, ventes et
   moyens de paiement administratifs exigent leurs permissions dédiées. Les
   projections POS sont limitées aux données nécessaires.

### Cohérence 403/404

Le moteur P1-A2 définit : absence de membership = 404 ; membership existant mais
non autorisé ou suspendu = 403. Les vues Sales/Receivables migrées en P1-A3.2 et
Purchases/Expenses migrées en P1-A3.3, Catalog/Inventory migrées en P1-A3.4 et
les projections financières migrées en P1-A3.5 ainsi que l'administration et
les lectures Receivables migrées en P1-A3.6 appliquent désormais cette
distinction en résolvant d'abord le Business puis en appelant
`require_permission`. Les sept dernières opérations appliquent la même règle
depuis P1-A3.7.

## Matrice fonctionnelle condensée

| Domaine / opération | Permission existante retenue |
|---|---|
| Modifier Business | `UPDATE_BUSINESS` |
| Consulter membres | `VIEW_MEMBERS` |
| Lire / gérer moyens de paiement | `VIEW_PAYMENT_METHODS` / `MANAGE_PAYMENT_METHODS` |
| Lire / gérer clients | `VIEW_CUSTOMERS` / `MANAGE_CUSTOMERS` |
| Lire / gérer catalogue | `VIEW_CATALOG` / `MANAGE_CATALOG` |
| Rechercher au POS | `USE_POS` |
| Lire / gérer inventaire | `VIEW_INVENTORY` / `MANAGE_INVENTORY` |
| Lire / gérer achats, fournisseurs et règlements | `VIEW_PURCHASES` / `MANAGE_PURCHASES` |
| Créer/éditer/compléter un ticket POS | `USE_POS` |
| Lire l'historique des ventes | `VIEW_SALES` |
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
était alors volontairement différé ; il exige désormais `MANAGE_CUSTOMERS`
depuis P1-A3.7.

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

### P1-A3.6 — Administration Business et lectures Receivables — terminé

Les sept opérations disposant déjà d'une permission exacte ont été migrées :
modification Business, lecture des membres, création/modification des moyens de
paiement et trois lectures Receivables. Les quatre arbitrages détaillés plus
haut ont ensuite été rendus et appliqués en P1-A3.7.

### P1-A3.7 — Harmonisation finale — terminé

Les quatre nouvelles permissions protègent les sept opérations finales. Les
helpers legacy ont été supprimés, OpenAPI expose les erreurs 403/404 et les
tests couvrent OWNER, permission explicite, aucun droit, ancien MANAGER, membre
suspendu, autre Business et Business inactif. Les deux projections POS restent
bornées aux moyens actifs et aux identifiants clients strictement nécessaires.

Chaque lot conserve les routes et payloads, n'ajoute pas de logique métier aux
serializers, et peut être validé indépendamment avant le suivant.

## Conclusion

L'isolation par Business est globalement présente et aucun rôle ou titre legacy
ne confère de privilège. Après P1-A3.7, les 87 opérations inventoriées sont
conformes ou constituent des exceptions administratives/publiques explicitement
justifiées. Les sept opérations finales utilisent les permissions décidées et
aucun helper legacy ne subsiste dans les vues. Le seul scope direct restant est
`accessible`, limité à la liste et au détail administratif minimal des Business
d'un membre actif. Aucun risque d'autorisation critique connu ne reste ouvert
dans le périmètre audité.
