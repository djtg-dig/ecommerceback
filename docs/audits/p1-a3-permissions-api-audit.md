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
| PATCH | `/businesses/{SH}/` | `BusinessDetailView`; serializer, `replace_categories` | `can_manage_business` | `UPDATE_BUSINESS` | à migrer |
| GET | `/businesses/{SH}/members/` | `BusinessMembersView`; projection ORM | `can_view_members` après `accessible` | `VIEW_MEMBERS` | à migrer |
| GET | `/businesses/{SH}/payment-methods/` | `BusinessPaymentMethodsView`; projection ORM | membre actif ; `can_manage_business` révèle aussi les inactifs | permission de lecture absente | à clarifier |
| POST | `/businesses/{SH}/payment-methods/` | `BusinessPaymentMethodsView`; serializer | `can_manage_business` | `MANAGE_PAYMENT_METHODS` | à migrer |
| GET | `/businesses/{SH}/payment-methods/{PM}/` | `BusinessPaymentMethodDetailView`; projection ORM | membre actif ; `can_manage_business` pour un moyen inactif | permission de lecture absente | à clarifier |
| PATCH | `/businesses/{SH}/payment-methods/{PM}/` | `BusinessPaymentMethodDetailView`; serializer | `can_manage_business` | `MANAGE_PAYMENT_METHODS` | à migrer |
| GET | `/business-categories/` | `BusinessCategoriesView`; projection ORM | public `AllowAny` | aucune, taxonomie publique | conforme |

Les lectures liste/détail Business sont les informations administratives
minimales qu'un membre actif doit pouvoir consulter. Elles ne donnent aucun
droit métier. La migration de `BusinessMembersView` reste nécessaire pour
obtenir les erreurs canoniques de `require_permission`.

### Catalog — 12 opérations

| Méthode | Chemin | Vue ; service | Contrôle actuel | Permission cible | Statut |
|---|---|---|---|---|---|
| GET | `/product-categories/` | `ProductCategoryListView`; queryset | public `AllowAny` | aucune, taxonomie publique | conforme |
| GET | `/product-categories/{code}/attributes/` | `ProductCategoryAttributesView`; `effective_attributes` | public `AllowAny` | aucune, taxonomie publique | conforme |
| GET | `/businesses/{SH}/products/` | `ProductListCreateView`; queryset | membership ACTIVE direct | `VIEW_CATALOG` | à migrer |
| POST | `/businesses/{SH}/products/` | `ProductListCreateView`; `create_product` | `can_manage_business` | `MANAGE_CATALOG` | à migrer |
| GET | `/businesses/{SH}/products/pos/search/` | `PosSearchView`; agrégations Catalog/Inventory | membership ACTIVE direct | `USE_POS` | à migrer |
| GET | `/businesses/{SH}/products/{PR}/` | `ProductDetailView`; queryset | membership ACTIVE direct | `VIEW_CATALOG` | à migrer |
| PATCH | `/businesses/{SH}/products/{PR}/` | `ProductDetailView`; serializer | `can_manage_business` | `MANAGE_CATALOG` | à migrer |
| POST | `/businesses/{SH}/products/{PR}/archive/` | `ProductArchiveView`; modèle | `can_manage_business` | `MANAGE_CATALOG` | à migrer |
| GET | `/businesses/{SH}/products/{PR}/variants/` | `ProductVariantListCreateView`; queryset | membership ACTIVE direct | `VIEW_CATALOG` | à migrer |
| POST | `/businesses/{SH}/products/{PR}/variants/` | `ProductVariantListCreateView`; `ensure_can_create_variant`, `create_variant` | `can_manage_business` | `MANAGE_CATALOG` | à migrer |
| GET | `/businesses/{SH}/products/{PR}/variants/{PV}/` | `ProductVariantDetailView`; queryset | membership ACTIVE direct | `VIEW_CATALOG` | à migrer |
| PATCH | `/businesses/{SH}/products/{PR}/variants/{PV}/` | `ProductVariantDetailView`; serializer | `can_manage_business` | `MANAGE_CATALOG` | à migrer |

### Inventory — 5 opérations

