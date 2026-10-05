# API

| Endpoint | Auth | But |
|---|---|---|
| GET `/api/v1/health/` | public | liveness `{"status":"ok"}` |
| POST `/api/v1/auth/carri/mobile/exchange/` | public | échange preuve Android `{id_token,access_token,nonce}` contre JWT ecommerce |
| GET `/api/v1/auth/carri/login/` | public | redirection Web OIDC |
| GET `/api/v1/auth/carri/callback/` | public | valide callback et retourne un handoff |
| POST `/api/v1/auth/carri/handoff/consume/` | public, handoff | consomme le handoff une fois et retourne JWT ecommerce |
| GET `/api/v1/auth/me/` | JWT ecommerce | `{id,carri_subject}` |
| POST `/api/v1/auth/token/refresh/` | refresh ecommerce | renouvelle les tokens |
| GET/POST `/api/v1/businesses/` | JWT ecommerce | liste isolée / crée Business + OWNER |
| GET/PATCH `/api/v1/businesses/{id}/` | membre actif | détail / modification OWNER ou MANAGER |
| GET `/api/v1/businesses/{id}/members/` | OWNER ou MANAGER | memberships sans données Carri |

Un Business étranger répond 404. Invitations de membres : à implémenter.
