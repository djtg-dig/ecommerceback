"""Règles métier réutilisables par REST et les futurs consumers Channels."""

import hashlib
import secrets
from datetime import timedelta
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.db import IntegrityError, transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone
from django.utils.text import get_valid_filename
from rest_framework.exceptions import NotFound, PermissionDenied

from apps.businesses.models import Business, BusinessMember, BusinessMemberPermission
from apps.businesses.permissions import has_messaging_permission, membership_for
from apps.carts.models import Cart
from apps.common.media import validate_image

from .models import BusinessMessagingSettings, Conversation, Inquiry, Message, WebSocketTicket


VIEW = BusinessMemberPermission.Permission.MESSAGING_VIEW
REPLY = BusinessMemberPermission.Permission.MESSAGING_REPLY


class ConversationStateError(Exception):
    """Signale une action incompatible avec l'état de la conversation."""


class BusinessMemberCannotContactSellerError(Exception):
    """Une adhésion active interdit le rôle d'acheteur dans sa boutique."""


def require_buyer_can_contact(*, buyer, business):
    """Réutilise la définition d'adhésion active du module paniers."""
    if BusinessMember.objects.filter(
        identity=buyer,
        business=business,
        status=BusinessMember.Status.ACTIVE,
    ).exists():
        raise BusinessMemberCannotContactSellerError()


def messaging_settings(*, business, lock=False):
    settings_row, _ = BusinessMessagingSettings.objects.get_or_create(business=business)
    queryset = BusinessMessagingSettings.objects.select_related(
        "business", "designated_agent__identity", "designated_agent__business"
    ).filter(pk=settings_row.pk)
    # ``designated_agent`` is nullable, so PostgreSQL turns that
    # ``select_related`` into an outer join. Lock only the settings row and
    # never the nullable joined side.
    return queryset.select_for_update(of=("self",)).get() if lock else queryset.get()


def effective_agent(*, business, lock=False):
    settings_row = messaging_settings(business=business, lock=lock)
    if not settings_row.is_enabled:
        raise ValidationError({"business": "La messagerie de cette entreprise est désactivée."})
    agent = settings_row.effective_agent()
    if agent is None:
        raise ValidationError({"business": "Cette entreprise n'a pas d'agent de messagerie actif."})
    return agent


def set_designated_agent(*, actor, business, member_reference=None):
    """Lock the Business scope so replacements cannot create two agents."""
    with transaction.atomic():
        owner = BusinessMember.objects.select_for_update(of=("self",)).filter(business=business, identity=actor, is_owner=True, status=BusinessMember.Status.ACTIVE).first()
        if owner is None:
            raise PermissionDenied("Seul le propriétaire peut désigner l'agent de messagerie.")
        settings_row = messaging_settings(business=business, lock=True)
        settings_row.designated_agent = None
        if member_reference:
            member = BusinessMember.objects.select_for_update(of=("self",)).select_related("identity", "business").filter(business=business, public_id=member_reference).first()
            if member is None:
                raise ValidationError({"designated_agent": "Membre introuvable."})
            settings_row.designated_agent = member
        settings_row.full_clean()
        settings_row.save(update_fields=("designated_agent", "updated_at"))
        return settings_row


def issue_websocket_ticket(*, identity, conversation):
    if identity.id == conversation.buyer_id:
        require_buyer_can_contact(buyer=identity, business=conversation.business)
    require_conversation_access(identity, conversation)
    raw_token = secrets.token_urlsafe(32)
    expires_at = timezone.now() + timedelta(seconds=45)
    WebSocketTicket.objects.filter(expires_at__lt=timezone.now()).delete()
    WebSocketTicket.objects.create(
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        conversation=conversation,
        identity=identity,
        expires_at=expires_at,
    )
    return raw_token, expires_at


def consume_websocket_ticket(*, raw_token, conversation):
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    with transaction.atomic():
        ticket = WebSocketTicket.objects.select_for_update(of=("self",)).select_related("identity").filter(
            token_hash=token_hash, conversation=conversation, consumed_at__isnull=True,
            expires_at__gt=timezone.now(),
        ).first()
        if ticket is None:
            raise PermissionDenied("Ticket WebSocket invalide ou expiré.")
        ticket.consumed_at = timezone.now()
        ticket.save(update_fields=("consumed_at",))
        if ticket.identity_id == conversation.buyer_id:
            require_buyer_can_contact(buyer=ticket.identity, business=conversation.business)
        require_conversation_access(ticket.identity, conversation)
        return ticket.identity


