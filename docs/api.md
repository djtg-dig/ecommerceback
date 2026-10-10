# API

| Endpoint | Auth | But |
|---|---|---|
| GET `/api/v1/health/` | public | liveness `{"status":"ok"}` |
| POST `/api/v1/auth/carri/mobile/exchange/` | public | échange preuve Android `{id_token,access_token,nonce}` contre JWT ecommerce |
| GET `/api/v1/auth/carri/login/` | public | redirection Web OIDC; `delivery=nextjs` active la livraison POST vers l'URL serveur allowlistée |
| GET `/api/v1/auth/carri/callback/` | public | valide callback et retourne le handoff JSON historique, ou une page de livraison POST Next.js |
| POST `/api/v1/auth/carri/handoff/consume/` | HMAC `ecommerce-web`, handoff | consomme le handoff une fois et retourne JWT ecommerce |
| GET `/api/v1/auth/me/` | JWT ecommerce | `{id,carri_subject}` |
| GET `/api/v1/product-categories/` | public | catégories globales actives, à plat (`parent_code`, `level`) |
| GET `/api/v1/product-categories/{code}/attributes/` | public | attributs actifs effectifs et leurs options actives |
| POST `/api/v1/auth/token/refresh/` | refresh ecommerce | renouvelle les tokens |
| GET/POST `/api/v1/businesses/` | JWT ecommerce | liste isolée / crée Business + OWNER |
| GET/PATCH `/api/v1/businesses/{id}/` | membre actif | détail / modification OWNER ou permission explicite |
| GET `/api/v1/businesses/{id}/members/` | OWNER ou `VIEW_MEMBERS` | memberships sans données Carri |
| GET/POST `/api/v1/businesses/{SH}/invitations/` | OWNER ou `MANAGE_MEMBERS` | liste paginée / crée et envoie une invitation |
| POST `/api/v1/businesses/{SH}/invitations/{MI}/resend/` | OWNER ou `MANAGE_MEMBERS` | rotation du jeton et nouvel envoi |
| POST `/api/v1/businesses/{SH}/invitations/{MI}/revoke/` | OWNER ou `MANAGE_MEMBERS` | révocation transactionnelle |

Un Business inconnu répond `404 business_not_found`, une invitation inconnue du
tenant `404 invitation_not_found`. Le lien e-mail transmis au destinataire porte
`?invitation={MI}&token={jeton}`. Le contrat détaillé des invitations, exemples
et erreurs stables est décrit dans [Business member invitations](business-invitations.md).

La propriété administrative (`is_owner`), le titre professionnel (`title`) et les permissions individuelles sont indépendants. Un titre tel que Gérant, Gestionnaire ou Caissier n'accorde jamais de droit. L'OWNER actif dispose implicitement de toutes les permissions; les autres membres commencent sans permission et un membre SUSPENDED n'accède plus au Business. Le champ `role` reste exposé temporairement pour compatibilité legacy mais n'est plus une source d'autorisation. Durant la transition des endpoints métier, la mention historique « MANAGER » dans les tableaux ci-dessous désigne un membre auquel l'OWNER a explicitement attribué la permission transitoire requise, actuellement `UPDATE_BUSINESS`; le seul titre ou l'ancien rôle MANAGER ne suffit plus.

Le moteur central refuse tout nom de permission inconnu. L'absence d'appartenance au Business produit `404`; un membre existant sans permission, ou suspendu, produit `403`. Un Business `SUSPENDED` ou `ARCHIVED` reste consultable pour les informations administratives autorisées, mais le moteur refuse ses écritures métier. Pour le MVP, seul l'OWNER actif accorde ou révoque les permissions individuelles.

Business routes use `public_id` (`SHXXXXXXXXXX`), never the internal UUID: `GET/PATCH /api/v1/businesses/{public_id}/` and `GET /api/v1/businesses/{public_id}/members/`. Create and PATCH accept `categories` (codes) and optional `primary_category`; OWNER and MANAGER may change them. `GET /api/v1/business-categories/` is public and returns active platform categories only.

Le destinataire authentifié traite une invitation via
`POST /api/v1/me/business-invitations/{MI}/accept/` ou `.../decline/`, avec
`{"token": "..."}`. Ces routes n'exigent pas `MANAGE_MEMBERS` mais imposent une
adresse Carri vérifiée et une preuve OIDC récente de 10 minutes. Le contrat
détaillé, les réponses et les codes stables figurent dans
[Invitations Business](business-invitations.md).

## Livraison de handoff Next.js

