# Infrastructure temps réel

Ce document décrit uniquement le socle Channels/Redis/ASGI. Aucun modèle de
conversation, consumer métier ou endpoint WebSocket public n'est encore
fourni.

## État de l'architecture

- Django continue de servir les API REST sous ASGI et conserve son entrée WSGI.
- Daphne fournit le serveur ASGI et remplace `runserver` en développement.
- `channels-redis` utilise `REDIS_URL`; la couche mémoire n'est jamais activée
  par les paramètres de production.
- `config.asgi.application` route HTTP vers Django et WebSocket vers un
  `OriginValidator` exact.
- `config.routing.websocket_urlpatterns` ne contient qu'une route terminale
  de refus (code 4404). Une origine autorisée ne suffit donc pas à ouvrir une
  connexion et un chemin absent ne provoque pas d'erreur serveur.
- Le préfixe Redis par défaut est `ecommerce`, afin de séparer les clés de ce
  projet dans une instance partagée.

## Développement local avec Docker

Vérifier d'abord Docker, les conteneurs Redis et le port :

```bash
docker --version
docker info
docker ps -a --format '{{.ID}} {{.Names}} {{.Image}} {{.Status}} {{.Ports}}' | rg -i redis
ss -ltnp | rg ':6379\b'
```

Le poste de développement actuel utilise le conteneur dédié suivant. Il ne
publie Redis que sur le loopback et conserve les données dans un volume nommé :

```bash
docker start ecommerce-redis
docker ps --filter name=^/ecommerce-redis$
docker exec ecommerce-redis redis-cli ping
docker exec ecommerce-redis redis-server --version
```

La commande de création, à n'utiliser que si le conteneur n'existe pas, est :

```bash
docker run -d \
  --name ecommerce-redis \
  --restart unless-stopped \
  -p 127.0.0.1:6379:6379 \
  -v ecommerce-redis-data:/data \
  --health-cmd 'redis-cli ping' \
  --health-interval 10s \
  --health-timeout 5s \
  --health-retries 5 \
  redis:7.4-alpine redis-server --appendonly yes
```

Ne pas recréer le conteneur, le volume ou un réseau si une ressource adaptée
existe déjà. Ne pas publier `6379` sur `0.0.0.0`.

## Installation Python et démarrage ASGI

Depuis la racine du dépôt :

```bash
env/bin/python -m pip install -r requirements/development.txt
cd backend
../env/bin/python manage.py check
../env/bin/daphne -b 127.0.0.1 -p 8000 config.asgi:application
```

`../env/bin/python manage.py runserver` utilise également Daphne en
développement. La commande explicite reste préférable pour reproduire le mode
ASGI de production.

Variables locales :

```dotenv
REDIS_URL=redis://127.0.0.1:6379/0
REDIS_CHANNEL_PREFIX=ecommerce
WEBSOCKET_ALLOWED_ORIGINS=http://localhost:3000
```

`WEBSOCKET_ALLOWED_ORIGINS` accepte une liste séparée par des virgules. Il faut
déclarer les origines exactes, schéma compris; un joker large n'est pas adapté
aux connexions authentifiées.

## Vérifications

```bash
docker exec ecommerce-redis redis-cli ping
cd /home/mubaraka/Documents/Entreprise/ecommerce/backend
../env/bin/python manage.py check
RUN_REDIS_INTEGRATION_TESTS=1 ../env/bin/python -m pytest \
  config/tests/test_realtime_infrastructure.py -q
../env/bin/python -m pytest tests/test_health.py -q
```

Le test d'intégration envoie puis reçoit un message par la vraie couche
`RedisChannelLayer`. Sans `RUN_REDIS_INTEGRATION_TESTS=1`, ce seul test est
ignoré afin que les tests unitaires ne dépendent pas d'un service externe.

Diagnostic courant :

- `Connection refused` : vérifier le conteneur, sa santé et `REDIS_URL`;
- délai d'attente : vérifier le port publié, le pare-feu local et la résolution
  du nom Redis depuis le processus Django;
- `403` ou fermeture au handshake : vérifier l'origine exacte; ne pas élargir
  la liste pour masquer l'erreur;
- perte des groupes entre processus : vérifier que tous les processus utilisent
  la même instance, base et préfixe Redis;
- erreur TLS : utiliser `rediss://` avec les paramètres imposés par le
  fournisseur, sans désactiver la validation de certificat.

