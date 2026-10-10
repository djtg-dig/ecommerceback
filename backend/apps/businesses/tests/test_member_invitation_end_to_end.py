"""End-to-end integration tests for the Business invitation lifecycle."""

import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.db import close_old_connections, transaction
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
    hash_invitation_token,
    invite_member,
    resend_member_invitation,
    revoke_member_invitation,
)


pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def invitation_delivery_settings(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.DEFAULT_FROM_EMAIL = "E-commerce <no-reply@example.com>"
    settings.BUSINESS_MEMBER_INVITATION_URL = (
        "https://app.example.com/business-invitations"
    )


def fresh_identity(subject, email):
    now = timezone.now()
    return CarriIdentity.objects.create(
        carri_subject=subject,
        verified_email=email,
        email_verified=True,
        email_verified_at=now,
        last_oidc_auth_at=now,
    )


def context(suffix):
    business = Business.objects.create(name=f"Commerce {suffix}")
    owner_identity = fresh_identity(
        f"owner-{suffix}",
        f"owner-{suffix}@example.com",
    )
    owner = BusinessMember.objects.create(
        business=business,
        identity=owner_identity,
        role=BusinessMember.Role.OWNER,
    )
    recipient = fresh_identity(
        f"recipient-{suffix}",
        f"recipient-{suffix}@example.com",
    )
    return business, owner_identity, owner, recipient


def client_for(identity):
    client = APIClient()
    client.force_authenticate(user=identity)
    return client


def extract_link(message):
    link = next(
        line.strip()
        for line in message.body.splitlines()
        if line.strip().startswith("https://")
    )
    query = parse_qs(urlsplit(link).query)
    return query["invitation"][0], query["token"][0]


@pytest.mark.parametrize(
    ("action", "expected_status", "member_count"),
    [("accept", "ACCEPTED", 1), ("decline", "DECLINED", 0)],
)
def test_admin_email_link_drives_recipient_action_end_to_end(
    action,
    expected_status,
    member_count,
    mailoutbox,
    caplog,
):
    business, owner_identity, owner, recipient = context(f"e2e-{action}")
    admin = client_for(owner_identity)

    created = admin.post(
        f"/api/v1/businesses/{business.public_id}/invitations/",
        {"email": recipient.verified_email, "title": "Caissier"},
        format="json",
    )

    assert created.status_code == 201
    assert len(mailoutbox) == 1
    invitation_public_id, token = extract_link(mailoutbox[0])
    assert invitation_public_id == created.data["public_id"]
    assert token not in caplog.text

    acted = client_for(recipient).post(
        f"/api/v1/me/business-invitations/{invitation_public_id}/{action}/",
        {"token": token},
        format="json",
    )

    assert acted.status_code == 200
    assert acted.data["status"] == expected_status
    assert "token" not in str(acted.data)
    assert BusinessMember.objects.filter(
        business=business,
        identity=recipient,
    ).count() == member_count
    if member_count:
        member = BusinessMember.objects.get(
            business=business,
            identity=recipient,
        )
        assert member.title == "Caissier"
        assert member.is_owner is False
        assert not member.permissions.exists()

    listed = admin.get(
        f"/api/v1/businesses/{business.public_id}/invitations/"
    )
    assert listed.status_code == 200
    assert listed.data["results"][0]["status"] == expected_status
    assert "token" not in str(listed.data)


def test_failed_initial_delivery_can_be_recovered_by_resend(mailoutbox):
    business, owner_identity, owner, recipient = context("delivery-recovery")
    admin = client_for(owner_identity)

    with patch(
        "apps.businesses.services.invitation_email.EmailMultiAlternatives.send",
        side_effect=RuntimeError("provider unavailable"),
    ):
        failed = admin.post(
            f"/api/v1/businesses/{business.public_id}/invitations/",
            {"email": recipient.verified_email},
            format="json",
        )

    assert failed.status_code == 503
    invitation = BusinessMemberInvitation.objects.get(business=business)
    assert invitation.last_sent_at is None

    resent = admin.post(
        f"/api/v1/businesses/{business.public_id}/invitations/"
        f"{invitation.public_id}/resend/"
    )

    assert resent.status_code == 200
    invitation.refresh_from_db()
    assert invitation.last_sent_at is not None
    assert invitation.resend_count == 1
    assert len(mailoutbox) == 1
    invitation_public_id, token = extract_link(mailoutbox[0])
    assert invitation_public_id == invitation.public_id
    assert invitation.token_hash == hash_invitation_token(token)


def test_administrative_not_found_errors_have_stable_safe_codes():
    business, owner_identity, owner, recipient = context("not-found")
    client = client_for(owner_identity)

    missing_business = client.get(
        "/api/v1/businesses/SH2222222222/invitations/"
    )
    missing_invitation = client.post(
        f"/api/v1/businesses/{business.public_id}/invitations/MI2222222222/revoke/"
    )

    assert missing_business.status_code == 404
    assert missing_business.data == {
        "code": "business_not_found",
        "detail": "Entreprise introuvable.",
    }
    assert missing_invitation.status_code == 404
    assert missing_invitation.data == {
        "code": "invitation_not_found",
        "detail": "Invitation introuvable.",
    }


def test_missing_business_and_invitation_are_stable_for_every_action():
    business, owner_identity, owner, recipient = context("not-found-actions")
    client = client_for(owner_identity)

    created = client.post(
        f"/api/v1/businesses/{business.public_id}/invitations/",
        {"email": "stale@example.com"},
        format="json",
    )
    invitation = BusinessMemberInvitation.objects.get(
        public_id=created.data["public_id"],
    )

    for method, unknown_business_url in (
        (
            "get",
            "/api/v1/businesses/SH2222222222/invitations/",
        ),
        (
            "post",
            "/api/v1/businesses/SH2222222222/invitations/",
        ),
    ):
        response = getattr(client, method)(
            unknown_business_url,
            format="json",
        )
        assert response.status_code == 404
        assert response.data["code"] == "business_not_found"

    for action in ("resend", "revoke"):
        response = client.post(
            f"/api/v1/businesses/SH2222222222/invitations/"
            f"{invitation.public_id}/{action}/"
        )
        assert response.status_code == 404
        assert response.data["code"] == "business_not_found"

        response = client.post(
            f"/api/v1/businesses/{business.public_id}/invitations/"
            f"MI2222222222/{action}/"
        )
        assert response.status_code == 404
        assert response.data["code"] == "invitation_not_found"


def test_delivered_link_is_copyable_and_carries_both_public_identifiers(
    mailoutbox,
    caplog,
):
    business, owner_identity, owner, recipient = context("link-contract")
    admin = client_for(owner_identity)

    created = admin.post(
        f"/api/v1/businesses/{business.public_id}/invitations/",
        {"email": recipient.verified_email, "title": "Caissier"},
        format="json",
    )
    invitation = BusinessMemberInvitation.objects.get(
        public_id=created.data["public_id"],
    )

    assert len(mailoutbox) == 1
    message = mailoutbox[0]
    assert "&amp;" not in message.body
    text_link, html_link = (
        next(
            line.strip()
            for line in message.body.splitlines()
            if line.strip().startswith("https://")
        ),
        re.search(
            r'href="https://[^"]+"',
            message.alternatives[0][0],
        )
        .group(0)
        .removeprefix('href="')
        .removesuffix('"'),
    )

    text_query = parse_qs(urlsplit(text_link).query)
    assert text_query["invitation"][0] == invitation.public_id
    assert invitation.token_hash == hash_invitation_token(text_query["token"][0])
    assert text_link == html_link.replace("&amp;", "&")
    assert text_query["token"][0] not in caplog.text
    assert text_query["token"][0] not in str(created.data)

    consumed = client_for(recipient).post(
        f"/api/v1/me/business-invitations/{text_query['invitation'][0]}/accept/",
        {"token": text_query["token"][0]},
        format="json",
    )
    assert consumed.status_code == 200
    assert consumed.data["status"] == "ACCEPTED"


def test_acceptance_and_revocation_are_serialized():
    business, owner_identity, owner, recipient = context("accept-revoke")
    invitation, token = invite_member(
        owner,
        business,
        recipient.verified_email,
    )

    def accept():
        close_old_connections()
        try:
            accept_member_invitation(recipient, invitation.public_id, token)
            return "accepted"
        except InvitationActionError as exc:
            return exc.code
        finally:
            close_old_connections()

    def revoke():
        close_old_connections()
        try:
            revoke_member_invitation(owner, invitation)
            return "revoked"
        except ValidationError:
            return "revoke_refused"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [executor.submit(accept), executor.submit(revoke)]
        outcomes = frozenset(future.result() for future in results)

    invitation.refresh_from_db()
    member_count = BusinessMember.objects.filter(
        business=business,
        identity=recipient,
    ).count()
    assert (invitation.status, member_count, outcomes) in {
        (
            BusinessMemberInvitation.Status.ACCEPTED,
            1,
            frozenset({"accepted", "revoke_refused"}),
        ),
        (
            BusinessMemberInvitation.Status.REVOKED,
            0,
            frozenset({"revoked", "invitation_revoked"}),
        ),
    }


def test_acceptance_and_resend_are_serialized():
    business, owner_identity, owner, recipient = context("accept-resend")
    invitation, token = invite_member(
        owner,
        business,
        recipient.verified_email,
    )

    def accept():
        close_old_connections()
        try:
            accept_member_invitation(recipient, invitation.public_id, token)
            return "accepted"
        except InvitationActionError as exc:
            return exc.code
        finally:
            close_old_connections()

    def resend():
        close_old_connections()
        try:
            resend_member_invitation(owner, invitation)
            return "resent"
        except ValidationError:
            return "resend_refused"
        finally:
            close_old_connections()

    with patch(
        "apps.businesses.services.invitation_email.send_invitation_email"
    ):
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = [executor.submit(accept), executor.submit(resend)]
            outcomes = frozenset(future.result() for future in results)

    invitation.refresh_from_db()
    member_count = BusinessMember.objects.filter(
        business=business,
        identity=recipient,
    ).count()
    assert (invitation.status, member_count, outcomes) in {
        (
            BusinessMemberInvitation.Status.ACCEPTED,
            1,
            frozenset({"accepted", "resend_refused"}),
        ),
        (
            BusinessMemberInvitation.Status.PENDING,
            0,
            frozenset({"resent", "invalid_invitation_token"}),
        ),
    }
    if invitation.status == BusinessMemberInvitation.Status.PENDING:
        assert invitation.resend_count == 1


def test_acceptance_and_business_suspension_are_serialized():
    business, owner_identity, owner, recipient = context("accept-suspend")
    invitation, token = invite_member(
        owner,
        business,
        recipient.verified_email,
    )

    def accept():
        close_old_connections()
        try:
            accept_member_invitation(recipient, invitation.public_id, token)
            return "accepted"
        except InvitationActionError as exc:
            return exc.code
        finally:
            close_old_connections()

    def suspend_business():
        close_old_connections()
        try:
            with transaction.atomic():
                locked = Business.objects.select_for_update().get(pk=business.pk)
                locked.status = Business.Status.SUSPENDED
                locked.save(update_fields=("status", "updated_at"))
            return "suspended"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [executor.submit(accept), executor.submit(suspend_business)]
        outcomes = frozenset(future.result() for future in results)

    invitation.refresh_from_db()
    member_count = BusinessMember.objects.filter(
        business=business,
        identity=recipient,
    ).count()
    assert outcomes in (
        frozenset({"accepted", "suspended"}),
        frozenset({"business_inactive", "suspended"}),
    )
    assert member_count == (1 if invitation.status == "ACCEPTED" else 0)


def test_double_http_submission_creates_one_membership():
    business, owner_identity, owner, recipient = context("double-submit")
    invitation, token = invite_member(
        owner,
        business,
        recipient.verified_email,
    )
    client = client_for(recipient)
    url = f"/api/v1/me/business-invitations/{invitation.public_id}/accept/"

    first = client.post(url, {"token": token}, format="json")
    second = client.post(url, {"token": token}, format="json")

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.data["code"] == "invitation_already_processed"
    assert BusinessMember.objects.filter(
        business=business,
        identity=recipient,
    ).count() == 1


def test_openapi_documents_stable_administrative_error_payloads():
    from drf_spectacular.generators import SchemaGenerator

    schema = SchemaGenerator().get_schema(request=None, public=True)
    error_schema = "#/components/schemas/BusinessMemberInvitationError"
    base = "/api/v1/businesses/{public_id}/invitations/"
    action = (
        "/api/v1/businesses/{public_id}/invitations/"
        "{invitation_public_id}"
    )

    expected = {
        base: (
            ("get", ("200", "403", "404")),
            ("post", ("201", "400", "403", "404", "409", "503")),
        ),
        f"{action}/resend/": (
            ("post", ("200", "403", "404", "409", "503")),
        ),
        f"{action}/revoke/": (("post", ("200", "403", "404", "409")),),
    }

    for path, operations in expected.items():
        for method, statuses in operations:
            operation = schema["paths"][path][method]
            assert set(operation["responses"]) == set(statuses)
            for status in statuses:
                if status.startswith("2"):
                    continue
                content = operation["responses"][status]["content"]
                assert content["application/json"]["schema"]["$ref"] == (
                    error_schema
                ), (path, method, status)