@dataclass(frozen=True)
class AttachmentMetadata:
    name: str
    content_type: str
    size: int
    sha256: str
    extension: str


def _members_with_messaging_flags(queryset):
    permissions = BusinessMemberPermission.objects.filter(member_id=OuterRef("pk"))
    return queryset.annotate(
        messaging_view_granted=Exists(permissions.filter(permission=VIEW)),
        messaging_reply_granted=Exists(permissions.filter(permission=REPLY)),
    )


def eligible_sellers(*, business, buyer):
    """Retourne les membres actifs cumulant vue et réponse, sans statut de présence."""
    if business.status != Business.Status.ACTIVE:
        return []
    queryset = _members_with_messaging_flags(
        BusinessMember.objects.filter(
            business=business,
            status=BusinessMember.Status.ACTIVE,
        )
        .exclude(identity=buyer)
        .select_related("identity", "business")
    ).filter(
        Q(is_owner=True)
        | Q(messaging_view_granted=True, messaging_reply_granted=True)
    )
    return [member for member in queryset if member.identity.is_active]


def require_eligible_seller(*, business, buyer, seller_reference, lock=False):
    queryset = BusinessMember.objects.select_related("identity", "business").filter(
        public_id=seller_reference,
        business=business,
        status=BusinessMember.Status.ACTIVE,
    )
    if lock:
        queryset = queryset.select_for_update(of=("self",))
    member = queryset.first()
    if (
        member is None
        or member.identity_id == buyer.id
        or not member.identity.is_active
        or not has_messaging_permission(member, VIEW)
        or not has_messaging_permission(member, REPLY)
    ):
        raise ValidationError({"seller": "Ce vendeur n'est pas disponible pour la messagerie."})
    return member


def seller_membership(conversation, *, include_inactive=False):
    queryset = BusinessMember.objects.select_related("business", "identity").filter(
        business=conversation.business,
        identity=conversation.seller,
    )
    if not include_inactive:
        queryset = queryset.filter(status=BusinessMember.Status.ACTIVE)
    return queryset.first()


def require_active_conversation_seller(conversation, *, write=False):
    """Exige que le vendeur désigné conserve les deux droits opérationnels."""
    member = seller_membership(conversation)
    if (
        not has_messaging_permission(member, VIEW, write=write)
        or not has_messaging_permission(member, REPLY, write=write)
    ):
        raise PermissionDenied("Le vendeur désigné n'est plus disponible.")
    return member


def require_conversation_access(identity, conversation, *, seller_permission=VIEW, write=False):
    """Staff may view the shared inbox; only the effective agent may write."""
    if identity.id == conversation.buyer_id:
        if write and conversation.business.status != Business.Status.ACTIVE:
            raise PermissionDenied("Forbidden.")
        return "BUYER"
    member = membership_for(identity, conversation.business, include_suspended=True)
    if member is None:
        raise NotFound("Not found.")
    if not has_messaging_permission(member, seller_permission, write=write):
        raise PermissionDenied("Forbidden.")
    if write and effective_agent(business=conversation.business, lock=True).id != member.id:
        raise PermissionDenied("Seul l'agent de messagerie effectif peut répondre aux acheteurs.")
    return "SELLER"


def accessible_conversations(identity):
    """The inbox is shared with members holding the view permission."""
    authorized_memberships = _members_with_messaging_flags(
        BusinessMember.objects.filter(
            identity=identity,
            status=BusinessMember.Status.ACTIVE,
        )
    ).filter(Q(is_owner=True) | Q(messaging_view_granted=True))
    authorized_businesses = authorized_memberships.values("business_id")
    return (
        Conversation.objects.filter(
            Q(buyer=identity) | Q(business_id__in=authorized_businesses)
        )
        .select_related("business", "buyer", "seller")
        .distinct()
    )


def get_accessible_conversation(*, identity, reference, write=False, seller_permission=VIEW):
    conversation = (
        Conversation.objects.select_related("business", "buyer", "seller")
        .filter(reference=reference)
        .first()
    )
    if conversation is None:
        raise NotFound("Not found.")
    require_conversation_access(
        identity,
        conversation,
        seller_permission=seller_permission,
        write=write,
    )
    return conversation


