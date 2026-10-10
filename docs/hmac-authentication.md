# Authentification HMAC des clients applicatifs

HMAC authentifie l'**application** qui appelle l'API E-commerce. Il ne
remplace jamais l'authentification utilisateur JWT ni les permissions métier.

```text
Client applicatif : request.ecommerce_client
Utilisateur JWT    : request.user
```

Le contrat est `Ecommerce-HMAC v1`. Une signature valable prouve seulement que
l'appelant détient le secret partagé ; l'accès aux données continue de dépendre
de `EcommerceJWTAuthentication`, de `require_permission` et du statut `ACTIVE`
du Business.

## Modèles

`ApiClient` est le registre. Il ne contient **aucun secret** :

| Champ | Role |
|---|---|
| `reference` | Reference publique opaque `AC` + 10 caracteres |
| `name` | Nom humain, par exemple `Ecommerce Web` |
| `client_id` | Identifiant technique stable envoye dans `X-Ecommerce-Client-Id` |
| `client_type` | `WEB`, `MOBILE_ANDROID`, `MOBILE_IOS`, `DESKTOP`, `PARTNER`, `INTERNAL_SERVICE`, `WORKER`, `OTHER` |
| `auth_method` | `HMAC`, `PLAY_INTEGRITY`, `APP_ATTEST`, `PUBLIC_KEY`, `OAUTH_CLIENT_CREDENTIALS`, `MTLS`, `NONE`, `OTHER` |
| `is_active` | Revocation immediate sans suppression |
| `last_seen_at` | Derniere authentification reussie, mise a jour avec throttling |
| `description`, `metadata` | Informations non sensibles |

`ClientNonce` enregistre chaque nonce consomme. La contrainte d'unicite
`(client, nonce)` est appliquee par PostgreSQL : la detection d'un rejeu reste
atomique avec plusieurs workers ou plusieurs instances, sans cache partage.

## En-tetes

```http
X-Ecommerce-Client-Id: ecommerce-web
X-Ecommerce-Timestamp: 1760000000
X-Ecommerce-Nonce: 5f2b7c1e-9a3d-4c8e-b1a6-0d4e2f8c9a01
X-Ecommerce-Content-SHA256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
X-Ecommerce-Signature-Version: v1
X-Ecommerce-Signature: <hmac sha256 hex>
```

Les six en-tetes sont obligatoires sur une route protegee. Le timestamp est un
entier en secondes Unix.

## Chaine canonique

```text
v1
{client_id}
{timestamp}
{nonce}
{METHOD}
{canonical_path_and_query}
{body_sha256}
```

- `METHOD` est en majuscules ;
- `canonical_path_and_query` est le chemin suivi de la requete canonisee : les
  parametres sont tries par cle puis valeur, les valeurs vides sont conservees
  et les parametres repetes sont conserves. Sans requete, seul le chemin est
  signe ;
- `body_sha256` est l'empreinte SHA-256 hexadecimale des octets bruts du corps,
  `e3b0c442...b855` pour un corps vide ;
- la signature est `HMAC-SHA256` du secret encodé en UTF-8 sur cette chaine,
  rendue en hexadecimal minuscules ;
- la comparaison de la signature et de l'empreinte du corps utilise
  `hmac.compare_digest`.

## Exemples reproductibles

Ces vecteurs utilisent un secret de demonstration qui n'est **jamais** un secret
reel. Ils sont verifies par `backend/apps/api_clients/tests/test_hmac_helpers.py`.

**Exemple 1 — GET avec requete**

Corps vide, `page=2`, `page_size=20`, timestamp `1760000000`, nonce
`5f2b7c1e-9a3d-4c8e-b1a6-0d4e2f8c9a01` :

```text
v1
ecommerce-web
1760000000
5f2b7c1e-9a3d-4c8e-b1a6-0d4e2f8c9a01
GET
/api/v1/businesses/?page=2&page_size=20
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
```

Signature attendue :

```text
f9ed028a8aea2533d551fba8f86197906edfa2cafefdb191ba37b0bacb86e6bb
```

**Exemple 2 — POST avec corps**

