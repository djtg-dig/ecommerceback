"""Recipient acceptance and decline tests for Business invitations."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from django.db import close_old_connections
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import CarriIdentity
from apps.businesses.models import (
    Business,
    BusinessMember,
    BusinessMemberInvitation,
)
from apps.businesses.services.invitations import (
    InvitationActionError,
    accept_member_invitation,
    generate_invitation_token,
    hash_invitation_token,
    invite_member,
)


pytestmark = pytest.mark.django_db(transaction=True)


def identity(suffix, email=None, *, fresh=True, verified=True):
    now = timezone.now()
    return CarriIdentity.objects.create(
        carri_subject=f"carri-{suffix}",
        verified_email=email or f"{suffix}@example.com",
        email_verified=verified,
        email_verified_at=now if verified and fresh else None,
        last_oidc_auth_at=now if fresh else None,
    )


def invitation_context(suffix="recipient", *, title="Caissier"):
    business = Business.objects.create(name=f"Commerce {suffix}")
    owner_identity = identity(f"owner-{suffix}")
    owner = BusinessMember.objects.create(
        business=business,
        identity=owner_identity,
        role=BusinessMember.Role.OWNER,
    )
    recipient = identity(f"invitee-{suffix}")
    invitation, token = invite_member(
        owner,
        business,
        recipient.verified_email,
        title=title,
    )
    return business, owner, recipient, invitation, token


def client_for(recipient):
    client = APIClient()
    client.force_authenticate(user=recipient)
    return client


def action_url(invitation, action):
    return (
        f"/api/v1/me/business-invitations/{invitation.public_id}/"
        f"{action}/"
    )


def test_recipient_accepts_and_gets_permissionless_non_owner_membership():
    business, owner, recipient, invitation, token = invitation_context("accept")

    response = client_for(recipient).post(
        action_url(invitation, "accept"),
        {"token": token},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["status"] == "ACCEPTED"
    assert response.data["business_public_id"] == business.public_id
    assert response.data["business_name"] == business.name
    assert "token" not in str(response.data)
    assert "email" not in response.data
    member = BusinessMember.objects.get(business=business, identity=recipient)
    assert response.data["member_public_id"] == member.public_id
    assert member.title == "Caissier"
    assert member.status == BusinessMember.Status.ACTIVE
    assert member.is_owner is False
    assert member.role == BusinessMember.Role.EMPLOYEE
    assert not member.permissions.exists()
    invitation.refresh_from_db()
    assert invitation.accepted_by == recipient
    assert invitation.member == member
    assert invitation.acted_at is not None


def test_recipient_declines_without_membership_or_permission():
    business, owner, recipient, invitation, token = invitation_context("decline")

    response = client_for(recipient).post(
        action_url(invitation, "decline"),
        {"token": token},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["status"] == "DECLINED"
    assert response.data["member_public_id"] is None
    assert not BusinessMember.objects.filter(
        business=business,
        identity=recipient,
    ).exists()
    invitation.refresh_from_db()
    assert invitation.declined_by == recipient
    assert invitation.accepted_by is None
    assert invitation.member is None
    assert invitation.acted_at is not None


def test_different_carri_account_is_refused():
    business, owner, recipient, invitation, token = invitation_context("mismatch")
    other = identity("different-account")

    response = client_for(other).post(
        action_url(invitation, "accept"),
        {"token": token},
        format="json",
    )

    assert response.status_code == 403
    assert response.data == {
        "code": "invitation_recipient_mismatch",
        "detail": "Cette invitation est destinée à un autre compte Carri.",
    }
    assert not BusinessMember.objects.filter(
        business=business,
        identity=other,
    ).exists()


def test_unverified_email_requires_verified_carri_identity():
    business, owner, recipient, invitation, token = invitation_context("unverified")
    recipient.email_verified = False
    recipient.email_verified_at = None
    recipient.save(update_fields=("email_verified", "email_verified_at"))

    response = client_for(recipient).post(
        action_url(invitation, "accept"),
        {"token": token},
        format="json",
    )

    assert response.status_code == 403
    assert response.data["code"] == "verified_email_required"


@pytest.mark.parametrize("stale_field", ["email_verified_at", "last_oidc_auth_at"])
def test_stale_oidc_proof_requires_carri_reauthentication(stale_field):
    business, owner, recipient, invitation, token = invitation_context(
        f"stale-{stale_field}"
    )
    setattr(recipient, stale_field, timezone.now() - timedelta(minutes=11))
    recipient.save(update_fields=(stale_field,))

    response = client_for(recipient).post(
        action_url(invitation, "accept"),
        {"token": token},
        format="json",
    )

    assert response.status_code == 401
    assert response.data == {
        "code": "carri_reauthentication_required",
        "detail": "Une nouvelle authentification Carri est nécessaire pour traiter cette invitation.",
    }


def test_invalid_missing_and_expired_tokens_are_refused():
    business, owner, recipient, invitation, token = invitation_context("token-errors")
    client = client_for(recipient)

    missing = client.post(action_url(invitation, "accept"), {}, format="json")
    invalid = client.post(
        action_url(invitation, "accept"),
        {"token": "x" * 32},
        format="json",
    )
    invitation.expires_at = timezone.now() - timedelta(seconds=1)
    invitation.save(update_fields=("expires_at", "updated_at"))
    expired = client.post(
        action_url(invitation, "accept"),
        {"token": token},
        format="json",
    )

    assert missing.status_code == 400
    assert missing.data["code"] == "invalid_invitation_token"
    assert invalid.status_code == 400
    assert invalid.data["code"] == "invalid_invitation_token"
    assert expired.status_code == 410
    assert expired.data["code"] == "invitation_expired"
    invitation.refresh_from_db()
    assert invitation.status == BusinessMemberInvitation.Status.EXPIRED


def test_revoked_and_rotated_tokens_are_unusable():
    business, owner, recipient, invitation, old_token = invitation_context("lifecycle")
    new_token = generate_invitation_token()
    invitation.token_hash = hash_invitation_token(new_token)
    invitation.save(update_fields=("token_hash", "updated_at"))

    old_response = client_for(recipient).post(
        action_url(invitation, "accept"),
        {"token": old_token},
        format="json",
    )
    invitation.status = BusinessMemberInvitation.Status.REVOKED
    invitation.save(update_fields=("status", "updated_at"))
    revoked_response = client_for(recipient).post(
        action_url(invitation, "accept"),
        {"token": new_token},
        format="json",
    )

    assert old_response.status_code == 400
    assert old_response.data["code"] == "invalid_invitation_token"
    assert revoked_response.status_code == 410
    assert revoked_response.data["code"] == "invitation_revoked"


@pytest.mark.parametrize(
    ("first_action", "second_action"),
    [
        ("accept", "accept"),
        ("decline", "accept"),
        ("accept", "decline"),
    ],
)
def test_terminal_invitation_cannot_be_consumed_again(first_action, second_action):
    business, owner, recipient, invitation, token = invitation_context(
        f"terminal-{first_action}-{second_action}"
    )
    client = client_for(recipient)

    first = client.post(
        action_url(invitation, first_action),
        {"token": token},
        format="json",
    )
    second = client.post(
        action_url(invitation, second_action),
        {"token": token},
        format="json",
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.data["code"] == "invitation_already_processed"
    assert BusinessMember.objects.filter(
        business=business,
        identity=recipient,
    ).count() == (1 if first_action == "accept" else 0)


def test_public_id_and_token_must_belong_to_same_invitation():
    business, owner, recipient, invitation, token = invitation_context("tenant-a")
    other_business, other_owner, other_recipient, other_invitation, other_token = (
        invitation_context("tenant-b")
    )

    response = client_for(recipient).post(
        action_url(other_invitation, "accept"),
        {"token": token},
        format="json",
    )

    assert response.status_code == 400
    assert response.data["code"] == "invalid_invitation_token"
    assert not BusinessMember.objects.filter(
        business=other_business,
        identity=recipient,
    ).exists()


def test_existing_or_removed_membership_is_not_silently_reactivated():
    business, owner, recipient, invitation, token = invitation_context("existing")
    member = BusinessMember.objects.create(
        business=business,
        identity=recipient,
        title="Ancien membre",
        status=BusinessMember.Status.REMOVED,
        removed_at=timezone.now(),
    )

    response = client_for(recipient).post(
        action_url(invitation, "accept"),
        {"token": token},
        format="json",
    )

    assert response.status_code == 409
    assert response.data["code"] == "business_member_already_exists"
    member.refresh_from_db()
    invitation.refresh_from_db()
    assert member.status == BusinessMember.Status.REMOVED
    assert invitation.status == BusinessMemberInvitation.Status.PENDING


def test_inactive_business_refuses_acceptance():
    business, owner, recipient, invitation, token = invitation_context("inactive")
    business.status = Business.Status.SUSPENDED
    business.save(update_fields=("status", "updated_at"))

    response = client_for(recipient).post(
        action_url(invitation, "accept"),
        {"token": token},
        format="json",
    )

    assert response.status_code == 409
    assert response.data["code"] == "business_inactive"


def test_concurrent_acceptance_creates_exactly_one_membership():
    business, owner, recipient, invitation, token = invitation_context("concurrent")

    def accept_once():
        close_old_connections()
        try:
            result = accept_member_invitation(
                recipient,
                invitation.public_id,
                token,
            )
            return "accepted", result[1].public_id
        except InvitationActionError as exc:
            return exc.code, None
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: accept_once(), range(2)))

    assert sorted(code for code, _member_id in results) == [
        "accepted",
        "invitation_already_processed",
    ]
    assert BusinessMember.objects.filter(
        business=business,
        identity=recipient,
    ).count() == 1


@pytest.mark.parametrize("action", ["accept", "decline"])
def test_unknown_invitation_has_a_stable_not_found_error(action):
    business, owner, recipient, invitation, token = invitation_context(
        f"unknown-{action}"
    )

    response = client_for(recipient).post(
        f"/api/v1/me/business-invitations/MI2222222222/{action}/",
        {"token": token},
        format="json",
    )

    assert response.status_code == 404
    assert response.data == {
        "code": "invitation_not_found",
        "detail": "Invitation introuvable.",
    }
    assert not BusinessMember.objects.filter(
        business=business,
        identity=recipient,
    ).exists()


def test_openapi_documents_recipient_actions_and_errors():
    from drf_spectacular.generators import SchemaGenerator

    schema = SchemaGenerator().get_schema(request=None, public=True)
    base = "/api/v1/me/business-invitations/{invitation_public_id}"

    for action in ("accept", "decline"):
        operation = schema["paths"][f"{base}/{action}/"]["post"]
        assert operation["summary"]
        assert {"200", "400", "401", "403", "404", "409", "410"}.issubset(
            operation["responses"]
        )
