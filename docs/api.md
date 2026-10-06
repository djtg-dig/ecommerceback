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

## Purchases

`/api/v1/businesses/{SH}/suppliers/` et `/purchases/` exposent Supplier/Purchase/PurchaseLine. OWNER/MANAGER écrivent, EMPLOYEE lit. Actions : `POST purchases/{PU}/confirm/`, `/receive/`, `/cancel/`; réception crée les mouvements IN système.

## Sales
Routes internes : `/customers/`, `/sales/`, `/sales/{SA}/lines/`, `/complete/`, `/cancel/`.

## Receivables
GET `/receivables/`, detail, PATCH metadata et GET/POST `/payments/`.

## Expenses

| Endpoint | Permission | Comportement |
|---|---|---|
| GET/POST `/api/v1/businesses/{SH}/expense-categories/` | membre actif / OWNER, MANAGER | Liste ou crée une catégorie propre au Business. |
| GET/PATCH `/api/v1/businesses/{SH}/expense-categories/{EC}/` | membre actif / OWNER, MANAGER | Les catégories système protègent leurs champs métier. |
| GET/POST `/api/v1/businesses/{SH}/expenses/` | membre actif / OWNER, MANAGER | Liste ou crée une dépense ACTIVE. |
| GET/PATCH `/api/v1/businesses/{SH}/expenses/{EX}/` | membre actif / OWNER, MANAGER | Une dépense CANCELLED est immuable. |
| POST `/api/v1/businesses/{SH}/expenses/{EX}/cancel/` | OWNER, MANAGER | Annule définitivement une dépense avec `cancellation_reason`. |

Les filtres de dépenses sont `category`, `status`, `payment_method`, `currency`, `date_from` et `date_to`; les dates sont au format `YYYY-MM-DD`. Les montants sont positifs, les devises sont `CDF` ou `USD` sans conversion automatique. `payment_method` accepte `CASH`, `MOBILE_MONEY`, `BANK_TRANSFER`, `CARD` et `OTHER` comme classification déclarative, sans gateway.

## Finance

Les routes Finance sont consultables par les seuls OWNER et MANAGER actifs; les autres membres et tenants reçoivent `404`. Elles sont GET-only : aucun endpoint public ne crée, modifie ou supprime un mouvement dans ce lot.

| Endpoint | Permission | Comportement |
|---|---|---|
| GET `/api/v1/businesses/{SH}/financial-movements/` | OWNER, MANAGER | Journal Finance, filtres `direction`, `event_type`, `payment_method`, `date_from`, `date_to`. |
| GET `/api/v1/businesses/{SH}/financial-movements/{FM}/` | OWNER, MANAGER | Détail d’une écriture appartenant au Business. |
| GET `/api/v1/businesses/{SH}/financial-summary/` | OWNER, MANAGER | Totaux inflow/outflow/net flow et ventilation par moyen de paiement. |

Les filtres de date utilisent `YYYY-MM-DD`; les valeurs inconnues renvoient `400`. `FM` est une référence publique opaque, pas une autorisation.

## Encaissements Sales et créances

`POST /api/v1/businesses/{SH}/sales/{SA}/complete/` attend désormais :

```json
{"amount_paid": "35000.00", "payment_method": "CASH"}
```

`amount_paid` est obligatoire. S’il est positif, `payment_method` est obligatoire (`CASH`, `MOBILE_MONEY`, `BANK_TRANSFER`, `CARD`, `OTHER`). S’il vaut zéro, `payment_method` doit être absent et aucun encaissement Finance n’est créé. Ce contrat remplace la finalisation historique sans payload.

`POST /api/v1/businesses/{SH}/receivables/{RC}/payments/` accepte `amount`, `payment_method`, `reference`, `notes` et l’en-tête optionnel `Idempotency-Key`. Une répétition avec la même clé et le même payload renvoie le même paiement sans duplication; un payload différent avec la même clé répond `409`.

## Expense payments

| Endpoint | Permission | Comportement |
|---|---|---|
| GET `/api/v1/businesses/{SH}/expenses/{EX}/payments/` | membre actif | Historique des règlements. |
| POST `/api/v1/businesses/{SH}/expenses/{EX}/payments/` | OWNER, MANAGER | Crée un règlement réel et son mouvement Finance. En-tête optionnel `Idempotency-Key`. |
| POST `/api/v1/businesses/{SH}/expenses/{EX}/payments/{EP}/reverse/` | OWNER, MANAGER | Corrige un règlement via une écriture Finance opposée, avec `reason`. |

Une Expense expose `paid_amount`, `balance` et `payment_status`. Créer une Expense ne crée aucun OUTFLOW.

## Supplier payments

GET/POST `/api/v1/businesses/{SH}/purchases/{PU}/payments/` et POST `/payments/{PP}/reverse/` sont réservés OWNER/MANAGER. Le POST accepte `amount`, `payment_method` et l'en-tête optionnel `Idempotency-Key`.

### Financial summary

`GET /businesses/{SH}/financial-summary/` accepte `date_from`, `date_to`, `payment_method`, `event_type`, `business_payment_method` et `recording_mode`. La réponse conserve `total_inflow`, `total_outflow`, `net_flow` et `by_payment_method`; elle ajoute les ventilations `by_category`, `by_business_payment_method` et `by_recording_mode`.

### Dashboard
`GET /businesses/{SH}/dashboard/` est réservé aux OWNER/MANAGER. Paramètres : `period`, ou `date_from` et `date_to`. La réponse compacte contient périodes, CA, cash, créances, rupture et dette fournisseur.
