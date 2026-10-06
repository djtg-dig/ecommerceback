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

- ✓ Business / membres
- ✓ Catalogue, produits / variantes
- ✓ Inventaire
- ✓ Fournisseurs et achats
- ✓ Clients et ventes POS
- ✓ Créances
- ✓ Dépenses

À venir : caisse / flux financiers et reporting / dashboard. Les niveaux 2 (visibilité publique) et 3 (vente en ligne) ne sont pas implémentés.

## Devise financière unique

Chaque Business choisit `primary_currency` (`CDF` ou `USD`) à sa création. Cette valeur est immuable : Sale, Purchase, Expense et Receivable conservent une devise snapshot imposée par le Business. Aucune conversion, taux ou frais de conversion n’est géré dans les domaines opérationnels ; un domaine séparé les traitera ultérieurement.

## Finance

Finance est le journal financier append-only interne. `FinancialMovement` reçoit des événements métier déjà validés et ne pilote aucun gateway. Les sources Sales, Receivables et Expenses restent propriétaires de leurs workflows; leurs futures écritures Finance passeront par un service transactionnel idempotent. OWNER et MANAGER consultent les mouvements et agrégats, tandis que les employés n’accèdent pas au reporting financier.
