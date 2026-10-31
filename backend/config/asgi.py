"""
ASGI config for config project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import OriginValidator
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

# Django doit initialiser son registre avant tout futur import de consumer
# susceptible d'accéder aux modèles.
django_asgi_application = get_asgi_application()

from django.conf import settings  # noqa: E402

from config.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_application,
        # Aucun consumer fonctionnel n'est publié avant la mise en place de
        # l'authentification WebSocket par ticket éphémère; la route terminale
        # ferme explicitement toute tentative restante.
        "websocket": OriginValidator(
            URLRouter(websocket_urlpatterns),
            settings.WEBSOCKET_ALLOWED_ORIGINS,
        ),
    }
)
