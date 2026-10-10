# Invitations de membres Business

Les endpoints administratifs utilisent un JWT E-commerce et les identifiants
publics `SH` (Business) et `MI` (invitation). Ils exigent un OWNER actif ou un
membre actif disposant explicitement de `MANAGE_MEMBERS`. Un ancien rôle ou un
titre professionnel n'accorde aucun accès. Un tenant étranger répond `404`, un
membre connu sans permission répond `403`.

Les réponses ne contiennent jamais `token`, `token_hash`, UUID interne ou
permission future. Une invitation ne crée aucun `BusinessMember` et n'attribue
aucune permission avant une acceptation, qui reste hors de ce lot.

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

