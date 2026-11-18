"""Modèles persistants de la messagerie commerciale acheteur–entreprise."""

import uuid
from pathlib import Path

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from .identifiers import generate_conversation_reference, generate_message_reference
from .storage import PrivateMessagingStorage


def private_attachment_upload_to(message, filename):
    """Construit un chemin opaque isolé par conversation."""
    extension = Path(filename).suffix.lower()
    return f"messaging/{message.conversation.reference}/{uuid.uuid4().hex}{extension}"


class Conversation(models.Model):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        CLOSED = "CLOSED", "Closed"
        ARCHIVED = "ARCHIVED", "Archived"

    class Kind(models.TextChoices):
        DIRECT = "DIRECT", "Direct discussion"
        INQUIRY = "INQUIRY", "Commercial inquiry"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reference = models.CharField(max_length=12, unique=True, editable=False, db_index=True)
    business = models.ForeignKey(
        "businesses.Business",
        on_delete=models.PROTECT,
        related_name="messaging_conversations",
    )
    buyer = models.ForeignKey(
        "accounts.CarriIdentity",
        on_delete=models.PROTECT,
        related_name="buyer_conversations",
    )
    seller = models.ForeignKey(
        "accounts.CarriIdentity",
        on_delete=models.PROTECT,
        related_name="seller_conversations",
    )
    # Historical recipient retained for existing conversations. New sends are
    # routed through the effective business agent at the time of the send.
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.DIRECT, db_index=True)
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.OPEN,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_message_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ("-last_message_at", "-created_at")
        constraints = [
            models.UniqueConstraint(
                fields=("business", "buyer", "seller", "kind"),
                name="messaging_conversation_participants_unique",
            ),
            models.CheckConstraint(
                condition=~Q(buyer=F("seller")),
                name="messaging_conversation_distinct_participants",
            ),
        ]
        indexes = [
            models.Index(fields=("buyer", "status"), name="msg_conv_buyer_status_idx"),
            models.Index(fields=("seller", "status"), name="msg_conv_seller_status_idx"),
            models.Index(fields=("business", "seller"), name="msg_conv_business_seller_idx"),
            models.Index(fields=("business", "kind"), name="msg_conv_business_kind_idx"),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.buyer_id and self.seller_id and self.buyer_id == self.seller_id:
            errors["seller"] = "L'acheteur et le vendeur doivent être différents."
        if self.business_id and self.seller_id:
            from apps.businesses.models import BusinessMember, BusinessMemberPermission
            from apps.businesses.permissions import has_messaging_permission

            member = BusinessMember.objects.filter(
                business_id=self.business_id,
                identity_id=self.seller_id,
            ).select_related("business", "identity").first()
            if member is None:
                errors["seller"] = "Le vendeur doit appartenir à l'entreprise."
            elif self._state.adding:
                can_view = has_messaging_permission(
                    member,
                    BusinessMemberPermission.Permission.MESSAGING_VIEW,
                )
                can_reply = has_messaging_permission(
                    member,
                    BusinessMemberPermission.Permission.MESSAGING_REPLY,
                )
                if not member.identity.is_active or not can_view or not can_reply:
                    errors["seller"] = "Le vendeur doit être actif et autorisé à utiliser la messagerie."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = generate_conversation_reference()
        self.full_clean()
        return super().save(*args, **kwargs)


class BusinessMessagingSettings(models.Model):
    """The designated agent, with the owner as a computed safe fallback."""

    business = models.OneToOneField("businesses.Business", on_delete=models.CASCADE, related_name="messaging_settings")
    designated_agent = models.ForeignKey("businesses.BusinessMember", null=True, blank=True, on_delete=models.PROTECT, related_name="designated_messaging_for")
    is_enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        super().clean()
        if not self.designated_agent_id:
            return
        from apps.businesses.models import BusinessMember, BusinessMemberPermission
        from apps.businesses.permissions import has_messaging_permission

        agent = self.designated_agent
        if agent.business_id != self.business_id:
            raise ValidationError({"designated_agent": "L'agent doit appartenir à cette entreprise."})
        if (agent.status != BusinessMember.Status.ACTIVE or not agent.identity.is_active
                or not has_messaging_permission(agent, BusinessMemberPermission.Permission.MESSAGING_VIEW)
                or not has_messaging_permission(agent, BusinessMemberPermission.Permission.MESSAGING_REPLY)):
            raise ValidationError({"designated_agent": "Le membre désigné ne peut pas répondre aux acheteurs."})

    def effective_agent(self):
        """Never cache this result: suspension and permission revocation are immediate."""
        from apps.businesses.models import BusinessMember, BusinessMemberPermission
        from apps.businesses.permissions import has_messaging_permission

        agent = self.designated_agent
        if agent and agent.status == BusinessMember.Status.ACTIVE and agent.identity.is_active and has_messaging_permission(agent, BusinessMemberPermission.Permission.MESSAGING_VIEW) and has_messaging_permission(agent, BusinessMemberPermission.Permission.MESSAGING_REPLY):
            return agent
        owner = BusinessMember.objects.select_related("identity", "business").filter(
            business=self.business, is_owner=True, status=BusinessMember.Status.ACTIVE
        ).first()
        return owner if owner and owner.identity.is_active else None


class Inquiry(models.Model):
    """Commercial request whose product context remains available after edits."""

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        IN_PROGRESS = "IN_PROGRESS", "In progress"
        CLOSED = "CLOSED", "Closed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reference = models.CharField(max_length=12, unique=True, editable=False, db_index=True)
    business = models.ForeignKey("businesses.Business", on_delete=models.PROTECT, related_name="messaging_inquiries")
    buyer = models.ForeignKey("accounts.CarriIdentity", on_delete=models.PROTECT, related_name="messaging_inquiries")
    product = models.ForeignKey("catalog.Product", null=True, blank=True, on_delete=models.SET_NULL, related_name="messaging_inquiries")
    product_reference = models.CharField(max_length=12, blank=True, default="")
    product_name = models.CharField(max_length=240, blank=True, default="")
    quantity = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    description = models.TextField(blank=True, default="")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN, db_index=True)
    conversation = models.OneToOneField("Conversation", null=True, blank=True, on_delete=models.PROTECT, related_name="inquiry")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=("business", "status"), name="msg_inquiry_biz_status_idx")]

    def clean(self):
        super().clean()
        if self.product_id and self.product.business_id != self.business_id:
            raise ValidationError({"product": "Le produit doit appartenir à l'entreprise destinataire."})
        if self.quantity is not None and self.quantity <= 0:
            raise ValidationError({"quantity": "La quantité doit être positive."})
        if not self.description.strip() and not self.product_id:
            raise ValidationError({"description": "Décrivez votre besoin ou sélectionnez un produit."})

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = generate_conversation_reference()
        self.description = (self.description or "").strip()
        self.full_clean()
        return super().save(*args, **kwargs)


