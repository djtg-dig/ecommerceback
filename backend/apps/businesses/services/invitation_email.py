"""Delivery adapter for Business member invitation emails."""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import formats, timezone
from django.utils.translation import override

from ..models import BusinessMemberInvitation
from .invitations import hash_invitation_token


class InvitationDeliveryConfigurationError(Exception):
    """Raised before persistence when no safe invitation URL is configured."""


class InvitationDeliveryError(Exception):
    """Raised when the configured email backend cannot deliver an invitation."""


def invitation_base_url():
    """Return the configured absolute invitation URL or reject the delivery."""
    value = settings.BUSINESS_MEMBER_INVITATION_URL.strip()
    parts = urlsplit(value)
    if (
        not value
        or parts.scheme not in {"http", "https"}
        or not parts.netloc
    ):
        raise InvitationDeliveryConfigurationError
    if not settings.DEFAULT_FROM_EMAIL.strip():
        raise InvitationDeliveryConfigurationError
    return value


def build_invitation_url(invitation, token):
    """Append the invitation public id and token without corrupting params."""
    parts = urlsplit(invitation_base_url())
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["invitation"] = invitation.public_id
    query["token"] = token
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(query),
            parts.fragment,
        )
    )


def _format_expiration(expires_at):
    with override("fr"):
        return formats.date_format(
            timezone.localtime(expires_at),
            "j F Y à H:i",
        )


def send_invitation_email(invitation_id, token):
    """Deliver one invitation and mark it sent only after backend success."""
    invitation = (
        BusinessMemberInvitation.objects.select_related("business")
        .filter(
            pk=invitation_id,
            status=BusinessMemberInvitation.Status.PENDING,
            token_hash=hash_invitation_token(token),
        )
        .first()
    )
    if invitation is None:
        return

    context = {
        "business_name": invitation.business.name,
        "invited_email": invitation.email,
        "title": invitation.title,
        "expires_at": _format_expiration(invitation.expires_at),
        "invitation_url": build_invitation_url(invitation, token),
    }
    subject = (
        f"Invitation à rejoindre {invitation.business.name} sur E-commerce"
    )
    text_body = render_to_string(
        "businesses/emails/member_invitation.txt",
        context,
    )
    html_body = render_to_string(
        "businesses/emails/member_invitation.html",
        context,
    )
    email = EmailMultiAlternatives(
        subject,
        text_body,
        settings.DEFAULT_FROM_EMAIL,
        [invitation.email],
    )
    email.attach_alternative(html_body, "text/html")

    try:
        delivered = email.send(fail_silently=False)
    except Exception as exc:
        raise InvitationDeliveryError from exc
    if delivered != 1:
        raise InvitationDeliveryError

    BusinessMemberInvitation.objects.filter(
        pk=invitation.pk,
        status=BusinessMemberInvitation.Status.PENDING,
        token_hash=hash_invitation_token(token),
    ).update(last_sent_at=timezone.now(), updated_at=timezone.now())

