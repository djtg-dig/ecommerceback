# Authentication

Carri Account gère identité, inscription, mots de passe, consentement OAuth et preuves OIDC. Ecommerce gère CarriIdentity, validation OIDC, sessions ecommerce et autorisation métier.

`CarriIdentity` conserve `carri_subject` (le claim `sub`, unique et stable), une
projection de l'adresse Carri vérifiée et les dates d'observation de `userinfo`
et de `auth_time`. L'e-mail n'est jamais une clé d'identité et n'a pas de
contrainte d'unicité globale.

## Android

```mermaid
sequenceDiagram
Flutter->>Carri Account: Authorization Code + PKCE S256
Carri Account-->>Flutter: id_token + access_token
Flutter->>Ecommerce: mobile/exchange (id_token, access_token, nonce)
Ecommerce->>Ecommerce: RS256/JWKS, iss, aud, exp, iat, nonce, at_hash
Ecommerce->>Carri Account: userinfo(access_token)
Ecommerce-->>Flutter: JWT ecommerce
```

Android est public, sans secret; state et nonce sont obligatoires. Flutter doit
demander `openid email`. Une adresse transmise directement par Flutter n'est
jamais une preuve. `IDTokenReplay` conserve le hash d'une preuve acceptée
jusqu'à `exp`.

## Web

Le backend demande `openid email`, utilise Authorization Code + PKCE, garde
state hashé, nonce et verifier dans `OAuthLoginAttempt`, puis crée un handoff
opaque et à usage unique. Les JWT ecommerce ne passent jamais dans une URL.

Le contrat JSON historique du callback est conservé. Pour le BFF Next.js,
`GET /api/v1/auth/carri/login/?delivery=nextjs&delivery_binding=<opaque>`
sélectionne uniquement `CARRI_ACCOUNT_WEB_HANDOFF_DELIVERY_URL`, une URL fixe
validée côté serveur. Il n'accepte aucune URL de destination navigateur. Après
la validation OIDC, Django retourne une page `no-store` et `no-referrer` qui
POSTe `handoff` et `delivery_binding` vers cette URL; aucun handoff ne figure
dans la query string et aucun JWT n'est produit dans le HTML.

Le formulaire transmet `application/x-www-form-urlencoded` avec les champs
`handoff` et `delivery_binding`. Django pose pour le callback un cookie
`HttpOnly`, `Secure` hors DEBUG et `SameSite=Lax` : le callback Carri Account
revient en navigation principale GET, pour laquelle Lax est adapté. Le BFF
Next.js doit créer avant la redirection son propre cookie de transaction
`HttpOnly; Secure; SameSite=None` (HTTPS requis) afin qu'il accompagne le POST
inter-origines. Le BFF compare le binding reçu à ce cookie, puis consomme le
handoff côté serveur avec HMAC. Le binding est stocké hashé dans la tentative
OAuth et lié au `state`; il ne peut donc pas être remplacé indépendamment.
`Origin` et `Sec-Fetch-Site` peuvent compléter le contrôle côté BFF, sans
remplacer le cookie transactionnel.

Le handoff Next est lié au client applicatif `ecommerce-web`; il échoue fermé
sans signature HMAC vérifiée de ce client. Configurer le mode HMAC `ENFORCE` en
production. Le mode `DISABLED` refuse ces handoffs. Les handoffs historiques
non liés conservent le callback JSON et leur comportement de consommation.

