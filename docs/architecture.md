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