class WebSocketTicket(models.Model):
    """Ticket opaque, court et à usage unique pour un socket privé."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="websocket_tickets")
    identity = models.ForeignKey("accounts.CarriIdentity", on_delete=models.CASCADE)
    expires_at = models.DateTimeField(db_index=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=("conversation", "expires_at"), name="msg_ticket_conv_exp_idx")]


class Message(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reference = models.CharField(max_length=12, unique=True, editable=False, db_index=True)
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.PROTECT,
        related_name="messages",
    )
    sender = models.ForeignKey(
        "accounts.CarriIdentity",
        on_delete=models.PROTECT,
        related_name="messages_sent",
    )
    sender_member = models.ForeignKey("businesses.BusinessMember", null=True, blank=True, on_delete=models.PROTECT, related_name="messaging_messages_sent")
    recipient = models.ForeignKey(
        "accounts.CarriIdentity",
        on_delete=models.PROTECT,
        related_name="messages_received",
    )
    sent_at = models.DateTimeField(auto_now_add=True, db_index=True)
    received_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    reply_to = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="replies",
    )
    cart = models.ForeignKey(
        "carts.Cart",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="messages",
    )
    file = models.FileField(
        storage=PrivateMessagingStorage(),
        upload_to=private_attachment_upload_to,
        max_length=500,
        null=True,
        blank=True,
    )
    file_name = models.CharField(max_length=255, blank=True, default="")
    file_content_type = models.CharField(max_length=100, blank=True, default="")
    file_size = models.PositiveBigIntegerField(null=True, blank=True)
    file_sha256 = models.CharField(max_length=64, blank=True, default="")
    content = models.TextField(blank=True, default="")

    class Meta:
        ordering = ("sent_at", "id")
        constraints = [
            models.CheckConstraint(
                condition=~Q(sender=F("recipient")),
                name="messaging_message_distinct_participants",
            ),
            models.CheckConstraint(
                condition=Q(received_at__isnull=True) | Q(received_at__gte=F("sent_at")),
                name="messaging_message_received_after_sent",
            ),
            models.CheckConstraint(
                condition=Q(read_at__isnull=True) | Q(read_at__gte=F("sent_at")),
                name="messaging_message_read_after_sent",
            ),
            models.CheckConstraint(
                condition=(
                    ~Q(content="")
                    | (Q(file__isnull=False) & ~Q(file=""))
                ),
                name="messaging_message_content_or_file",
            ),
        ]
        indexes = [
            models.Index(fields=("conversation", "sent_at"), name="msg_message_conv_sent_idx"),
            models.Index(fields=("recipient", "read_at"), name="msg_message_recipient_read_idx"),
        ]

    def clean(self):
        super().clean()
        errors = {}
        self.content = (self.content or "").strip()
        if not self.content and not self.file:
            errors["content"] = "Un texte ou une pièce jointe est requis."
        if self.sender_id and self.recipient_id and self.sender_id == self.recipient_id:
            errors["recipient"] = "L'émetteur et le destinataire doivent être différents."
        if self.conversation_id and self.sender_id and self.recipient_id:
            if self.sender_id == self.conversation.buyer_id:
                if self.sender_member_id:
                    errors["sender_member"] = "Un acheteur ne peut pas être un agent de l'entreprise."
                elif self._state.adding:
                    from apps.businesses.models import BusinessMember, BusinessMemberPermission
                    from apps.businesses.permissions import has_messaging_permission

                    recipient_member = BusinessMember.objects.filter(
                        business_id=self.conversation.business_id,
                        identity_id=self.recipient_id,
                        status=BusinessMember.Status.ACTIVE,
                    ).select_related("identity").first()
                    if (
                        recipient_member is None
                        or not recipient_member.identity.is_active
                        or not (
                            recipient_member.is_owner
                            or (
                                has_messaging_permission(recipient_member, BusinessMemberPermission.Permission.MESSAGING_VIEW)
                                and has_messaging_permission(recipient_member, BusinessMemberPermission.Permission.MESSAGING_REPLY)
                            )
                        )
                    ):
                        errors["recipient"] = "Le destinataire doit être l'agent de messagerie de l'entreprise."
            else:
                member = self.sender_member
                legacy_sender = bool(self.pk and self.sender_id == self.conversation.seller_id and member is None)
                if not legacy_sender and (member is None or member.business_id != self.conversation.business_id or member.identity_id != self.sender_id):
                    errors["sender_member"] = "L'expéditeur entreprise doit conserver son adhésion réelle."
                if self.recipient_id != self.conversation.buyer_id:
                    errors["recipient"] = "La réponse entreprise doit être adressée à l'acheteur."
        if self.reply_to_id:
            if self.pk and self.reply_to_id == self.pk:
                errors["reply_to"] = "Un message ne peut pas se citer lui-même."
            elif self.conversation_id and self.reply_to.conversation_id != self.conversation_id:
                errors["reply_to"] = "Le message cité appartient à une autre conversation."
        if self.cart_id and self.conversation_id:
            if self.cart.buyer_id != self.conversation.buyer_id:
                errors["cart"] = "Le panier n'appartient pas à l'acheteur."
            elif self.cart.business_id != self.conversation.business_id:
                errors["cart"] = "Le panier appartient à une autre entreprise."
        if self.received_at and self.sent_at and self.received_at < self.sent_at:
            errors["received_at"] = "La réception ne peut pas précéder l'envoi."
        if self.read_at and self.sent_at and self.read_at < self.sent_at:
            errors["read_at"] = "La lecture ne peut pas précéder l'envoi."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = generate_message_reference()
        self.full_clean()
        return super().save(*args, **kwargs)
