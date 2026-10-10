"""Administrative API tests for Business member invitations."""

from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import CarriIdentity
from apps.businesses.models import (
    Business,
    BusinessMember,
    BusinessMemberInvitation,
    BusinessMemberPermission,
)
from apps.businesses.services import grant_permission
from apps.businesses.services.invitations import hash_invitation_token


pytestmark = pytest.mark.django_db(transaction=True)
Permission = BusinessMemberPermission.Permission


@pytest.fixture(autouse=True)
def invitation_delivery_settings(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.DEFAULT_FROM_EMAIL = "E-commerce <no-reply@example.com>"
    settings.BUSINESS_MEMBER_INVITATION_URL = (
        "https://app.example.com/business-invitations"
    )


def create_business_with_owner(suffix):
    business = Business.objects.create(name=f"Commerce {suffix}")
    identity = CarriIdentity.objects.create(
        carri_subject=f"owner-{suffix}",
        verified_email=f"owner-{suffix}@example.com",
        email_verified=True,
    )
    owner = BusinessMember.objects.create(
        business=business,
        identity=identity,
        role=BusinessMember.Role.OWNER,
    )
    return business, identity, owner


def create_member(business, suffix, *, role=BusinessMember.Role.EMPLOYEE):
    identity = CarriIdentity.objects.create(
        carri_subject=f"member-{suffix}",
        verified_email=f"member-{suffix}@example.com",
        email_verified=True,
    )
    member = BusinessMember.objects.create(
        business=business,
        identity=identity,
        role=role,
        title="Employé",
    )
    return identity, member


def client_for(identity):
    client = APIClient()
    client.force_authenticate(user=identity)
    return client


def collection_url(business):
    return f"/api/v1/businesses/{business.public_id}/invitations/"


def action_url(business, invitation, action):
    return (
        f"/api/v1/businesses/{business.public_id}/invitations/"
        f"{invitation.public_id}/{action}/"
    )


def test_owner_creates_and_lists_compact_paginated_invitations(mailoutbox):
    business, identity, owner = create_business_with_owner("owner-api")
    client = client_for(identity)

    created = client.post(
        collection_url(business),
        {"email": " Invitee@Example.COM ", "title": "Caissier"},
        format="json",
    )

    assert created.status_code == 201
    assert created.data["email"] == "invitee@example.com"
    assert created.data["title"] == "Caissier"
    assert created.data["status"] == "PENDING"
    assert created.data["last_sent_at"] is not None
    assert created.data["public_id"].startswith("MI")
    assert "token_hash" not in created.data
    assert "token" not in created.data
    assert len(mailoutbox) == 1
    assert business.name in mailoutbox[0].subject
    delivered_link = next(
        line.strip()
        for line in mailoutbox[0].body.splitlines()
        if line.strip().startswith("https://")
    )
    delivered_query = parse_qs(urlsplit(delivered_link).query)
    assert urlsplit(delivered_link).path == "/business-invitations"
    assert delivered_query["invitation"][0] == created.data["public_id"]
    invitation = BusinessMemberInvitation.objects.get(
        public_id=created.data["public_id"],
    )
    assert invitation.token_hash == hash_invitation_token(
        delivered_query["token"][0]
    )
    assert mailoutbox[0].alternatives[0].mimetype == "text/html"

    listed = client.get(collection_url(business), {"page_size": 1})

    assert listed.status_code == 200
    assert listed.data["count"] == 1
    assert len(listed.data["results"]) == 1
    assert listed.data["results"][0] == created.data
    assert "token_hash" not in str(listed.data)


def test_member_with_manage_members_can_invite_but_legacy_manager_cannot(
    mailoutbox,
):
    business, owner_identity, owner = create_business_with_owner("delegated")
    allowed_identity, allowed = create_member(business, "allowed")
    denied_identity, denied = create_member(
        business,
        "legacy-manager",
        role=BusinessMember.Role.MANAGER,
    )
    grant_permission(owner, allowed, Permission.MANAGE_MEMBERS)

    allowed_response = client_for(allowed_identity).post(
        collection_url(business),
        {"email": "allowed-invitee@example.com"},
        format="json",
    )
    denied_response = client_for(denied_identity).post(
        collection_url(business),
        {"email": "denied-invitee@example.com"},
        format="json",
    )

    assert allowed_response.status_code == 201
    assert denied_response.status_code == 403
    assert denied_response.data == {
        "code": "invitation_permission_denied",
        "detail": "Vous n'êtes pas autorisé à gérer les invitations de cette entreprise.",
    }


def test_suspended_manager_is_refused():
    business, owner_identity, owner = create_business_with_owner("suspended")
    identity, manager = create_member(business, "suspended-manager")
    grant_permission(owner, manager, Permission.MANAGE_MEMBERS)
    manager.status = BusinessMember.Status.SUSPENDED
    manager.save(update_fields=("status", "updated_at"))

    response = client_for(identity).get(collection_url(business))

    assert response.status_code == 403
    assert response.data["code"] == "invitation_permission_denied"


def test_duplicate_and_invalid_email_have_stable_messages(mailoutbox):
    business, identity, owner = create_business_with_owner("validation")
    client = client_for(identity)
    assert client.post(
        collection_url(business),
        {"email": "duplicate@example.com"},
        format="json",
    ).status_code == 201

    duplicate = client.post(
        collection_url(business),
        {"email": "duplicate@example.com"},
        format="json",
    )
    invalid = client.post(
        collection_url(business),
        {"email": "not-an-email"},
        format="json",
    )

    assert duplicate.status_code == 409
    assert duplicate.data["code"] == "invitation_already_pending"
    assert duplicate.data["detail"] == (
        "Une invitation est déjà en attente pour cette adresse e-mail."
    )
    assert invalid.status_code == 400
    assert invalid.data["code"] == "invalid_email"
    assert invalid.data["email"] == [
        "Veuillez saisir une adresse e-mail valide."
    ]


@pytest.mark.parametrize(
    "member_status",
    [BusinessMember.Status.ACTIVE, BusinessMember.Status.SUSPENDED],
)
def test_existing_member_cannot_be_invited(member_status):
    business, owner_identity, owner = create_business_with_owner(
        f"existing-{member_status.lower()}"
    )
    target_identity, target = create_member(
        business,
        f"target-{member_status.lower()}",
    )
    target.status = member_status
    target.save(update_fields=("status", "updated_at"))

    response = client_for(owner_identity).post(
        collection_url(business),
        {"email": target_identity.verified_email},
        format="json",
    )

    assert response.status_code == 409
    assert response.data["code"] == "business_member_already_exists"
    assert response.data["detail"] == (
        "Cette personne est déjà membre de l'entreprise."
    )


@pytest.mark.parametrize(
    "business_status",
    [Business.Status.SUSPENDED, Business.Status.ARCHIVED],
)
def test_inactive_business_blocks_mutations(business_status):
    business, identity, owner = create_business_with_owner(
        f"inactive-{business_status.lower()}"
    )
    business.status = business_status
    business.save(update_fields=("status", "updated_at"))

    response = client_for(identity).post(
        collection_url(business),
        {"email": "invitee@example.com"},
        format="json",
    )

    assert response.status_code == 409
    assert response.data["code"] == "business_inactive"
    assert not BusinessMemberInvitation.objects.filter(
        business=business,
    ).exists()


def test_resend_rotates_token_and_renews_expiration(mailoutbox):
    business, identity, owner = create_business_with_owner("resend")
    client = client_for(identity)
    created = client.post(
        collection_url(business),
        {"email": "resend@example.com"},
        format="json",
    )
    invitation = BusinessMemberInvitation.objects.get(
        public_id=created.data["public_id"],
    )
    old_hash = invitation.token_hash
    old_expiry = invitation.expires_at

    response = client.post(action_url(business, invitation, "resend"))

    assert response.status_code == 200
    invitation.refresh_from_db()
    assert invitation.token_hash != old_hash
    assert invitation.expires_at > old_expiry
    assert invitation.resend_count == 1
    assert len(mailoutbox) == 2
    new_url = next(
        line
        for line in mailoutbox[-1].body.splitlines()
        if line.strip().startswith("https://")
    )
    new_query = parse_qs(urlsplit(new_url).query)
    assert new_query["invitation"][0] == invitation.public_id
    new_token = new_query["token"][0]
    assert invitation.token_hash == hash_invitation_token(new_token)
    assert old_hash not in str(response.data)
    assert new_token not in str(response.data)


def test_expired_invitation_is_reported_and_can_be_resent(mailoutbox):
    business, identity, owner = create_business_with_owner("expired")
    client = client_for(identity)
    created = client.post(
        collection_url(business),
        {"email": "expired@example.com"},
        format="json",
    )
    invitation = BusinessMemberInvitation.objects.get(
        public_id=created.data["public_id"],
    )
    invitation.expires_at = timezone.now() - timezone.timedelta(minutes=1)
    invitation.save(update_fields=("expires_at", "updated_at"))

    listed = client.get(collection_url(business))
    resent = client.post(action_url(business, invitation, "resend"))

    assert listed.data["results"][0]["status"] == "EXPIRED"
    assert resent.status_code == 200
    assert resent.data["status"] == "PENDING"


def test_revoke_is_tenant_scoped_and_never_creates_membership(mailoutbox):
    business, identity, owner = create_business_with_owner("revoke")
    other_business, other_identity, other_owner = create_business_with_owner(
        "other"
    )
    client = client_for(identity)
    created = client.post(
        collection_url(business),
        {"email": "revoke@example.com"},
        format="json",
    )
    invitation = BusinessMemberInvitation.objects.get(
        public_id=created.data["public_id"],
    )

    foreign = client_for(other_identity).post(
        action_url(other_business, invitation, "revoke")
    )
    revoked = client.post(action_url(business, invitation, "revoke"))
    revoked_again = client.post(action_url(business, invitation, "revoke"))

    assert foreign.status_code == 404
    assert revoked.status_code == 200
    assert revoked.data["status"] == "REVOKED"
    assert revoked_again.status_code == 409
    assert revoked_again.data == {
        "code": "invitation_revoked",
        "detail": "Cette invitation a été révoquée.",
    }
    invitation.refresh_from_db()
    assert invitation.acted_at is not None
    assert invitation.member is None
    assert not BusinessMember.objects.filter(
        business=business,
        identity__verified_email="revoke@example.com",
    ).exists()


def test_missing_delivery_configuration_refuses_before_persistence(settings):
    business, identity, owner = create_business_with_owner("no-delivery")
    settings.BUSINESS_MEMBER_INVITATION_URL = ""

    response = client_for(identity).post(
        collection_url(business),
        {"email": "no-delivery@example.com"},
        format="json",
    )

    assert response.status_code == 503
    assert response.data["code"] == "invitation_delivery_unavailable"
    assert response.data["detail"] == (
        "L'envoi de l'invitation est temporairement indisponible. Veuillez réessayer."
    )
    assert not BusinessMemberInvitation.objects.filter(
        business=business,
    ).exists()


def test_delivery_failure_keeps_unsent_invitation_for_explicit_resend():
    business, identity, owner = create_business_with_owner("delivery-failure")

    with patch(
        "apps.businesses.services.invitation_email.EmailMultiAlternatives.send",
        side_effect=RuntimeError("provider unavailable"),
    ):
        response = client_for(identity).post(
            collection_url(business),
            {"email": "failure@example.com"},
            format="json",
        )

    assert response.status_code == 503
    invitation = BusinessMemberInvitation.objects.get(business=business)
    assert invitation.status == BusinessMemberInvitation.Status.PENDING
    assert invitation.last_sent_at is None
    assert invitation.member is None


def test_openapi_documents_all_administrative_invitation_operations():
    from drf_spectacular.generators import SchemaGenerator

    schema = SchemaGenerator().get_schema(request=None, public=True)
    base = "/api/v1/businesses/{public_id}/invitations/"
    action = (
        "/api/v1/businesses/{public_id}/invitations/"
        "{invitation_public_id}"
    )

    assert {"get", "post"}.issubset(schema["paths"][base])
    assert "post" in schema["paths"][f"{action}/resend/"]
    assert "post" in schema["paths"][f"{action}/revoke/"]
    create = schema["paths"][base]["post"]
    assert create["summary"] == "Inviter une personne à rejoindre une entreprise"
    assert {"201", "400", "403", "404", "409", "503"}.issubset(
        create["responses"]
    )