| Méthode | Chemin | Vue ; service | Contrôle actuel | Permission cible | Statut |
|---|---|---|---|---|---|
| GET | `/businesses/{SH}/inventory/` | `InventoryListCreateView`; queryset | membership ACTIVE direct | `VIEW_INVENTORY` | à migrer |
| POST | `/businesses/{SH}/inventory/` | `InventoryListCreateView`; `create_inventory_item` | `can_manage_business` | `MANAGE_INVENTORY` | à migrer |
| GET | `/businesses/{SH}/inventory/{IV}/` | `InventoryDetailView`; queryset | membership ACTIVE direct | `VIEW_INVENTORY` | à migrer |
| GET | `/businesses/{SH}/inventory/{IV}/movements/` | `StockMovementListCreateView`; queryset | membership ACTIVE direct | `VIEW_INVENTORY` | à migrer |
| POST | `/businesses/{SH}/inventory/{IV}/movements/` | `StockMovementListCreateView`; `apply_stock_movement` | `can_manage_business` | `MANAGE_INVENTORY` | à migrer |

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
| GET | `/businesses/{SH}/receivables/` | `ReceivableListView`; queryset | membership ACTIVE direct | `VIEW_RECEIVABLES` | à migrer |
| GET | `/businesses/{SH}/receivables/{RE}/` | `ReceivableDetailView`; queryset | membership ACTIVE direct | `VIEW_RECEIVABLES` | à migrer |
| PATCH | `/businesses/{SH}/receivables/{RE}/` | `ReceivableDetailView`; modèle | `require_permission(..., MANAGE_RECEIVABLES, write=True)` | `MANAGE_RECEIVABLES` | conforme — P1-A3.2 |
| GET | `/businesses/{SH}/receivables/{RE}/payments/` | `ReceivablePaymentsView`; queryset | membership ACTIVE direct | `VIEW_RECEIVABLES` | à migrer |
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
| GET | `/businesses/{SH}/financial-movements/` | `FinancialMovementListView`; queryset | `can_manage_business`, refus masqué en 404 | `VIEW_FINANCIAL_SUMMARY` | à migrer |
| GET | `/businesses/{SH}/financial-movements/{FM}/` | `FinancialMovementDetailView`; queryset | `can_manage_business`, refus masqué en 404 | `VIEW_FINANCIAL_SUMMARY` | à migrer |
| GET | `/businesses/{SH}/financial-summary/` | `FinancialSummaryView`; `financial_summary` | `can_manage_business`, refus masqué en 404 | `VIEW_FINANCIAL_SUMMARY` | à migrer |

### Dashboard, rentabilité et rapports — 8 opérations

| Méthode | Chemin | Vue ; service | Contrôle actuel | Permission cible | Statut |
|---|---|---|---|---|---|
| GET | `/businesses/{SH}/dashboard/` | `DashboardView`; `build_dashboard` | `can_manage_business`, refus masqué en 404 | `VIEW_DASHBOARD` | à migrer |
| GET | `/businesses/{SH}/profitability-summary/` | `ProfitabilitySummaryView`; `build_profitability_summary` | `can_manage_business`, refus masqué en 404 | `VIEW_PROFITABILITY` | à migrer |
| GET | `/businesses/{SH}/reports/sales/` | `SalesReportView`; `build_sales_series` | `can_manage_business`, refus masqué en 404 | `VIEW_REPORTS` | à migrer |
| GET | `/businesses/{SH}/reports/products/` | `ProductReportView`; `build_product_top` | `can_manage_business`, refus masqué en 404 | `VIEW_REPORTS` | à migrer |
| GET | `/businesses/{SH}/reports/expenses/` | `ExpensesReportView`; `build_expenses_report` | `can_manage_business`, refus masqué en 404 | `VIEW_REPORTS` | à migrer |
| GET | `/businesses/{SH}/reports/receivables/` | `ReceivablesReportView`; agrégations | `can_manage_business`, refus masqué en 404 | `VIEW_REPORTS` | à migrer |
| GET | `/businesses/{SH}/reports/purchases/` | `PurchasesReportView`; `build_purchases_report` | `can_manage_business`, refus masqué en 404 | `VIEW_REPORTS` | à migrer |
| GET | `/businesses/{SH}/reports/supplier-debts/` | `SupplierDebtsReportView`; `debt_queryset` | `can_manage_business`, refus masqué en 404 | `VIEW_REPORTS` | à migrer |

## Synthèse chiffrée