La page est `Cache-Control: no-store`, `Referrer-Policy: no-referrer`,
`X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `noindex` et CSP
restrictive. Le handoff est temporaire (120 secondes par défaut, plafonné à
300 secondes pour Next.js), à usage unique, hashé en base, absent des URLs et
des journaux. Aucun JWT n'est émis par
le callback ni inclus dans le HTML. Django ne peut pas confirmer que le
navigateur a achevé le POST inter-origines; en cas d'échec du POST ou de
consommation, le récepteur Next affiche `handoff_delivery_failed` sans révéler
le handoff.

Discovery est obtenu via `{issuer}/.well-known/openid-configuration`; les endpoints et JWKS ne sont pas codés en dur. Validation : RS256, kid, signature, iss, aud, exp, iat, sub, nonce, nbf/azp si présents et at_hash.

Après validation de l'ID token, le backend appelle `userinfo` avec l'access
token lié par `at_hash`. Il exige `userinfo.public_id == sub`, un booléen
`email_verified` strictement égal à `true` et une adresse valide, ensuite
normalisée par `trim` + minuscules. Une réponse absente, incohérente ou une
erreur réseau interrompt l'authentification sans écraser une preuve antérieure.

La preuve destinée aux futures invitations est fraîche pendant 10 minutes. Le
contrôle porte séparément sur la date serveur d'observation de `userinfo` et
sur `auth_time`. Un JWT ecommerce ancien, ou une identité créée avant cette
projection, impose une nouvelle authentification Carri.

Les JWT ecommerce portent `identity_id`; EcommerceJWTAuthentication résout CarriIdentity. Variables : `CARRI_ACCOUNT_ISSUER`, `CARRI_ACCOUNT_CLIENT_ID`, `CARRI_ACCOUNT_CLIENT_SECRET`, `CARRI_ACCOUNT_REDIRECT_URI`, `CARRI_ACCOUNT_SCOPES`, `CARRI_ACCOUNT_ANDROID_CLIENT_ID`, `CARRI_ACCOUNT_ANDROID_REDIRECT_URI`, `CARRI_ACCOUNT_DISCOVERY_CACHE_SECONDS`, `CARRI_ACCOUNT_JWKS_CACHE_SECONDS`, `CARRI_ACCOUNT_ID_TOKEN_CLOCK_SKEW_SECONDS`, `CARRI_ACCOUNT_EMAIL_PROOF_MAX_AGE_SECONDS`.

Aucun token ou secret ne doit être loggé ou versionné. La blacklist SimpleJWT n'est pas utilisée car l'identité n'est pas AUTH_USER_MODEL; une révocation ecommerce dédiée reste nécessaire avant production.

## Authentification applicative HMAC

En complément du JWT utilisateur, `EcommerceClientHMACMiddleware` identifie l'application appelante. Le contrat complet, les en-têtes, la chaîne canonique, les vecteurs de signature, la rotation des clés, les codes d'erreur et la politique de routes sont décrits dans [Authentification HMAC des clients applicatifs](hmac-authentication.md).

Points structurants :

- HMAC n'est **jamais** un substitut au JWT utilisateur ni aux permissions métier ;
- les secrets vivent uniquement dans l'environnement, jamais en base ni en dépôt ;
- la politique de routes dépend de la méthode et du chemin, jamais d'un en-tête déclaré par le client ;
- Flutter Android n'embarque aucun secret HMAC partagé et conserve JWT + PKCE S256 ;
- Next.js conserve le secret côté serveur dans son BFF et ne signe jamais depuis le navigateur ;
- le mode est `DISABLED`, `OBSERVATION` ou `ENFORCE`; l'activation locale vise
  uniquement `POST /api/v1/auth/carri/handoff/consume/`;
- le renouvellement `POST /api/v1/auth/token/refresh/` reste sans HMAC car il
  est partage avec les clients existants; sa protection requerra une separation
  BFF explicite.

## Flux par plateforme

| Plateforme | Authentification applicative | Stockage des secrets |
|---|---|---|
| Flutter Android | aucune signature HMAC ; JWT ecommerce + PKCE S256 | aucun secret embarqué |
| Next.js Web | HMAC côté serveur, signé par le BFF uniquement | variable d'environnement du serveur |
| Flutter Desktop | client public, aucune signature HMAC | aucun secret embarqué |

Toutes les variables HMAC sont listées dans [API](api.md#authentification-hmac-des-clients-applicatifs).
