"""Routage WebSocket racine, volontairement fermé jusqu'au module métier."""

from django.urls import URLPattern, re_path


async def reject_unconfigured_websocket(scope, receive, send):
    """Ferme proprement tout chemin tant qu'aucun consumer sûr n'est publié."""
    message = await receive()
    if message["type"] == "websocket.connect":
        await send({"type": "websocket.close", "code": 4404})


# Les futurs consumers authentifiés devront précéder cette route terminale.
websocket_urlpatterns: list[URLPattern] = [
    re_path(r"^", reject_unconfigured_websocket),
]
