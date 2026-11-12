"""Routage WebSocket privé de la messagerie."""
from django.urls import re_path
from apps.messaging.consumers import MessagingConsumer

websocket_urlpatterns = [
    re_path(r"^ws/messaging/conversations/(?P<conversation_reference>[A-Za-z0-9_-]{1,64})/$", MessagingConsumer.as_asgi()),
]