Le navigateur démarre le flux avec `delivery=nextjs` et un
`delivery_binding` aléatoire généré par Next.js. Django n'accepte pas de
`redirect_uri` ou d'URL de livraison depuis le navigateur :
`CARRI_ACCOUNT_WEB_HANDOFF_DELIVERY_URL` est la seule destination possible.
Après le callback OIDC, Django répond `200 text/html` avec les en-têtes
`Cache-Control: no-store`, `Referrer-Policy: no-referrer`, `X-Frame-Options:
DENY`, CSP restrictive et un formulaire qui effectue :

```http
POST <CARRI_ACCOUNT_WEB_HANDOFF_DELIVERY_URL>
Content-Type: application/x-www-form-urlencoded

handoff=<opaque>&delivery_binding=<opaque>
```

Le handoff est opaque, valide au plus
`CARRI_ACCOUNT_HANDOFF_TTL_SECONDS` (120 secondes par défaut, plafonné à 300
secondes pour Next.js) et utilisable une fois. Il est transmis en formulaire
`application/x-www-form-urlencoded` avec
les champs `handoff` et `delivery_binding`, jamais dans l'URL. La page est
`no-store`, `no-referrer`, `noindex`, protégée par CSP et ne contient aucun
JWT. Le cookie Django du callback est `SameSite=Lax` (retour OAuth GET); le
cookie transactionnel Next doit être `HttpOnly; Secure; SameSite=None` pour
accompagner le POST inter-origines. Next.js compare le binding au cookie avant
de transmettre le handoff côté serveur à `POST
/api/v1/auth/carri/handoff/consume/` avec les six en-têtes Ecommerce-HMAC v1.
Les handoffs Next sont liés au client `ecommerce-web`; les handoffs JSON
historiques non liés restent compatibles.

Exemple de traitement dans le récepteur Next.js (adapter les appels cookies et
redirect à la version Next installée) :

```ts
const form = await request.formData();
const handoff = String(form.get("handoff") ?? "");
const binding = String(form.get("delivery_binding") ?? "");
const transaction = await readHttpOnlyTransactionCookie();

if (!handoff || !transaction || !constantTimeEqual(binding, transaction)) {
  return Response.json(
    { code: "handoff_delivery_binding_invalid", detail: "La liaison de livraison du handoff est invalide." },
    { status: 400 },
  );
}

const tokens = await consumeHandoffWithEcommerceHmac(handoff);
// Stocker les JWT en cookies HttpOnly; ne jamais les renvoyer au navigateur.
return redirectWithHttpOnlySession(tokens, "/");
```

Codes stables : `oauth_login_csrf_detected`,
`oauth_state_invalid_or_expired`,
`oauth_configuration_unavailable`, `oauth_provider_unavailable`,
`oauth_authorization_denied`, `oauth_proof_invalid`, `oauth_callback_invalid`,
`handoff_delivery_destination_not_allowed`,
`handoff_delivery_binding_invalid`, `handoff_missing`, `handoff_invalid`,
`handoff_expired`, `handoff_already_consumed` et
`handoff_client_not_authorized`. Si le POST ou l'appel HMAC échoue, le récepteur
Next.js affiche `handoff_delivery_failed` (« La livraison sécurisée de la
connexion a échoué. Veuillez recommencer. ») sans inclure le handoff dans la
réponse ou les journaux. Django ne peut pas confirmer la navigation ultérieure
du navigateur; cette réponse relève du récepteur Next.js.

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

Le schéma de sécurité `EcommerceClientHMAC` décrit l'authentification applicative HMAC. Une opération exigeant à la fois le JWT utilisateur et le HMAC applicatif déclare une seule exigence combinée, jamais deux objets séparés qui exprimeraient une alternative.

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
Routes internes : `/customers/`, `/sales/`, `/sales/{SA}/lines/`, `/complete/`, `/cancel/` et `/sales/{SA}/returns/`.

### Sale Returns

`GET/POST /api/v1/businesses/{SH}/sales/{SA}/returns/` est réservé aux OWNER et MANAGER actifs. Un EMPLOYEE reçoit `403`; un utilisateur sans accès au Business ou une Sale hors de ce Business reçoit `404`.

Le POST exécute en un seul appel le retour, la réintégration stock, le crédit de créance et l’éventuel remboursement. L’en-tête HTTP `Idempotency-Key` est obligatoire; son absence répond `400`. La même clé avec le même payload retourne le même `SaleReturn` sans dupliquer aucun effet. La même clé avec un payload différent répond `409`.

```http
Idempotency-Key: mobile-return-42
```

