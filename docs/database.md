# Database

```mermaid
erDiagram
  CARRI_IDENTITY ||--o{ BUSINESS_MEMBER : belongs
  BUSINESS ||--o{ BUSINESS_MEMBER : has
  PRODUCT_CATEGORY ||--o{ PRODUCT_CATEGORY : parent
  PRODUCT_CATEGORY ||--o{ ATTRIBUTE_DEFINITION : defines
  ATTRIBUTE_DEFINITION ||--o{ ATTRIBUTE_OPTION : allows
```

- **CarriIdentity** : PK UUID, `carri_subject` unique, projection minimale OIDC. Suppression protégée par les memberships.
- **OAuthLoginAttempt** : state hashé unique, nonce, verifier PKCE, expiration et consommation.
- **IDTokenReplay** : hash unique de preuve mobile et expiration.
- **OAuthHandoff** : hash unique, identité, expiration et consommation.
- **Business** : PK UUID, données opérationnelles, statut ACTIVE/SUSPENDED/ARCHIVED, devise CDF/USD.
- **BusinessMember** : PK UUID, FK protégées vers Business et CarriIdentity, unique `(identity, business)`, rôle OWNER/MANAGER/EMPLOYEE et statut ACTIVE/SUSPENDED. Le modèle refuse la suppression fonctionnelle du dernier OWNER actif.

## Public business identifiers and activity taxonomy

Business keeps its UUID for PostgreSQL relations but exposes immutable `public_id` as `SH` plus ten characters from `23456789ABCDEFGHJKLMNPQRSTUVWXYZ` (32^10 combinations). IDs use `secrets`; PostgreSQL UNIQUE remains authoritative and creation retries a bounded five times. Migration `0002` adds nullable IDs, backfills distinct values, then makes the column non-null.

BusinessCategory is the platform-controlled flat commerce taxonomy. BusinessCategoryMembership is the explicit relation, unique per Business/category; a conditional PostgreSQL constraint permits at most one `is_primary=True` membership per Business.


## Global product catalog

- **ProductCategory**: UUID PK; unique code and slug; optional globally unique `product_type_key`; protected parent relation; active flag and sort order. Model validation limits trees to three levels and rejects cycles.
- **AttributeDefinition**: UUID PK; protected category relation; unique `(category, code)`; typed active definition. A code cannot duplicate an ancestor's code.
- **AttributeOption**: UUID PK; protected definition relation; unique `(attribute_definition, value)`; active choice value.