Corps `{"email":"membre@example.com","title":"Caissier"}`, timestamp
`1760000100`, nonce `8c1d4e2a-7b93-4f05-9d6a-3e5c7a1b2d40` :

```text
v1
ecommerce-web
1760000100
8c1d4e2a-7b93-4f05-9d6a-3e5c7a1b2d40
POST
/api/v1/businesses/SH23456789AB/invitations/
26588659a66e2d544f2dc0252081ee2c3225bb9a5eb4b0edbbda96eeeb60e930
```

Signature attendue :

```text
ffe9356b7e5814534731aa8644e0cca7156b19ee6c3819c5f58eeb61a454d52c
```

**Exemple 3 — GET sans requete**

Timestamp `1760000200`, nonce `a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d` :

```text
v1
ecommerce-web
1760000200
a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d
GET
/api/v1/me/business-invitations/MI23456789AB/accept/
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
```

Signature attendue :

```text
db4a311f9bf026d663dd1ca806c405e55f32c383fb8292345656ee8ba616fa84
```

Canonicalisation de reference : `b=2&a=1&a=0&empty=` devient
`a=0&a=1&b=2&empty=`.

## Timestamp et nonce

- `ECOMMERCE_HMAC_MAX_CLOCK_SKEW_SECONDS` (120 s par defaut) borne la fenetre,
  dans les deux sens : un timestamp trop ancien ou trop futur est refuse.
- Le nonce doit etre unique par client, par exemple un UUIDv4. Il est enregistre
  apres verification complete de la signature, jamais avant.
- `ECOMMERCE_HMAC_NONCE_TTL_SECONDS` (900 s par defaut) est la duree pendant
  laquelle un nonce reste enregistre et donc rejete. Elle depasse toujours la
  fenetre de tolerance d'horloge afin qu'un rejeu reste detectable.

## Rotation et revocation

Les secrets vivent exclusivement dans l'environnement.

```text
ECOMMERCE_HMAC_CLIENT_SECRETS={"ecommerce-web":{"current":"...","previous":"...","previous_expires_at":"2030-01-01T00:00:00Z"}}
```

Chaque entree accepte :

- `current` : secret courant, obligatoire ;
- `previous` : secret precedent, facultatif, accepté pendant la rotation ;
- `previous_expires_at` : date d'expiration **obligatoire si `previous` est
  present**, sous forme d'horodatage Unix ou de date ISO 8601. Un secret
  precedent sans date limite invalide la configuration au demarrage.

Procedure de rotation :

1. deployer avec `previous` = ancien secret et `current` = nouveau ;
2. deployer chaque client avec le nouveau secret ;
3. retirer `previous` au bout de la fenetre de grace choisie.

Revocation : `is_active=False` sur l'`ApiClient`. La signature est verifiee
**avant** l'etat d'activation, de sorte que seul un appelant detenant le secret
apprend qu'une cle est revoquee. La revocation est immediate et ne supprime pas
l'historique.

Un client mobile public ne peut pas etre configure en `HMAC` : `ApiClient.clean()`
le refuse, car un secret partage embarque dans une application est extractible.

## Modes

`ECOMMERCE_HMAC_MODE` :

| Mode | Comportement |
|---|---|
| `DISABLED` | aucune verification, defaut dans ce lot |
| `OBSERVATION` | verification et journalisation sans blocage. Ce mode n'est pas une protection : il doit etre presente comme une phase de mesure |
| `ENFORCE` | les routes protegees exigent une signature complete et valide |

La politique de routes depend **uniquement** de la methode et du chemin. Un
en-tete declare par le client (`User-Agent`, `X-Client-Type`, ...) n'est jamais
consulte : aucun appelant ne peut echapper a HMAC en se declarant mobile.

## Routes

`ECOMMERCE_HMAC_PROTECTED_PREFIXES` liste les prefixes exigeant HMAC,
`ECOMMERCE_HMAC_EXEMPT_METHODS` les methodes exemptees (`OPTIONS` par defaut).
La liste est une sous-liste validee des routes reservees au BFF codees cote
serveur : une variable d'environnement ne peut donc pas proteger par erreur
une route Android ou une route partagee.