```json
{
  "reason": "Article non conforme",
  "returned_at": "2026-10-08T09:30:00+01:00",
  "refund_payment_method": "PMXXXXXXXXXX",
  "lines": [
    {"sale_line": "SLXXXXXXXXXX", "quantity": "2.000"}
  ]
}
```

`refund_payment_method` est facultatif et nullable lorsque le montant calculé du remboursement est zéro. Lorsqu’un remboursement est dû, il doit référencer une méthode active du même Business. Les erreurs de quantité, statut de vente, appartenance de ligne ou moyen de remboursement répondent `400`.

La réponse compacte contient `public_id`, `status`, `reason`, `returned_at`, `return_total`, `receivable_credit_amount`, `refund_amount`, la référence publique `refund_payment_method` ou `null`, et les lignes avec leurs identifiants publics, quantité, snapshots prix/coût et `line_total`. Le GET retourne la même projection dans une pagination `count/next/previous/results`, avec 20 éléments par défaut et un `page_size` maximal de 50. Il ne liste que les retours de la Sale demandée et précharge leurs relations pour éviter les requêtes N+1.

Les retours peuvent être partiels, totaux et successifs dans la limite cumulée de la quantité vendue. Une cible Product ou ProductVariant archivée après la vente reste retournable sans être réactivée. Il n’existe pas d’endpoint de modification, suppression ou reversal du retour dans le Lot 1.

Dashboard, `profitability-summary` et les rapports Sales, Products et Receivables intègrent les retours `POSTED`. Les ventes sont imputées selon `completed_at`, les retours économiques selon `returned_at`, et les remboursements monétaires restent des OUTFLOW Finance distincts.

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

### Reporting économique

Les endpoints OWNER/MANAGER `profitability-summary/`, `reports/sales/`, `reports/products/`, `reports/expenses/` et `reports/receivables/` agrègent côté serveur et restent isolés par Business. Les trois premiers exposent séparément les ventes brutes, retours et valeurs nettes. `reports/receivables/` est paginé et distingue montant initial, paiements, crédits retour et solde par client. Les crédits `RETURN_CREDIT` ne sont jamais présentés comme des encaissements.

## Authentification HMAC des clients applicatifs

`ApiClient` registre les applications autorisées, `ClientNonce` rend chaque requête signée à usage unique. Le contrat complet — en-têtes, chaîne canonique, vecteurs de signature, timestamp, nonce, rotation, révocation, codes d'erreur, routes protégées et exemptées — est décrit dans [Authentification HMAC des clients applicatifs](hmac-authentication.md).

| Variable | Défaut | Rôle |
|---|---|---|
| `ECOMMERCE_HMAC_MODE` | `DISABLED` | `DISABLED`, `OBSERVATION` ou `ENFORCE` |
| `ECOMMERCE_HMAC_CLIENT_SECRETS` | vide | objet JSON `{client_id: {current, previous, previous_expires_at}}` |
| `ECOMMERCE_HMAC_MAX_CLOCK_SKEW_SECONDS` | `120` | tolérance d'horloge en secondes |
| `ECOMMERCE_HMAC_NONCE_TTL_SECONDS` | `900` | durée de conservation d'un nonce rejoué |
| `ECOMMERCE_HMAC_MAX_BODY_BYTES` | `1000000` | taille maximale du corps signé |
| `ECOMMERCE_HMAC_REQUIRE_BODY_HASH` | `true` | impose `X-Ecommerce-Content-SHA256` |
| `ECOMMERCE_HMAC_PROTECTED_PREFIXES` | `/api/v1/auth/carri/handoff/consume/` | sous-liste des seules routes BFF reservees cote serveur |
| `ECOMMERCE_HMAC_EXEMPT_METHODS` | `OPTIONS` | méthodes exemptées |

La route BFF effectivement protegee en `ENFORCE` est
`POST /api/v1/auth/carri/handoff/consume/`. Les routes Android, le refresh JWT
et les routes metier partagees restent exemptes. Les en-tetes declares par le
client ne modifient jamais cette politique. Un ancien secret de rotation exige
toujours `previous_expires_at`.

## Registre des clients applicatifs

| Usage | Modèle | Remarques |
|---|---|---|
| Recenser un client | `ApiClient` | `client_id` unique, `client_type`, `auth_method`, `is_active`, `last_seen_at` |
| Purger les nonces expirés | `python backend/manage.py purge_client_nonces` | suppression par `seen_at`, rétention configurable |
| Révoquer un client | `ApiClient.is_active = False` | effet immédiat, historique conservé |

Un client mobile public ne peut pas être configuré en `HMAC` : la validation du modèle le refuse.
