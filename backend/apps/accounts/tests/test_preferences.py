import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CarriIdentity
from apps.accounts.views import _pair


def authenticated_client(identity):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {_pair(identity)['access']}")
    return client


@pytest.mark.django_db
def test_preferences_are_absent_until_the_identity_selects_a_language():
    identity = CarriIdentity.objects.create(carri_subject="without-preference")

    response = authenticated_client(identity).get("/api/v1/auth/me/preferences/")

    assert response.status_code == 200
    assert response.json() == {"preferred_language": ""}


@pytest.mark.django_db
@pytest.mark.parametrize("language", ["fr", "en"])
def test_identity_can_persist_a_supported_language(language):
    identity = CarriIdentity.objects.create(carri_subject=f"language-{language}")
    client = authenticated_client(identity)

    response = client.patch(
        "/api/v1/auth/me/preferences/", {"preferred_language": language}, format="json"
    )

    assert response.status_code == 200
    assert response.json() == {"preferred_language": language}
    identity.refresh_from_db()
    assert identity.preferred_language == language


@pytest.mark.django_db
def test_preferences_reject_an_unsupported_language_without_changing_the_identity():
    identity = CarriIdentity.objects.create(carri_subject="unsupported-language")

    response = authenticated_client(identity).patch(
        "/api/v1/auth/me/preferences/", {"preferred_language": "sw"}, format="json"
    )

    assert response.status_code == 400
    identity.refresh_from_db()
    assert identity.preferred_language == ""


@pytest.mark.django_db
def test_preferences_require_authentication_and_cannot_target_another_identity():
    first = CarriIdentity.objects.create(carri_subject="first-identity")
    second = CarriIdentity.objects.create(carri_subject="second-identity")
    anonymous = APIClient()

    assert anonymous.get("/api/v1/auth/me/preferences/").status_code == 401
    assert authenticated_client(first).patch(
        "/api/v1/auth/me/preferences/", {"preferred_language": "en"}, format="json"
    ).status_code == 200
    second.refresh_from_db()
    assert second.preferred_language == ""


@pytest.mark.django_db
def test_preference_initialisation_is_idempotent_and_preserves_identity_fields():
    identity = CarriIdentity.objects.create(
        carri_subject="stable-identity", verified_email="person@example.test", email_verified=True
    )
    client = authenticated_client(identity)

    assert client.patch(
        "/api/v1/auth/me/preferences/", {"preferred_language": "en"}, format="json"
    ).status_code == 200
    assert client.patch(
        "/api/v1/auth/me/preferences/", {"preferred_language": "en"}, format="json"
    ).status_code == 200

    identity.refresh_from_db()
    assert identity.preferred_language == "en"
    assert identity.carri_subject == "stable-identity"
    assert identity.verified_email == "person@example.test"
