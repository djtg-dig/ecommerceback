"""Contrats REST minimaux de la messagerie privée."""

from rest_framework import serializers

from apps.businesses.models import BusinessMember

from .models import BusinessMessagingSettings, Conversation, Inquiry, Message


def seller_projection(member):
    first_name = member.identity.first_name.strip()
    return {
        "reference": member.public_id,
        "first_name": first_name or "Vendeur",
        "display_name": first_name or "Vendeur",
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
    first_name = serializers.CharField()
    display_name = serializers.CharField()
    avatar = serializers.CharField(allow_null=True)


class ConversationCreateSerializer(serializers.Serializer):
    business = serializers.CharField(max_length=12)
    # Legacy input remains accepted only when it identifies today's agent.
    seller = serializers.CharField(max_length=12, required=False)


class ConversationSerializer(serializers.ModelSerializer):
    business = serializers.CharField(source="business.public_id", read_only=True)
    business_name = serializers.CharField(source="business.name", read_only=True)
    agent = serializers.SerializerMethodField()
    participant_role = serializers.SerializerMethodField()
    can_reply = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = (
            "reference",
            "business",
            "business_name",
            "agent",
            "participant_role",
            "can_reply",
            "unread_count",
            "kind",
            "status",
            "created_at",
            "updated_at",
            "last_message_at",
        )
        read_only_fields = fields

    def get_agent(self, conversation):
        from .services import effective_agent
        try:
            return seller_projection(effective_agent(business=conversation.business))
        except Exception:
            return None

    def get_participant_role(self, conversation):
        request = self.context.get("request")
        return "BUYER" if request and request.user.id == conversation.buyer_id else "SELLER"

    def get_can_reply(self, conversation):
        request = self.context.get("request")
        if not request:
            return False
        if request.user.id == conversation.buyer_id:
            return conversation.status == Conversation.Status.OPEN
        from .services import effective_agent
        try:
            return effective_agent(business=conversation.business).identity_id == request.user.id and conversation.status == Conversation.Status.OPEN
        except Exception:
            return False

    def get_unread_count(self, conversation):
        request = self.context.get("request")
        return conversation.messages.filter(recipient=request.user, read_at__isnull=True).count() if request else 0


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


class InquiryCreateSerializer(serializers.Serializer):
    business = serializers.CharField(max_length=12)
    product = serializers.CharField(max_length=12, required=False)
    quantity = serializers.DecimalField(max_digits=14, decimal_places=3, required=False, allow_null=True)
    description = serializers.CharField(max_length=4000, required=False, allow_blank=True, trim_whitespace=False)


class InquirySerializer(serializers.ModelSerializer):
    business = serializers.CharField(source="business.public_id", read_only=True)
    conversation = serializers.CharField(source="conversation.reference", read_only=True)
    class Meta:
        model = Inquiry
        fields = ("reference", "business", "product_reference", "product_name", "quantity", "description", "status", "conversation", "created_at", "updated_at")
        read_only_fields = fields


class InquiryStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Inquiry.Status.choices)


class MessagingSettingsSerializer(serializers.ModelSerializer):
    designated_agent = serializers.SerializerMethodField()
    effective_agent = serializers.SerializerMethodField()
    class Meta:
        model = BusinessMessagingSettings
        fields = ("is_enabled", "designated_agent", "effective_agent", "updated_at")
        read_only_fields = ("designated_agent", "effective_agent", "updated_at")
    def get_designated_agent(self, settings_row):
        return settings_row.designated_agent.public_id if settings_row.designated_agent_id else None
    def get_effective_agent(self, settings_row):
        agent = settings_row.effective_agent()
        return seller_projection(agent) if agent else None