| Statut | Opérations |
|---|---:|
| Conforme | 46 |
| À migrer | 33 |
| À clarifier | 7 |
| **Total** | **86** |

## Contrôles legacy et dupliqués

Quatre familles de contrôles doivent disparaître progressivement des vues :

1. `can_manage_business`, helper transitoire fondé sur `UPDATE_BUSINESS`, protège
   encore 23 opérations de configuration Business, catalogue, stock, Finance et
   reporting avec une permission trop générale ;
2. les recherches directes `members__identity` + `members__status="ACTIVE"`
   sont répétées dans presque chaque mixin et contournent `membership_for` /
   `require_permission` ;
3. `can_view_members` porte la bonne permission mais n'utilise pas encore le
   chemin canonique `require_permission`, notamment pour 403/404 ;
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

## Permissions manquantes — décisions requises

Quatre capacités ne peuvent pas être exprimées précisément avec le registre
actuel :

1. **lecture des moyens de paiement actifs** : décider si elle reste un droit de
   référence implicite pour tout membre actif ou si une permission
   `VIEW_PAYMENT_METHODS` est nécessaire ;
2. **lecture des clients** : une permission du type `VIEW_CUSTOMERS` éviterait
   d'accorder `MANAGE_SALES` ou `USE_POS` à une consultation globale ;
3. **gestion des clients** : une permission du type `MANAGE_CUSTOMERS` séparerait
   le référentiel client de l'utilisation du POS ;
4. **lecture globale des ventes** : une permission du type `VIEW_SALES` éviterait
   qu'un vendeur `USE_POS` lise tout l'historique ou qu'un lecteur doive recevoir
   `MANAGE_SALES`.

Ces noms sont descriptifs pour la décision métier ; cet audit ne les ajoute ni
au modèle ni à une migration.

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
4. **Lecture sensible trop large — partiellement corrigée P1-A3.3** : achats,
   fournisseurs et dépenses exigent désormais leur permission de lecture. Tout
   membre actif peut encore lire clients, ventes, créances, stock et catalogue
   indépendamment de ses permissions individuelles.

### Cohérence 403/404

Le moteur P1-A2 définit : absence de membership = 404 ; membership existant mais
non autorisé ou suspendu = 403. Les vues Sales/Receivables migrées en P1-A3.2 et
Purchases/Expenses migrées en P1-A3.3 appliquent désormais cette distinction en
résolvant d'abord le Business puis en appelant `require_permission`. Les autres
scopes directs et usages de `can_manage_business` restent à harmoniser.

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

### P1-A3.4 — Catalog, POS search et Inventory

Remplacer les mixins dupliqués par le moteur central, distinguer
`VIEW_CATALOG`, `MANAGE_CATALOG`, `USE_POS`, `VIEW_INVENTORY` et
`MANAGE_INVENTORY`, puis tester produits archivés et isolation Business.

### P1-A3.5 — Finance, Dashboard, rentabilité et rapports

Remplacer `UPDATE_BUSINESS` par les permissions de lecture dédiées. Tester chaque
projection, l'absence de fuite financière, les périodes et le comportement des
Business inactifs.

### P1-A3.6 — Administration Business

Migrer membres, modification Business et gestion des moyens de paiement.
Trancher la lecture des moyens de paiement et préserver les lectures
administratives strictement nécessaires au statut d'un Business inactif.

### P1-A3.7 — Harmonisation finale

Supprimer les usages API de `can_manage_business`, centraliser les mixins de
résolution, harmoniser OpenAPI et les erreurs 403/404, puis exécuter la matrice
transversale OWNER / permission accordée / révoquée / aucune permission /
suspendu / autre Business / Business inactif.

Chaque lot conserve les routes et payloads, n'ajoute pas de logique métier aux
serializers, et peut être validé indépendamment avant le suivant.

## Conclusion

L'isolation par Business est globalement présente et aucun rôle ou titre legacy
ne confère de privilège. Après P1-A3.3, 33 opérations ont encore une permission
existante mais n'utilisent pas le moteur avec cette permission, et 7 nécessitent
une décision de granularité. Les opérations Sales/Returns/Receivables critiques
ainsi que tout le périmètre Purchases/Expenses sont désormais centralisés ; la
création de client et les autres lectures sensibles trop larges restent les
priorités documentées.
