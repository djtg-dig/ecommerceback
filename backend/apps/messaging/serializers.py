"""Contrats REST minimaux de la messagerie privée."""

from rest_framework import serializers

from apps.businesses.models import BusinessMember

from .models import Conversation, Message


def seller_projection(member):
    return {
        "reference": member.public_id,
        "display_name": member.title.strip() or "Vendeur",
        "avatar": None,
    }


def conversation_seller_member(conversation):
    return BusinessMember.objects.filter(
        business_id=conversation.business_id,
        identity_id=conversation.seller_id,
    ).first()


def conversation_seller_map(conversations):
    """Charge en une requête les adhésions vendeur nécessaires à une page."""
    conversations = list(conversations)
    members = BusinessMember.objects.filter(
        business_id__in={item.business_id for item in conversations},
        identity_id__in={item.seller_id for item in conversations},
    )
    return {
        (member.business_id, member.identity_id): member
        for member in members
    }


class EligibleSellerSerializer(serializers.Serializer):
    reference = serializers.CharField()
    display_name = serializers.CharField()
    avatar = serializers.CharField(allow_null=True)


class ConversationCreateSerializer(serializers.Serializer):
    business = serializers.CharField(max_length=12)
    seller = serializers.CharField(max_length=12)


class ConversationSerializer(serializers.ModelSerializer):
    business = serializers.CharField(source="business.public_id", read_only=True)
    business_name = serializers.CharField(source="business.name", read_only=True)
    seller = serializers.SerializerMethodField()
    participant_role = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = (
            "reference",
            "business",
            "business_name",
            "seller",
            "participant_role",
            "status",
            "created_at",
            "updated_at",
            "last_message_at",
        )
        read_only_fields = fields

    def get_seller(self, conversation):
        member_map = self.context.get("seller_members")
        member = (
            member_map.get((conversation.business_id, conversation.seller_id))
            if member_map is not None
            else conversation_seller_member(conversation)
        )
        return seller_projection(member) if member else None

    def get_participant_role(self, conversation):
        request = self.context.get("request")
        return "BUYER" if request and request.user.id == conversation.buyer_id else "SELLER"


class MessageWriteSerializer(serializers.Serializer):
    content = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False)
    reply_to = serializers.CharField(required=False, allow_blank=False, max_length=12)
    cart = serializers.CharField(required=False, allow_blank=False, max_length=12)
    file = serializers.FileField(required=False, allow_empty_file=False)


class MessageSerializer(serializers.ModelSerializer):
    sender_role = serializers.SerializerMethodField()
    recipient_role = serializers.SerializerMethodField()
    reply_to = serializers.SerializerMethodField()
    cart = serializers.SerializerMethodField()
    attachment = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = (
            "reference",
            "sender_role",
            "recipient_role",
            "content",
            "sent_at",
            "received_at",
            "read_at",
            "reply_to",
            "cart",
            "attachment",
        )
        read_only_fields = fields

    @staticmethod
    def _role(message, identity_id):
        return "BUYER" if identity_id == message.conversation.buyer_id else "SELLER"

    def get_sender_role(self, message):
        return self._role(message, message.sender_id)

    def get_recipient_role(self, message):
        return self._role(message, message.recipient_id)

    def get_reply_to(self, message):
        if not message.reply_to:
            return None
        return {
            "reference": message.reply_to.reference,
            "sender_role": self._role(message.reply_to, message.reply_to.sender_id),
            "content_preview": message.reply_to.content[:160],
            "has_attachment": bool(message.reply_to.file),
        }

    def get_cart(self, message):
        if not message.cart:
            return None
        return {
            "reference": message.cart.reference,
            "name": message.cart.name,
            "status": message.cart.status,
        }

    def get_attachment(self, message):
        if not message.file:
            return None
        return {
            "name": message.file_name,
            "content_type": message.file_content_type,
            "size": message.file_size,
            "download_path": (
                f"/api/v1/messaging/conversations/{message.conversation.reference}/"
                f"messages/{message.reference}/attachment/"
            ),
        }
