import os
from urllib.parse import urlparse

import pytest
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from channels.routing import ProtocolTypeRouter
from channels.security.websocket import OriginValidator
from channels.testing import WebsocketCommunicator
from django.conf import settings

from config.asgi import application
from config.routing import websocket_urlpatterns


def test_asgi_routes_http_and_websocket_protocols():
    assert isinstance(application, ProtocolTypeRouter)
    assert set(application.application_mapping) == {"http", "websocket"}
    assert isinstance(application.application_mapping["websocket"], OriginValidator)


def test_no_functional_websocket_endpoint_is_published_before_authentication_exists():
    communicator = WebsocketCommunicator(
        application,
        "/ws/",
        headers=[
            (b"host", b"localhost"),
            (b"origin", b"http://localhost:3000"),
        ],
    )

    assert len(websocket_urlpatterns) == 1
    assert async_to_sync(communicator.connect)() == (False, 4404)


def test_disallowed_websocket_origin_is_rejected():
    validator = application.application_mapping["websocket"]

    assert validator.valid_origin(None) is False
    assert validator.valid_origin(urlparse("https://untrusted.example")) is False


def test_development_channel_layer_uses_redis_url():
    layer = settings.CHANNEL_LAYERS["default"]

    assert layer["BACKEND"] == "channels_redis.core.RedisChannelLayer"
    assert layer["CONFIG"]["hosts"] == [settings.REDIS_URL]
    assert settings.REDIS_URL.startswith(("redis://", "rediss://"))


@pytest.mark.skipif(
    os.getenv("RUN_REDIS_INTEGRATION_TESTS") != "1",
    reason="Le test Redis explicite requiert RUN_REDIS_INTEGRATION_TESTS=1.",
)
def test_channels_can_exchange_a_message_through_redis():
    async def exchange_message():
        layer = get_channel_layer()
        channel = await layer.new_channel("infrastructure.")
        message = {"type": "infrastructure.test", "value": "ok"}

        await layer.send(channel, message)
        received = await layer.receive(channel)
        await layer.close_pools()
        return received

    assert async_to_sync(exchange_message)() == {
        "type": "infrastructure.test",
        "value": "ok",
    }
