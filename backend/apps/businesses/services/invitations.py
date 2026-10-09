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
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from ..models import (
    Business,
    BusinessMember,
    BusinessMemberInvitation,
    BusinessMemberPermission,
)


INVITATION_EXPIRY_HOURS = getattr(
    settings,
    "BUSINESS_MEMBER_INVITATION_EXPIRY_HOURS",
    168,
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
    return timezone.now() + timedelta(hours=INVITATION_EXPIRY_HOURS)


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

    normalized_email = normalize_email(email)
    if not normalized_email:
        raise ValidationError({"email": "A valid invitation address is required."})

    with transaction.atomic():
        locked_business = Business.objects.select_for_update().get(pk=business.pk)
        locked_actor = BusinessMember.objects.select_for_update().get(
            pk=actor_member.pk,
        )
        locked_actor.business = locked_business

        if (
            locked_actor.status != BusinessMember.Status.ACTIVE
            or locked_actor.business_id != locked_business.pk
            or not locked_actor.is_owner
        ) and not BusinessMemberPermission.objects.filter(
            member=locked_actor,
            permission=BusinessMemberPermission.Permission.MANAGE_MEMBERS,
        ).exists():
            raise ValidationError("An authorized member manager is required.")
        if locked_business.status != Business.Status.ACTIVE:
            raise ValidationError("Invitations require an active Business.")

        existing_membership = BusinessMember.objects.filter(
            business=locked_business,
            identity__carri_subject=normalized_email,
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
                last_sent_at=timezone.now(),
            )
        except IntegrityError as exc:
            raise ValidationError(
                {"email": "A pending invitation already exists for this address."}
            ) from exc

    return invitation, token


def validate_invitation_state(invitation):
    """Return the effective state of an invitation, expiring it if needed."""
    if invitation.status != BusinessMemberInvitation.Status.PENDING:
        return invitation.status
    if invitation.is_expired:
        return BusinessMemberInvitation.Status.EXPIRED
    return BusinessMemberInvitation.Status.PENDING
