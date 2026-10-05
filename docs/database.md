# Database

```mermaid
erDiagram
  CARRI_IDENTITY ||--o{ BUSINESS_MEMBER : belongs
  BUSINESS ||--o{ BUSINESS_MEMBER : has
```

- **CarriIdentity** : PK UUID, `carri_subject` unique, projection minimale OIDC. Suppression protégée par les memberships.
- **OAuthLoginAttempt** : state hashé unique, nonce, verifier PKCE, expiration et consommation.
- **IDTokenReplay** : hash unique de preuve mobile et expiration.
- **OAuthHandoff** : hash unique, identité, expiration et consommation.
- **Business** : PK UUID, données opérationnelles, statut ACTIVE/SUSPENDED/ARCHIVED, devise CDF/USD.
- **BusinessMember** : PK UUID, FK protégées vers Business et CarriIdentity, unique `(identity, business)`, rôle OWNER/MANAGER/EMPLOYEE et statut ACTIVE/SUSPENDED. Le modèle refuse la suppression fonctionnelle du dernier OWNER actif.