## Authentification WebSocket cible

Le cookie `ecommerce_session` est chiffré, `HttpOnly` et lisible uniquement par
le BFF Next.js. Django reçoit aujourd'hui un JWT E-commerce dans les appels
serveur-à-serveur. `AuthMiddlewareStack`, qui repose sur une session Django
classique, ne restituerait donc pas l'identité Carri Account réelle.

La future implémentation doit suivre ce flux :

1. Le navigateur demande un ticket à une route BFF même origine, protégée par
   le contrôle CSRF existant.
2. Le BFF lit et rafraîchit sa session, puis appelle un futur endpoint Django
   réservé au BFF avec le JWT utilisateur et la signature HMAC applicative.
3. Django vérifie l'identité, l'entreprise active, l'appartenance et la
   permission `MESSAGING_VIEW` au moyen de `require_messaging_permission`.
4. Django émet un secret opaque aléatoire, à usage unique, conservé sous forme
   hachée, avec une durée de vie courte (30 à 60 secondes), une audience
   WebSocket, l'identité et l'entreprise attendues.
5. Le navigateur offre deux sous-protocoles pendant le handshake : le protocole
   fixe `ecommerce.messaging.v1` et une valeur `ticket.<opaque>`. Le serveur
   valide la seconde mais sélectionne et renvoie uniquement le protocole fixe;
   le ticket n'est donc jamais répercuté dans la réponse. Les journaux du proxy
   et de Daphne doivent expurger l'en-tête de requête `Sec-WebSocket-Protocol`.
6. Un middleware ASGI valide l'origine, consomme atomiquement le ticket, charge
   l'identité dans le `scope` puis seulement laisse atteindre le consumer.
7. Le consumer revérifie l'appartenance active et la permission adaptée
   (`MESSAGING_VIEW`, `MESSAGING_REPLY`, `MESSAGING_ASSIGN` ou
   `MESSAGING_MANAGE`) pour chaque action sensible et chaque entreprise.

Le ticket ne doit pas figurer dans l'URL : les query strings sont couramment
journalisées. Le secret HMAC du BFF ne doit jamais atteindre le navigateur. La
connexion doit être fermée à l'expiration/révocation de session ou après une
durée maximale définie; les changements de permission doivent aussi provoquer
une nouvelle vérification avant toute écriture.

Cette architecture est documentée mais volontairement non implémentée dans ce
lot. Tant que le middleware et l'émission du ticket n'existent pas, seule la
route terminale de refus reste publiée.

## Préparation de la production

Variables obligatoires :

```dotenv
REDIS_URL=rediss://user:password@redis.internal.example:6380/0
REDIS_CHANNEL_PREFIX=ecommerce-production
WEBSOCKET_ALLOWED_ORIGINS=https://commerce.example.com
```

Utiliser un Redis privé ou managé : isolation réseau, authentification,
chiffrement TLS quand disponible, sauvegardes adaptées et métriques de mémoire,
connexions, latence et évictions. Les identifiants restent dans le gestionnaire
de secrets du déploiement. Tous les processus ASGI doivent partager la même
couche Redis; `InMemoryChannelLayer` est interdit en production.

Conserver WSGI tant que d'autres services en dépendent. Pour le temps réel,
superviser Daphne avec systemd, Supervisor ou l'orchestrateur existant. Exemple
de commande de processus, à adapter sans modifier le VPS dans ce lot :

```bash
/srv/ecommerce/env/bin/daphne \
  -b 127.0.0.1 \
  -p 8001 \
  config.asgi:application
```

Exemple Nginx indicatif :

```nginx
location /ws/ {
    proxy_pass http://127.0.0.1:8001;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header Origin $http_origin;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 75s;
}
```

Le proxy doit utiliser HTTPS/WSS publiquement, limiter les handshakes, conserver
des délais d'inactivité bornés et ne jamais journaliser les tickets. Pour
plusieurs processus, déclarer plusieurs instances Daphne dans un upstream ou
utiliser l'orchestrateur existant; Redis assure alors les groupes interprocessus.

Après déploiement : vérifier la santé Redis, `manage.py check
--deploy --settings=config.settings.production`, l'endpoint HTTP de santé via
ASGI, un handshake refusé depuis une origine non autorisée, puis un échange
authentifié avec un ticket de test à usage unique lorsque ce mécanisme sera
implémenté.
