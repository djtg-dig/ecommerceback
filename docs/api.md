# API

| Endpoint | Auth | But |
|---|---|---|
| GET `/api/v1/health/` | public | liveness `{"status":"ok"}` |
| POST `/api/v1/auth/carri/mobile/exchange/` | public | échange preuve Android `{id_token,access_token,nonce}` contre JWT ecommerce |
| GET `/api/v1/auth/carri/login/` | public | redirection Web OIDC |
| GET `/api/v1/auth/carri/callback/` | public | valide callback et retourne un handoff |
| POST `/api/v1/auth/carri/handoff/consume/` | public, handoff | consomme le handoff une fois et retourne JWT ecommerce |
| GET `/api/v1/auth/me/` | JWT ecommerce | `{id,carri_subject}` |
| GET `/api/v1/product-categories/` | public | catégories globales actives, à plat (`parent_code`, `level`) |
| GET `/api/v1/product-categories/{code}/attributes/` | public | attributs actifs effectifs et leurs options actives |
| POST `/api/v1/auth/token/refresh/` | refresh ecommerce | renouvelle les tokens |
| GET/POST `/api/v1/businesses/` | JWT ecommerce | liste isolée / crée Business + OWNER |
| GET/PATCH `/api/v1/businesses/{id}/` | membre actif | détail / modification OWNER ou MANAGER |
| GET `/api/v1/businesses/{id}/members/` | OWNER ou MANAGER | memberships sans données Carri |

Un Business étranger répond 404. Invitations de membres : à implémenter.

Business routes use `public_id` (`SHXXXXXXXXXX`), never the internal UUID: `GET/PATCH /api/v1/businesses/{public_id}/` and `GET /api/v1/businesses/{public_id}/members/`. Create and PATCH accept `categories` (codes) and optional `primary_category`; OWNER and MANAGER may change them. `GET /api/v1/business-categories/` is public and returns active platform categories only.

## Products and variants

| Endpoint | Permission | Payload / behavior |
|---|---|---|
| GET `/api/v1/businesses/{SH}/products/` | membre actif | Filters: `status`, `category` (code), `search`; only that Business. |
| POST `/api/v1/businesses/{SH}/products/` | OWNER, MANAGER | `name`, leaf `category`, `selling_price`, optional JSON `attributes`, SKU, barcode, costs/currency/status. |
| GET/PATCH `/api/v1/businesses/{SH}/products/{PR}/` | membre actif / OWNER, MANAGER | Product response exposes category code/type and no UUID. PATCH revalidates attributes and variants if category changes. |
| POST `/api/v1/businesses/{SH}/products/{PR}/archive/` | OWNER, MANAGER | Sets Product status to `ARCHIVED`; no delete endpoint. |
| GET/POST `/api/v1/businesses/{SH}/products/{PR}/variants/` | membre actif / OWNER, MANAGER | Variant JSON attributes contain only category variant axes. |
| GET/PATCH `/api/v1/businesses/{SH}/products/{PR}/variants/{PV}/` | membre actif / OWNER, MANAGER | Returns effective inherited prices; UUID and signature are not exposed. |

Invalid/inactive/non-leaf categories, invalid attribute values, unknown keys, a duplicate variant combination, negative price, or conflicting SKU return `400`. Foreign business/product/variant paths return `404`.

## OpenAPI / Swagger

La documentation développeur est générée depuis les routes et serializers réels :

- Swagger UI : `/api/docs/`
- ReDoc : `/api/redoc/`
- Schéma OpenAPI : `/api/schema/`

Les routes protégées affichent le bouton **Authorize**. Coller uniquement un JWT d’accès ecommerce dans le champ Bearer (`Authorization: Bearer <ecommerce_access_token>`). Swagger ne demande jamais de mot de passe Carri Account, de secret client, de code OAuth ou de vérificateur PKCE. `/api/v1/` n’est pas une API root et peut répondre `404`; `/api/docs/` est le point d’entrée développeur.

## Inventory / Stock

Toutes les routes utilisent un JWT ecommerce Bearer. OWNER, MANAGER et EMPLOYEE lisent; seul OWNER ou MANAGER crée un InventoryItem ou un mouvement.

| Endpoint | Permission | Comportement |
|---|---|---|
| GET `/api/v1/businesses/{SH}/inventory/` | membre actif | Filtres optionnels `product=PR...`, `variant=PV...`, `low_stock=true`. |
| POST `/api/v1/businesses/{SH}/inventory/` | OWNER, MANAGER | `{ "product": "PR...", "low_stock_threshold": "5.000" }` ou `{ "variant": "PV..." }`; quantité initiale zéro. |
| GET `/api/v1/businesses/{SH}/inventory/{IV}/` | membre actif | Solde, réservé, disponible, seuil et statut low-stock. |
| GET `/api/v1/businesses/{SH}/inventory/{IV}/movements/` | membre actif | Historique immuable, plus récent en premier. |
| POST `/api/v1/businesses/{SH}/inventory/{IV}/movements/` | OWNER, MANAGER | Entrée, sortie ou ajustement manuel. |

Exemples de mutation :

```json
{ "type": "IN", "quantity": "25.000", "reason": "Stock initial" }
```

```json
{ "type": "OUT", "quantity": "3.000", "reason": "Produit endommagé" }
```

```json
{ "type": "ADJUSTMENT", "target_quantity": "20.000", "reason": "Inventaire physique" }
```

Les champs `quantity`, `reserved_quantity`, snapshots avant/après, auteur, références techniques et identifiants publics sont calculés ou réservés au serveur. Les erreurs de cible invalide, stock insuffisant, type réservé, produit archivé ou accès inter-tenant renvoient `400`, `403` ou `404` selon le cas.