def get_or_create_conversation(*, buyer, business, seller_reference=None):
    """Open one direct buyer–business conversation, safe under concurrent opens."""
    if business.status != Business.Status.ACTIVE:
        raise ValidationError({"business": "Cette entreprise n'est pas disponible."})
    require_buyer_can_contact(buyer=buyer, business=business)
    try:
        with transaction.atomic():
            existing = Conversation.objects.filter(
                business=business,
                buyer=buyer,
                kind=Conversation.Kind.DIRECT,
            ).first()
            if existing:
                return existing, False
            member = effective_agent(business=business, lock=True)
            if seller_reference and seller_reference != member.public_id:
                raise ValidationError({"seller": "Cet agent n'est plus l'agent effectif de l'entreprise."})
            conversation = Conversation(
                business=business,
                buyer=buyer,
                seller=member.identity,
                kind=Conversation.Kind.DIRECT,
            )
            try:
                conversation.save()
            except ValidationError:
                # Model validation can observe a row committed by a concurrent
                # opener before the INSERT reaches PostgreSQL. Treat that
                # unique-validation race exactly like an IntegrityError.
                existing = Conversation.objects.filter(
                    business=business,
                    buyer=buyer,
                    kind=Conversation.Kind.DIRECT,
                ).first()
                if existing:
                    return existing, False
                raise
            return conversation, True
    except IntegrityError:
        existing = Conversation.objects.filter(business=business, buyer=buyer, kind=Conversation.Kind.DIRECT).first()
        if existing:
            return existing, False
        raise


def _file_size(upload: UploadedFile) -> int:
    size = getattr(upload, "size", None)
    if size is not None:
        return int(size)
    position = upload.tell()
    upload.seek(0, 2)
    size = upload.tell()
    upload.seek(position)
    return size


def _file_sha256(upload: UploadedFile) -> str:
    digest = hashlib.sha256()
    upload.seek(0)
    if hasattr(upload, "chunks"):
        for chunk in upload.chunks():
            digest.update(chunk)
    else:
        while chunk := upload.read(64 * 1024):
            digest.update(chunk)
    upload.seek(0)
    return digest.hexdigest()


def validate_attachment(upload: UploadedFile) -> AttachmentMetadata:
    """Valide les octets du fichier; le MIME déclaré par le client est ignoré."""
    size = _file_size(upload)
    maximum = settings.MESSAGING_ATTACHMENT_MAX_BYTES
    if size <= 0 or size > maximum:
        raise ValidationError({"file": f"La pièce jointe doit peser au plus {maximum // 1024 // 1024} Mo."})

    upload.seek(0)
    header = upload.read(8)
    upload.seek(max(0, size - 2048))
    trailer = upload.read()
    upload.seek(0)

    if header.startswith(b"%PDF-"):
        if b"%%EOF" not in trailer:
            raise ValidationError({"file": "Le fichier PDF est incomplet ou invalide."})
        extension = ".pdf"
        content_type = "application/pdf"
    else:
        metadata = validate_image(upload, kind="product")
        extension = f".{metadata.format}"
        content_type = {
            "jpg": "image/jpeg",
            "png": "image/png",
            "webp": "image/webp",
        }[metadata.format]
        size = metadata.size_bytes

    original_stem = get_valid_filename(Path(upload.name or "attachment").stem)[:180]
    safe_name = f"{original_stem or 'attachment'}{extension}"
    return AttachmentMetadata(
        name=safe_name,
        content_type=content_type,
        size=size,
        sha256=_file_sha256(upload),
        extension=extension,
    )


def _resolve_reply(conversation, reference):
    if not reference:
        return None
    reply = Message.objects.filter(reference=reference).first()
    if reply is None or reply.conversation_id != conversation.id:
        raise ValidationError({"reply_to": "Le message cité est introuvable dans cette conversation."})
    return reply


def _resolve_cart(conversation, reference):
    if not reference:
        return None
    cart = Cart.objects.filter(reference=reference).first()
    if (
        cart is None
        or cart.buyer_id != conversation.buyer_id
        or cart.business_id != conversation.business_id
    ):
        raise ValidationError({"cart": "Ce panier ne peut pas être associé à la conversation."})
    return cart


def create_inquiry(*, buyer, business, product_reference="", quantity=None, description=""):
    if business.status != Business.Status.ACTIVE:
        raise ValidationError({"business": "Cette entreprise n'est pas disponible."})
    require_buyer_can_contact(buyer=buyer, business=business)
    with transaction.atomic():
        agent = effective_agent(business=business, lock=True)
        product = None
        if product_reference:
            from apps.catalog.models import Product
            product = Product.objects.filter(public_id=product_reference, business=business).first()
            if product is None:
                raise ValidationError({"product": "Produit introuvable pour cette entreprise."})
        conversation = Conversation(
            business=business,
            buyer=buyer,
            seller=agent.identity,
            kind=Conversation.Kind.INQUIRY,
        )
        conversation.save()
        inquiry = Inquiry(business=business, buyer=buyer, product=product, product_reference=product.public_id if product else "", product_name=product.name if product else "", quantity=quantity, description=description, conversation=conversation)
        inquiry.save()
        return inquiry


