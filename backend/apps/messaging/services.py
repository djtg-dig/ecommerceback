"""Règles métier réutilisables par REST et les futurs consumers Channels."""

import hashlib
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
from apps.businesses.permissions import has_messaging_permission
from apps.carts.models import Cart
from apps.common.media import validate_image

from .models import Conversation, Message


VIEW = BusinessMemberPermission.Permission.MESSAGING_VIEW
REPLY = BusinessMemberPermission.Permission.MESSAGING_REPLY


class ConversationStateError(Exception):
    """Signale une action incompatible avec l'état de la conversation."""


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
        queryset = queryset.select_for_update()
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
    """Exige d'être l'un des deux participants, puis contrôle le droit du vendeur."""
    if identity.id == conversation.buyer_id:
        if write and conversation.business.status != Business.Status.ACTIVE:
            raise PermissionDenied("Forbidden.")
        return "BUYER"
    if identity.id != conversation.seller_id:
        raise NotFound("Not found.")
    member = seller_membership(conversation)
    if not has_messaging_permission(member, seller_permission, write=write):
        raise PermissionDenied("Forbidden.")
    return "SELLER"


def accessible_conversations(identity):
    """Isole les conversations acheteur et celles où l'identité est le vendeur désigné."""
    authorized_memberships = _members_with_messaging_flags(
        BusinessMember.objects.filter(
            identity=identity,
            status=BusinessMember.Status.ACTIVE,
        )
    ).filter(Q(is_owner=True) | Q(messaging_view_granted=True))
    authorized_businesses = authorized_memberships.values("business_id")
    return (
        Conversation.objects.filter(
            Q(buyer=identity)
            | Q(seller=identity, business_id__in=authorized_businesses)
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


def get_or_create_conversation(*, buyer, business, seller_reference):
    """Crée une seule conversation par triplet, même sous concurrence."""
    if business.status != Business.Status.ACTIVE:
        raise ValidationError({"business": "Cette entreprise n'est pas disponible."})
    try:
        with transaction.atomic():
            member = require_eligible_seller(
                business=business,
                buyer=buyer,
                seller_reference=seller_reference,
                lock=True,
            )
            existing = Conversation.objects.filter(
                business=business,
                buyer=buyer,
                seller=member.identity,
            ).first()
            if existing:
                return existing, False
            conversation = Conversation(
                business=business,
                buyer=buyer,
                seller=member.identity,
            )
            conversation.save()
            return conversation, True
    except IntegrityError:
        existing = Conversation.objects.filter(
            business=business,
            buyer=buyer,
            seller__business_memberships__public_id=seller_reference,
            seller__business_memberships__business=business,
        ).first()
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


def send_message(*, identity, conversation, content="", reply_reference="", cart_reference="", upload=None):
    """Enregistre un message en déduisant toujours le destinataire côté serveur."""
    stored_name = ""
    with transaction.atomic():
        conversation = Conversation.objects.select_for_update().select_related(
            "business", "buyer", "seller"
        ).get(pk=conversation.pk)
        role = require_conversation_access(
            identity,
            conversation,
            seller_permission=REPLY,
            write=True,
        )
        require_active_conversation_seller(conversation, write=True)
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
        recipient = conversation.seller if role == "BUYER" else conversation.buyer
        message = Message(
            conversation=conversation,
            sender=identity,
            recipient=recipient,
            content=normalized_content,
            reply_to=reply,
            cart=cart,
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
        message = Message.objects.select_for_update().select_related(
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
        conversation = Conversation.objects.select_for_update().select_related("business").get(pk=conversation.pk)
        require_conversation_access(identity, conversation, seller_permission=REPLY, write=True)
        if conversation.status == Conversation.Status.ARCHIVED:
            raise ConversationStateError("Une conversation archivée ne peut pas être fermée.")
        if conversation.status != Conversation.Status.CLOSED:
            conversation.status = Conversation.Status.CLOSED
            conversation.save(update_fields=("status", "updated_at"))
        return conversation


def reopen_conversation(*, identity, conversation):
    with transaction.atomic():
        conversation = Conversation.objects.select_for_update().select_related("business").get(pk=conversation.pk)
        require_conversation_access(identity, conversation, seller_permission=REPLY, write=True)
        if conversation.status == Conversation.Status.ARCHIVED:
            raise ConversationStateError("Une conversation archivée ne peut pas être rouverte.")
        if conversation.status != Conversation.Status.OPEN:
            conversation.status = Conversation.Status.OPEN
            conversation.save(update_fields=("status", "updated_at"))
        return conversation
