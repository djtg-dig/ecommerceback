# Invitations de membres Business

Les endpoints administratifs utilisent un JWT E-commerce et les identifiants
publics `SH` (Business) et `MI` (invitation). Ils exigent un OWNER actif ou un
membre actif disposant explicitement de `MANAGE_MEMBERS`. Un ancien rôle ou un
titre professionnel n'accorde aucun accès. Un tenant étranger répond `404`, un
membre connu sans permission répond `403`.

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
- `404` : entreprise inaccessible ;
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
immédiatement invalidé. Codes : `200`, `403`, `404`, `409`, `503`.

## Révoquer

`POST /api/v1/businesses/{SH}/invitations/{MI}/revoke/`

Aucun corps JSON. Seule une invitation effectivement `PENDING` est révoquée,
sous transaction et verrou de ligne. Son jeton n'est plus utilisable. Codes :
`200`, `403`, `404`, `409`.

## Livraison et reprise

`BUSINESS_MEMBER_INVITATION_URL` doit être une URL HTTP(S) absolue et
`DEFAULT_FROM_EMAIL` doit être configuré. Le lien ajoute le jeton en paramètre
`token` sans supprimer les paramètres existants. Les e-mails texte et HTML
indiquent l'entreprise, le titre éventuel, l'adresse destinataire et
l'expiration.

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

Après validation du MI, du hash du jeton, de l'identité et du Business actif,
le service crée dans la même transaction un `BusinessMember` actif avec le
titre proposé. Il reste non propriétaire et ne reçoit aucune permission. Le
jeton est consommé par le passage à `ACCEPTED` et ne peut plus être réutilisé.

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

Le corps et les contrôles d'identité sont identiques à l'acceptation. Le service
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
appartenance existante avec `transaction.atomic`/`select_for_update`. Une
acceptation concurrente ne crée donc qu'un membre. L'ancien jeton devient
invalide dès un renvoi. Le statut `REMOVED` reste terminal conformément au
cycle de vie actuel : une réinvitation ne réactive pas silencieusement cette
ligne et ne restaure jamais ses anciennes permissions. E-commerce ne possède
actuellement ni abonnement ni quota de sièges ; aucune limite artificielle
n'est appliquée dans ce flux.