def send_message(*, identity, conversation, content="", reply_reference="", cart_reference="", upload=None):
    """Enregistre un message en déduisant toujours le destinataire côté serveur."""
    stored_name = ""
    with transaction.atomic():
        conversation = Conversation.objects.select_for_update(of=("self",)).select_related(
            "business", "buyer", "seller"
        ).get(pk=conversation.pk)
        role = require_conversation_access(
            identity,
            conversation,
            seller_permission=REPLY,
            write=True,
        )
        agent = effective_agent(business=conversation.business, lock=True)
        if role == "BUYER":
            require_buyer_can_contact(buyer=identity, business=conversation.business)
        if conversation.status != Conversation.Status.OPEN:
            raise ConversationStateError("La conversation n'accepte pas de nouveaux messages.")

        normalized_content = (content or "").strip()
        if len(normalized_content) > settings.MESSAGING_MESSAGE_MAX_LENGTH:
            raise ValidationError({"content": "Le message dépasse la longueur autorisée."})
        attachment = validate_attachment(upload) if upload else None
        if not normalized_content and attachment is None:
            raise ValidationError({"content": "Un texte ou une pièce jointe est requis."})

        reply = _resolve_reply(conversation, reply_reference)
        cart = _resolve_cart(conversation, cart_reference)
        recipient = agent.identity if role == "BUYER" else conversation.buyer
        message = Message(
            conversation=conversation,
            sender=identity,
            recipient=recipient,
            content=normalized_content,
            reply_to=reply,
            cart=cart,
            sender_member=agent if role == "SELLER" else None,
        )
        if attachment:
            upload.name = attachment.name
            message.file = upload
            message.file_name = attachment.name
            message.file_content_type = attachment.content_type
            message.file_size = attachment.size
            message.file_sha256 = attachment.sha256
        try:
            message.save()
            stored_name = message.file.name if message.file else ""
            Conversation.objects.filter(pk=conversation.pk).update(
                last_message_at=message.sent_at,
                updated_at=message.sent_at,
            )
        except Exception:
            stored_name = message.file.name if message.file else stored_name
            if stored_name and message.file.storage.exists(stored_name):
                message.file.storage.delete(stored_name)
            raise
        return message


def confirm_delivery(*, identity, message):
    return _confirm_recipient_event(identity=identity, message=message, field="received_at")


def confirm_read(*, identity, message):
    return _confirm_recipient_event(identity=identity, message=message, field="read_at")


def _confirm_recipient_event(*, identity, message, field):
    with transaction.atomic():
        message = Message.objects.select_for_update(of=("self",)).select_related(
            "conversation__business",
            "conversation__buyer",
            "conversation__seller",
        ).get(pk=message.pk)
        require_conversation_access(identity, message.conversation)
        if message.recipient_id != identity.id:
            raise PermissionDenied("Seul le destinataire peut confirmer cet événement.")
        if getattr(message, field) is None:
            setattr(message, field, max(timezone.now(), message.sent_at))
            message.save(update_fields=(field,))
        return message


def close_conversation(*, identity, conversation):
    with transaction.atomic():
        conversation = Conversation.objects.select_for_update(of=("self",)).select_related("business").get(pk=conversation.pk)
        require_conversation_access(identity, conversation, seller_permission=REPLY, write=True)
        if conversation.status == Conversation.Status.ARCHIVED:
            raise ConversationStateError("Une conversation archivée ne peut pas être fermée.")
        if conversation.status != Conversation.Status.CLOSED:
            conversation.status = Conversation.Status.CLOSED
            conversation.save(update_fields=("status", "updated_at"))
        return conversation


def reopen_conversation(*, identity, conversation):
    with transaction.atomic():
        conversation = Conversation.objects.select_for_update(of=("self",)).select_related("business").get(pk=conversation.pk)
        require_conversation_access(identity, conversation, seller_permission=REPLY, write=True)
        if conversation.status == Conversation.Status.ARCHIVED:
            raise ConversationStateError("Une conversation archivée ne peut pas être rouverte.")
        if conversation.status != Conversation.Status.OPEN:
            conversation.status = Conversation.Status.OPEN
            conversation.save(update_fields=("status", "updated_at"))
        return conversation
