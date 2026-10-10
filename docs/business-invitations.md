# Invitations de membres Business

Les endpoints administratifs utilisent un JWT E-commerce et les identifiants
publics `SH` (Business) et `MI` (invitation). Ils exigent un OWNER actif ou un
membre actif disposant explicitement de `MANAGE_MEMBERS`. Un ancien rôle ou un
titre professionnel n'accorde aucun accès. Un Business inconnu répond `404`
`business_not_found` ; une invitation inconnue du tenant répond `404`
`invitation_not_found` ; un membre connu sans permission répond `403`
`invitation_permission_denied`.

Les réponses ne contiennent jamais `token`, `token_hash`, UUID interne ou
permission future. Une invitation ne crée aucun `BusinessMember` et n'attribue
aucune permission avant son acceptation explicite par le destinataire.

## Lister les invitations

`GET /api/v1/businesses/{SH}/invitations/?page=1&page_size=20`

Retourne les invitations de l'entreprise, états terminaux compris, dans un
ordre stable du plus récent au plus ancien. `page_size` vaut 20 par défaut et
50 au maximum.

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "public_id": "MI23456789AB",
      "email": "membre@example.com",
      "title": "Caissier",
      "status": "PENDING",
      "expires_at": "2026-10-17T10:00:00+01:00",
      "last_sent_at": "2026-10-10T10:00:01+01:00",
      "resend_count": 0,
      "created_at": "2026-10-10T10:00:00+01:00",
      "updated_at": "2026-10-10T10:00:01+01:00"
    }
  ]
}
```

Codes : `200`, `403`, `404`.

## Créer et envoyer une invitation

`POST /api/v1/businesses/{SH}/invitations/`

```json
{
  "email": "membre@example.com",
  "title": "Caissier"
}
```

`email` est obligatoire et normalisé par `trim` puis minuscules. `title` est
facultatif, descriptif, limité à 120 caractères et ne confère aucun droit.
Une adresse correspondant à un membre actif ou suspendu est refusée. Une seule
invitation `PENDING` est autorisée par entreprise et adresse.

La réponse `201` utilise la projection compacte montrée ci-dessus. Erreurs :

- `400 invalid_email` : « Veuillez saisir une adresse e-mail valide. » ;
- `403 invitation_permission_denied` : permission insuffisante ;
- `404 business_not_found` : entreprise inaccessible ;
- `409 invitation_already_pending` : invitation ouverte existante ;
- `409 business_member_already_exists` : membre actif ou suspendu existant ;
- `409 business_inactive` : entreprise suspendue ou archivée ;
- `503 invitation_delivery_unavailable` : configuration ou fournisseur
  d'e-mail indisponible.

Exemple de conflit :

```json
{
  "code": "invitation_already_pending",
  "detail": "Une invitation est déjà en attente pour cette adresse e-mail.",
  "email": ["Une invitation est déjà en attente pour cette adresse e-mail."]
}
```

## Renvoyer

`POST /api/v1/businesses/{SH}/invitations/{MI}/resend/`

Aucun corps JSON. Une invitation `PENDING` ou expirée reçoit un nouveau jeton,
une nouvelle expiration et `resend_count` est incrémenté. L'ancien jeton est
immédiatement invalidé : les liens déjà envoyés cessent de fonctionner.

Effets de bord : un nouvel e-mail est programmé après le commit et un échec de
livraison laisse l'invitation `PENDING` avec `last_sent_at` inchangé, prête pour
un nouveau renvoi.

Erreurs :

- `403 invitation_permission_denied` ;
- `404 business_not_found` / `404 invitation_not_found` ;
- `409 invitation_cannot_be_resent` : invitation déjà acceptée ou refusée ;
- `409 invitation_revoked` : invitation révoquée ;
- `409 business_inactive` : entreprise suspendue ou archivée ;
- `503 invitation_delivery_unavailable` : configuration ou fournisseur
  d'e-mail indisponible.

Codes de succès : `200`.

## Révoquer

`POST /api/v1/businesses/{SH}/invitations/{MI}/revoke/`

Aucun corps JSON. Seule une invitation effectivement `PENDING` est révoquée,
sous transaction et verrou de ligne. Son jeton n'est plus utilisable et une
acceptation concurrente déjà engagée peut légitimement gagner la course : la
réponse `200` reflète alors l'état `REVOKED` de l'invitation.

Effets de bord : aucun `BusinessMember` n'est créé, aucune permission n'est
modifiée, `acted_at` est renseigné.

Erreurs :

- `403 invitation_permission_denied` ;
- `404 business_not_found` / `404 invitation_not_found` ;
- `409 invitation_expired` : invitation expirée, demander un nouveau lien ;
- `409 invitation_revoked` : invitation déjà révoquée ;
- `409 invitation_cannot_be_revoked` : invitation déjà acceptée ou refusée ;
- `409 business_inactive` : entreprise suspendue ou archivée.

Codes de succès : `200`.

## Livraison et reprise

`BUSINESS_MEMBER_INVITATION_URL` doit être une URL HTTP(S) absolue et
`DEFAULT_FROM_EMAIL` doit être configuré. Si l'une des deux manque, rien n'est
persisté et l'API répond `503 invitation_delivery_unavailable`.

### Contrat du lien

Le backend construit le lien en ajoutant deux paramètres de requête à l'URL
configurée, sans supprimer ni réécrire les paramètres déjà présents :

```text
{BUSINESS_MEMBER_INVITATION_URL}?invitation={MI}&token={jeton}
```

- `invitation` : identifiant public de l'invitation (`MI` + 10 caractères), celui
  qui apparaît dans la liste administrative et dans les réponses ;
- `token` : secret à usage unique de 43 caractères (`token_urlsafe(32)`), stocké
  uniquement sous forme de hash SHA-256 et jamais renvoyé par l'API ;
- l'ordre des paramètres n'est pas contractuel : `invitation` puis `token` sont
  ajoutés après les paramètres existants de l'URL configurée.

Exemple :

```text
https://app.example.com/business-invitations?invitation=MI23456789AB&token=J_jWDcgm6ZcX3eN-xQA3wjHCYlAXYu35A8oIp8wNwYY
```

Le jeton n'est écrit dans aucun journal et n'apparaît dans aucune réponse JSON.
La rotation du jeton lors d'un renvoi invalide immédiatement l'ancien lien.

### Parcours frontend attendu

1. Le destinataire ouvre le lien ; le frontend lit `invitation` et `token` dans
   la query string et les conserve en mémoire (ou en état de route), sans les
   écrire dans un journal ni dans une URL partagée.
2. S'il n'a pas de session E-commerce valide, il déclenche l'authentification
   Carri Account (`GET /api/v1/auth/carri/login/` puis
   `GET /api/v1/auth/carri/callback/` et `POST /api/v1/auth/carri/handoff/consume/`).
   Le jeton d'invitation n'est jamais transmis dans les paramètres OAuth : le
   backend génère son propre `state`/`nonce`.
3. Après la redirection OAuth, le frontend reprend l'invitation qu'il a conservée
   localement : le retour Carri ne transporte aucune donnée d'invitation.
4. Il appelle `POST /api/v1/me/business-invitations/{invitation}/accept/` ou
   `.../decline/` avec `{"token": "..."}` dans le corps, jamais dans l'URL.
5. Une réponse `401 carri_reauthentication_required` impose de recommencer
   l'étape 2 puis de rejouer l'étape 4 avec le même couple `invitation`/`token`.

Les e-mails texte et HTML indiquent l'entreprise, le titre éventuel, l'adresse
destinataire et l'expiration.

L'envoi est enregistré avec `transaction.on_commit`. `last_sent_at` n'est mis
à jour qu'après succès du backend e-mail. Si le fournisseur échoue après le
commit, l'API répond `503` mais l'invitation reste `PENDING`, non marquée comme
envoyée, et visible dans la liste afin qu'un administrateur utilise `resend`.
Le renvoi effectue toujours une nouvelle rotation du jeton. Cette stratégie ne
constitue pas une file de messages durable : un worker/outbox transactionnel
sera nécessaire si la livraison asynchrone garantie devient une exigence.

Variables :

```text
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
DEFAULT_FROM_EMAIL=E-commerce <no-reply@example.com>
BUSINESS_MEMBER_INVITATION_URL=https://app.example.com/business-invitations
BUSINESS_MEMBER_INVITATION_EXPIRY_HOURS=168
```

L'URL publique réelle doit être fournie par chaque environnement. Aucun domaine
Flutter ou de production n'est codé en dur.

## Accepter une invitation

`POST /api/v1/me/business-invitations/{MI}/accept/`

Permission : aucune permission Business n'est requise ; seul le JWT E-commerce du
destinataire authentifié est exigé. Aucun paramètre de requête, le jeton circule
exclusivement dans le corps.

```json
{
  "token": "secret-recu-dans-le-lien"
}
```

L'appel exige un JWT E-commerce. L'identité correspondante doit disposer d'une
adresse obtenue de `userinfo`, vérifiée par Carri et observée depuis moins de
10 minutes. La dernière authentification OIDC (`auth_time`) doit également
dater de moins de 10 minutes. L'adresse normalisée doit correspondre exactement
à l'invitation ; aucune adresse envoyée par le client n'est acceptée comme
preuve.

Règles métier et effets de bord, dans une seule transaction :

- le Business, l'identité Carri, l'invitation et toute appartenance existante
  sont verrouillés avant décision ;
- un `BusinessMember` `ACTIVE`, `role=EMPLOYEE`, non propriétaire, portant le
  titre proposé, est créé ; aucune permission ne lui est attribuée ;
- l'invitation passe `ACCEPTED` avec `accepted_by` et `acted_at` renseignés, ce
  qui consomme le jeton ;
- une appartenance déjà présente, même `REMOVED`, est refusée par `409` sans
  réactivation silencieuse de l'ancienne ligne.

Réponse `200` :

```json
{
  "public_id": "MI23456789AB",
  "status": "ACCEPTED",
  "business_public_id": "SH23456789AB",
  "business_name": "Commerce Exemple",
  "member_public_id": "BM23456789AB",
  "member_title": "Caissier",
  "acted_at": "2026-10-10T10:05:00+01:00"
}
```

## Refuser une invitation

`POST /api/v1/me/business-invitations/{MI}/decline/`

Permission, corps et contrôles d'identité identiques à l'acceptation. Le service
place l'invitation en `DECLINED`, renseigne `declined_by` et `acted_at`, sans
créer de membre ni modifier de permission. Une invitation refusée ne peut plus
être acceptée.

## Erreurs du parcours destinataire

Les deux endpoints utilisent `{code, detail}` et, pour une erreur de payload,
une liste `token` :

- `400 invalid_invitation_token` : jeton absent, mal formé ou ne correspondant
  pas au MI ;
- `401 carri_reauthentication_required` : observation `userinfo` ou
  `auth_time` trop ancienne ; le client doit relancer le parcours OIDC Carri ;
- `403 verified_email_required` : adresse Carri absente ou non vérifiée ;
- `403 invitation_recipient_mismatch` : autre compte Carri ;
- `404 invitation_not_found` : MI inconnu ;
- `409 invitation_already_processed` : invitation déjà acceptée ou refusée ;
- `409 business_member_already_exists` : appartenance déjà présente ;
- `409 business_inactive` : entreprise suspendue ou archivée ;
- `410 invitation_expired` ou `410 invitation_revoked` : lien définitivement
  inutilisable.

Les services verrouillent le Business, l'identité, l'invitation et toute
appartenance existante avec `transaction.atomic`/`select_for_update`. Les
scénarios concurrents suivants sont couverts et ne produisent jamais de membre
dupliqué ni de permission implicite :

- **Deux acceptations simultanées** : la première crée le membre, la seconde
  reçoit `409 invitation_already_processed` ; une seule ligne `BusinessMember`
  existe (contrainte d'unicité `business` + `identity` en secours) ;
- **Acceptation pendant une révocation** : les deux opérations verrouillent la
  même ligne d'invitation ; selon l'ordre, l'acceptation gagne (membre créé,
  invitation `ACCEPTED`, la révocation échoue avec `409`) ou la révocation gagne
  (`410 invitation_revoked`) ; aucun état intermédiaire n'est exposé ;
- **Acceptation pendant un renvoi** : si le renvoi gagne, le jeton présenté
  devient caduc (`400 invalid_invitation_token`) car son hash a été remplacé ;
- **Acceptation pendant une expiration** : l'invitation passe `EXPIRED` dans la
  transaction et la réponse est `410 invitation_expired` ;
- **Acceptation pendant une suspension du Business** : `409 business_inactive`,
  aucun membre n'est créé ;
- **Double soumission du formulaire** : la seconde soumission est refusée par
  l'état terminal de l'invitation (`409`) ou par l'appartenance existante
  (`409 business_member_already_exists`) ;
- **Renvoi après un échec d'e-mail** : l'invitation reste `PENDING`, non marquée
  comme envoyée, et le renvoi remet un jeton neuf en circulation.

L'ancien jeton devient invalide dès un renvoi. Le statut `REMOVED` reste
terminal conformément au cycle de vie actuel : une réinvitation ne réactive pas
silencieusement cette ligne et ne restaure jamais ses anciennes permissions.
E-commerce ne possède actuellement ni abonnement ni quota de sièges ; aucune
limite artificielle n'est appliquée dans ce flux.
