"""Local development settings."""

from .base import *  # noqa: F403

DEBUG = True
SECRET_KEY = SECRET_KEY or "django-insecure-development-only-not-for-production"  # noqa: F405
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1", "testserver"])  # noqa: F405
REDIS_URL = REDIS_URL or "redis://127.0.0.1:6379/0"  # noqa: F405
CHANNEL_LAYERS = redis_channel_layer(REDIS_URL)  # noqa: F405
WEBSOCKET_ALLOWED_ORIGINS = WEBSOCKET_ALLOWED_ORIGINS or [  # noqa: F405
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

# Le serveur de développement local réutilise les connexions PostgreSQL afin
# d'éviter un handshake par requête. La production conserve une valeur
# explicitement pilotée par son déploiement et son pool éventuel.
DATABASES["default"].update({  # noqa: F405
    "CONN_MAX_AGE": int(os.getenv("ECOMMERCE_DEV_DB_CONN_MAX_AGE", "60")),
    "CONN_HEALTH_CHECKS": True,
})
