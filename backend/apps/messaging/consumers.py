"""Consumer Channels de la messagerie, authentifié par ticket éphémère."""
from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from .models import Conversation, Message
from .serializers import MessageSerializer
from .services import confirm_delivery, confirm_read, consume_websocket_ticket, send_message


class MessagingConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        protocols = self.scope.get("subprotocols", [])
        token = protocols[1] if len(protocols) >= 2 and protocols[0] == "carri-messaging-v1" else ""
        try:
            self.conversation, self.identity = await self._authenticate(token)
        except Exception:
            await self.close(code=4403)
            return
        self.group_name = f"messaging.conversation.{self.conversation.reference}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept("carri-messaging-v1")

    async def disconnect(self, code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        try:
            event_type = content.get("type")
            if event_type == "message.send":
                message = await self._send_message(content)
                await self.channel_layer.group_send(self.group_name, {"type": "message.created", "message": message})
            elif event_type in {"message.received", "message.read"}:
                message = await self._confirm(event_type, content.get("message"))
                await self.channel_layer.group_send(self.group_name, {"type": event_type.replace(".", "_"), "message": message})
            else:
                await self.send_json({"event": "error", "code": "unsupported_event", "detail": "Événement WebSocket inconnu."})
        except Exception:
            await self.send_json({"event": "error", "code": "message_rejected", "detail": "Le message n’a pas pu être traité."})

    async def message_created(self, event):
        await self.send_json({"event": "message.created", "message": event["message"]})

    async def message_received(self, event):
        await self.send_json({"event": "message.received", "message": event["message"]})

    async def message_read(self, event):
        await self.send_json({"event": "message.read", "message": event["message"]})

    @sync_to_async
    def _authenticate(self, token):
        conversation = Conversation.objects.get(reference=self.scope["url_route"]["kwargs"]["conversation_reference"])
        identity = consume_websocket_ticket(raw_token=token, conversation=conversation)
        return conversation, identity

    @sync_to_async
    def _send_message(self, content):
        message = send_message(identity=self.identity, conversation=self.conversation, content=content.get("content", ""), reply_reference=content.get("reply_to", ""), cart_reference=content.get("cart", ""))
        return MessageSerializer(message).data

    @sync_to_async
    def _confirm(self, event_type, reference):
        message = Message.objects.get(reference=reference, conversation=self.conversation)
        result = confirm_delivery(identity=self.identity, message=message) if event_type == "message.received" else confirm_read(identity=self.identity, message=message)
        return MessageSerializer(result).data
