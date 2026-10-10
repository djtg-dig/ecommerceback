"""Transactional services for Business member email invitations.

The invitation flow is adapted from Kisinet's ``PharmacyMemberInvitation``
to the E-commerce ``BusinessMember`` model. The raw invitation secret is
never persisted: only its SHA-256 hash is stored, and the secret is
returned once to the caller so it can be delivered out of band.
"""

import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from ..models import (
    Business,
    BusinessMember,
    BusinessMemberInvitation,
    BusinessMemberPermission,
)


def normalize_email(email):
    """Return the canonical comparison value for an invitation address."""
    return (email or "").strip().lower()


def hash_invitation_token(token):
    """Return the SHA-256 hash stored for an invitation secret."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_invitation_token():
    """Return a cryptographically random invitation secret."""
    return secrets.token_urlsafe(32)


def invitation_expiry():
    """Return the server-side expiration of a new invitation."""
    hours = getattr(
        settings,
        "BUSINESS_MEMBER_INVITATION_EXPIRY_HOURS",
        168,
    )
    return timezone.now() + timedelta(hours=hours)


def _validate_actor(actor_member, business):
    """Enforce the invitation permission from locked server-side data."""
    if not actor_member or actor_member.status != BusinessMember.Status.ACTIVE:
        raise ValidationError("An active member is required.")
    if actor_member.business_id != business.pk:
        raise ValidationError("The invitation must stay inside one Business.")
    if not actor_member.is_owner and not BusinessMemberPermission.objects.filter(
        member=actor_member,
        permission=BusinessMemberPermission.Permission.MANAGE_MEMBERS,
    ).exists():
        raise ValidationError("An authorized member manager is required.")
    if business.status != Business.Status.ACTIVE:
        raise ValidationError("Invitations require an active Business.")


def _expire_stale_pending_invitations(business, normalized_email):
    """Mark expired pending invitations so a fresh one can be created."""
    stale = BusinessMemberInvitation.objects.select_for_update().filter(
        business=business,
        normalized_email=normalized_email,
        status=BusinessMemberInvitation.Status.PENDING,
    )
    for invitation in stale:
        if invitation.is_expired:
            invitation.status = BusinessMemberInvitation.Status.EXPIRED
            invitation.acted_at = timezone.now()
            invitation.save(
                update_fields=("status", "acted_at", "updated_at")
            )


def invite_member(actor_member, business, email, title=""):
    """Create one pending invitation for a Business email address.

    The actor must be an active member with ``MANAGE_MEMBERS`` on an
    active Business. The address is normalized before any comparison.
    An existing active membership (active or suspended) blocks the
    invitation. A pending invitation for the same address is rejected
    unless it already expired, in which case it is expired first. The
    raw token is returned alongside the invitation so the caller can
    deliver it exactly once; only its hash is persisted.
    """
    _validate_actor(actor_member, business)

    normalized_email = normalize_email(email)
    try:
        validate_email(normalized_email)
    except ValidationError as exc:
        raise ValidationError(
            {"email": "Veuillez saisir une adresse e-mail valide."}
        ) from exc

    with transaction.atomic():
        locked_business = Business.objects.select_for_update().get(pk=business.pk)
        locked_actor = BusinessMember.objects.select_for_update().get(
            pk=actor_member.pk,
        )
        _validate_actor(locked_actor, locked_business)

        existing_membership = BusinessMember.objects.filter(
            business=locked_business,
        ).filter(
            Q(identity__verified_email__iexact=normalized_email)
            | Q(identity__carri_subject=normalized_email)
        ).exclude(status=BusinessMember.Status.REMOVED).first()
        if existing_membership is not None:
            raise ValidationError(
                {"email": "This address already has a Business membership."}
            )

        _expire_stale_pending_invitations(locked_business, normalized_email)

        token = generate_invitation_token()
        try:
            invitation = BusinessMemberInvitation.objects.create(
                business=locked_business,
                email=normalized_email,
                title=title,
                token_hash=hash_invitation_token(token),
                expires_at=invitation_expiry(),
                invited_by=locked_actor.identity,
            )
        except IntegrityError as exc:
            raise ValidationError(
                {"email": "A pending invitation already exists for this address."}
            ) from exc

    return invitation, token


def _schedule_delivery(invitation, token):
    """Register delivery after commit; the adapter records successful sends."""
    from .invitation_email import send_invitation_email

    transaction.on_commit(
        lambda: send_invitation_email(invitation.pk, token)
    )


def create_and_send_invitation(actor_member, business, email, title=""):
    """Create an invitation and deliver its one-time secret after commit."""
    from .invitation_email import invitation_base_url

    invitation_base_url()
    with transaction.atomic():
        invitation, token = invite_member(
            actor_member,
            business,
            email,
            title=title,
        )
        _schedule_delivery(invitation, token)
    invitation.refresh_from_db()
    return invitation


def resend_member_invitation(actor_member, invitation):
    """Rotate a pending/expired invitation token and deliver it after commit."""
    from .invitation_email import invitation_base_url

    invitation_base_url()
    with transaction.atomic():
        locked_business = Business.objects.select_for_update().get(
            pk=invitation.business_id,
        )
        locked_actor = BusinessMember.objects.select_for_update().get(
            pk=actor_member.pk,
        )
        locked_invitation = (
            BusinessMemberInvitation.objects.select_for_update()
            .filter(
                pk=invitation.pk,
                business=locked_business,
            )
            .first()
        )
        if locked_invitation is None:
            raise ValidationError("Invitation introuvable.")
        _validate_actor(locked_actor, locked_business)

        effective_status = validate_invitation_state(locked_invitation)
        if effective_status == BusinessMemberInvitation.Status.REVOKED:
            raise ValidationError("Cette invitation a été révoquée.")
        if effective_status not in {
            BusinessMemberInvitation.Status.PENDING,
            BusinessMemberInvitation.Status.EXPIRED,
        }:
            raise ValidationError(
                "Seule une invitation en attente ou expirée peut être renvoyée."
            )

        token = generate_invitation_token()
        locked_invitation.status = BusinessMemberInvitation.Status.PENDING
        locked_invitation.token_hash = hash_invitation_token(token)
        locked_invitation.expires_at = invitation_expiry()
        locked_invitation.resend_count += 1
        locked_invitation.save(
            update_fields=(
                "status",
                "token_hash",
                "expires_at",
                "resend_count",
                "updated_at",
            )
        )
        _schedule_delivery(locked_invitation, token)

    locked_invitation.refresh_from_db()
    return locked_invitation


def revoke_member_invitation(actor_member, invitation):
    """Revoke one pending invitation under tenant and row locks."""
    with transaction.atomic():
        locked_business = Business.objects.select_for_update().get(
            pk=invitation.business_id,
        )
        locked_actor = BusinessMember.objects.select_for_update().get(
            pk=actor_member.pk,
        )
        locked_invitation = (
            BusinessMemberInvitation.objects.select_for_update()
            .filter(
                pk=invitation.pk,
                business=locked_business,
            )
            .first()
        )
        if locked_invitation is None:
            raise ValidationError("Invitation introuvable.")
        _validate_actor(locked_actor, locked_business)

        effective_status = validate_invitation_state(locked_invitation)
        if effective_status == BusinessMemberInvitation.Status.EXPIRED:
            raise ValidationError(
                "Cette invitation a expiré. Veuillez demander un nouveau lien."
            )
        if effective_status == BusinessMemberInvitation.Status.REVOKED:
            raise ValidationError("Cette invitation a été révoquée.")
        if effective_status != BusinessMemberInvitation.Status.PENDING:
            raise ValidationError(
                "Seule une invitation en attente peut être révoquée."
            )
        locked_invitation.status = BusinessMemberInvitation.Status.REVOKED
        locked_invitation.acted_at = timezone.now()
        locked_invitation.save(
            update_fields=("status", "acted_at", "updated_at")
        )

    return locked_invitation


def validate_invitation_state(invitation):
    """Return the effective state of an invitation, expiring it if needed."""
    if invitation.status != BusinessMemberInvitation.Status.PENDING:
        return invitation.status
    if invitation.is_expired:
        return BusinessMemberInvitation.Status.EXPIRED
    return BusinessMemberInvitation.Status.PENDING
