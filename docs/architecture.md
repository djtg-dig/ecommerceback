# Architecture

```text
Flutter Android / Next.js / Flutter Desktop -> REST /api/v1/ -> Django + DRF -> PostgreSQL
                                                        \-> Carri Account OIDC
```

Django expose l'API métier versionnée et PostgreSQL stocke les projections et domaines métier. Carri Account reste l'autorité d'identité. `apps/` isole les domaines : `accounts` pour OIDC et `businesses` pour les commerces.

## Décisions architecturales

- Django + DRF et PostgreSQL sont le socle.
- CarriIdentity est une projection de `sub`, pas un User métier.
- Les JWT ecommerce sont distincts des tokens Carri.
- Android est un client public PKCE; le Web est confidentiel.
- Chaque queryset Business est filtré par BusinessMember actif : c'est le socle multi-tenant des prochains domaines.

Business is the legal/operational tenant; a future BusinessLocation may represent outlets. BusinessCategory is a flat business-activity taxonomy and is distinct from future ProductCategory. Public IDs improve client-facing references but do not grant access: membership filtering remains mandatory.

`BusinessMember` sépare désormais trois notions : `is_owner` porte la propriété administrative unique du Business, `title` décrit librement le métier (Gérant, Gestionnaire, Caissier, Vendeur, Magasinier, Comptable ou Employé), et `BusinessMemberPermission` porte les autorisations individuelles. Un titre n'accorde aucun droit. L'OWNER actif possède implicitement toutes les permissions; les autres membres commencent sans permission et un membre suspendu n'en exerce aucune. Le champ `role` OWNER/MANAGER/EMPLOYEE est conservé uniquement pour la migration et la compatibilité des données historiques; les décisions d'autorisation ne le consultent plus.


## Global catalog

`apps.catalog` is platform metadata, independent from tenants. It exposes public category and effective-attribute reads. Product entities will reference this taxonomy in a later phase; this app deliberately creates no product, inventory or sales model.

## Tenant products and inventory boundary

`apps.catalog` owns global category metadata and tenant-owned Product/ProductVariant records. Products are reached only through an active `BusinessMember`, then the requested Business, so public identifiers do not bypass tenant boundaries. Attribute validation is centralized against the global taxonomy before persistence. Inventory will be a separate domain and will later attach stock movements and balances to a simple Product or a ProductVariant; it must not add quantities to catalog models.

## OpenAPI

`drf-spectacular` génère le contrat OpenAPI à partir des routes DRF et des serializers. Une extension décrit `EcommerceJWTAuthentication` comme un bearer JWT afin que le schéma conserve le même modèle de sécurité que l’API exécutée. Les pages Swagger et ReDoc sont publiques pour consultation, mais ne changent ni permissions ni authentification des opérations métier.

## Inventory

Le catalogue définit ce qui est vendable; Inventory définit combien est disponible. `InventoryItem` est le solde transactionnel d’un Product simple ou d’un ProductVariant, et `StockMovement` est son journal immuable. Les mutations prennent un verrou de ligne PostgreSQL avant le calcul du solde. La future évolution `Business -> BusinessLocation -> InventoryItem` ajoutera des emplacements sans mélanger inventaire et catalogue.

## Purchases

Purchases reste séparé de Inventory: seule la réception validée appelle le service Inventory atomique; DRAFT et CONFIRMED ne changent jamais le stock.

## Niveau 1 — Gestion interne
Business, catalogue, fournisseurs, achats, inventaire, clients et ventes servent les opérations internes. Sale est une vente POS, pas un Order. Niveau 2 visibilité publique et Niveau 3 vente en ligne ne sont pas implémentés.

Créances fait partie du Niveau 1 interne; aucun gateway, caisse ou marketplace n’est implémenté.

## Expenses

Expenses est un domaine Niveau 1 séparé de Purchases et de Receivables. Il possède ses catégories par Business et conserve un historique d'annulation. Les catégories standards sont orchestrées par le service Business dans la même transaction que la création du tenant.

## Niveau 1 — Gestion interne

- ✓ Business / membres (séparation propriété / titre / permissions)
- ✓ Catalogue, produits / variantes
- ✓ Inventaire
- ✓ Fournisseurs et achats
- ✓ Clients et ventes POS
- ✓ Créances
- ✓ Dépenses

Le journal financier interne, le dashboard et les rapports opérationnels sont implémentés au Niveau 1. Les niveaux 2 (visibilité publique) et 3 (vente en ligne) ne sont pas implémentés.

## Devise financière unique

Chaque Business choisit `primary_currency` (`CDF` ou `USD`) à sa création. Cette valeur est immuable : Sale, Purchase, Expense et Receivable conservent une devise snapshot imposée par le Business. Aucune conversion, taux ou frais de conversion n’est géré dans les domaines opérationnels ; un domaine séparé les traitera ultérieurement.

## Finance

Finance est le journal financier append-only interne. `FinancialMovement` reçoit des événements métier déjà validés et ne pilote aucun gateway. Les sources Sales, Sale Returns, Receivables, Expenses et Purchases restent propriétaires de leurs workflows et écrivent via le service Finance dans leurs transactions. Le propriétaire dispose de l'accès complet; un autre membre ne reçoit un accès de gestion que par permission individuelle explicite.

## Encaissements Sales et créances

Les domaines Sales et Receivables restent propriétaires de leurs workflows. Finance reçoit les encaissements et remboursements validés par leurs services centraux, dans la même transaction PostgreSQL. Cette séparation garantit qu’un acompte est représenté par le paiement de créance, pas deux fois par Sale et ReceivablePayment. Les comptes bancaires réels, gateways et rapprochements de caisse restent hors périmètre.

## Décaissements Expenses

Expense, ExpensePayment et FinancialMovement sont trois responsabilités distinctes : charge métier, règlement réel et conséquence financière. Leur liaison passe par les services Expenses et Finance transactionnels; l’annulation d’une charge réglée est refusée tant que les paiements ne sont pas explicitement reversés.

Purchase peut recevoir des marchandises via Inventory IN et recevoir séparément des SupplierPayment qui génèrent des OUTFLOW Finance. Reverser un paiement ne modifie jamais le stock.

La caisse vendeur est une projection calculée depuis `FinancialMovement`; aucun solde financier persistant n'est stocké sur Business ou sur une méthode de paiement.

Les écrans synthétiques critiques utilisent un endpoint agrégé compact afin de limiter les requêtes HTTP en connectivité faible. Cette optimisation réseau n'impose pas une requête SQL monolithique.