| Operation | Politique | Motif |
|---|---|---|
| `POST /api/v1/auth/carri/handoff/consume/` | HMAC `ecommerce-web` obligatoire en `ENFORCE` | Le handoff Web est consomme par le BFF serveur a serveur. |
| `POST /api/v1/auth/token/refresh/` | exempt HMAC | Route de renouvellement partagee; aucune separation BFF n'existe encore. |
| `POST /api/v1/auth/carri/mobile/exchange/` | exempt HMAC | Flutter Android est un client public sans secret partage. |
| `GET /api/v1/auth/carri/login/`, `GET /api/v1/auth/carri/callback/` | exempt HMAC | Etapes du navigateur et du fournisseur OIDC. |
| routes metier `/api/v1/businesses/…` | exempt HMAC | Routes aujourd'hui partagees avec Android; JWT et permissions metier restent requis. |

Les futures routes internes exclusivement serveur a serveur doivent etre ajoutees
a la liste serveur `ECOMMERCE_HMAC_BFF_ONLY_PREFIXES`, annotees dans OpenAPI et
couvertes par des tests avant d'etre placees dans la configuration active.

La compatibilite Android ne repose pas sur une exemption conditionnelle mais sur
des endpoints distincts : `POST /api/v1/auth/carri/mobile/exchange/` reste
accessible en JWT + PKCE, car l'APK ne detient aucun secret. Les endpoints
reserves au BFF, comme la consommation du handoff OAuth, sont des chemins
separes, protegeables sans ambiguite.

Un endpoint appele directement par une application mobile ne peut pas devenir
HMAC obligatoire sans une separation explicite des endpoints; `User-Agent`,
`Origin` et `X-Client-Type` ne constituent jamais une preuve de plateforme.

## Erreurs

Reponse `{code, detail}` avec un message francais. Aucune erreur ne contient de
secret, de signature, de nonce ni de cle.

| Code | HTTP | Message |
|---|---|---|
| `client_signature_required` | 401 | La signature du client applicatif est obligatoire pour cette requête. |
| `client_signature_invalid` | 401 | La signature du client applicatif est invalide. |
| `client_signature_expired` | 401 | La signature du client applicatif a expiré, vérifiez l'horloge de l'appareil. |
| `client_signature_version_unsupported` | 401 | La version de la signature du client applicatif n'est pas prise en charge. |
| `client_request_replayed` | 401 | Cette requête signée a déjà été traitée. |
| `client_key_revoked` | 401 | La clé du client applicatif a été révoquée. |
| `client_body_hash_mismatch` | 400 | L'empreinte du corps de la requête ne correspond pas aux données reçues. |

Un `client_id` inconnu et un client sans secret configure reçoivent la **même**
reponse `client_signature_invalid`, afin de ne pas permettre d'enumerer les
clients enregistrees. La raison exacte est consignee dans les journaux applicatifs
sans valeur sensible.

## Journalisation

Les refus sont journalises avec `client_id`, la raison, la methode, le chemin et
le mode. Le secret, la signature et le nonce ne sont jamais journalises.

## Contexte de requête

Apres succes :

```text
request.ecommerce_client        = <ApiClient>
request.client_authenticated    = True
request.client_auth_method      = "HMAC"
request.hmac_verified           = True
request.hmac_client_id          = "ecommerce-web"
```

## OpenAPI

Le schema de securite `EcommerceClientHMAC` est publie comme `apiKey` dans
l'en-tete `X-Ecommerce-Signature`. Une operation exigeant a la fois le JWT et le
HMAC declare une **seule** exigence combinant les deux schema :

```json
{
  "security": [
    {
      "EcommerceJWT": [],
      "EcommerceClientHMAC": []
    }
  ]
}
```

Deux objets distincts exprimeraient une alternative, ce qui laisserait croire
qu'un seul des deux suffit.

## Purge des nonces

```bash
python backend/manage.py purge_client_nonces --seconds 900
```

Sans `--seconds`, la duree `ECOMMERCE_HMAC_NONCE_TTL_SECONDS` est utilisee. La
commande affiche le nombre de nonces supprimes.
