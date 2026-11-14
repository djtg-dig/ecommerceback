from io import StringIO

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import CarriIdentity
from apps.businesses.models import Address, AdministrativeArea, Business, BusinessMember, Country, Locality


def auth(identity):
    client = APIClient()
    refresh = RefreshToken.for_user(identity)
    refresh["session_version"] = identity.session_version
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


@pytest.mark.django_db
def test_country_normalizes_iso2_and_enforces_its_uniqueness():
    country = Country.objects.create(name="République démocratique du Congo", iso2="cd", phone_code="+243")

    assert country.iso2 == "CD"
    with pytest.raises(ValidationError):
        Country.objects.create(name="Duplicate", iso2="CD", phone_code="+243")


@pytest.mark.django_db
def test_populate_countries_imports_the_complete_versioned_reference_idempotently():
    first_output = StringIO()
    call_command("populate_countries", stdout=first_output)

    assert Country.objects.count() == 249
    assert Country.objects.get(iso2="CD").phone_code == "+243"
    assert "créés : 249" in first_output.getvalue()

    second_output = StringIO()
    call_command("populate_countries", stdout=second_output)

    assert Country.objects.count() == 249
    assert "inchangés : 249" in second_output.getvalue()


@pytest.mark.django_db
def test_address_rejects_geographic_relations_from_another_country_or_area():
    rdc = Country.objects.create(name="RDC", iso2="CD", phone_code="+243")
    congo = Country.objects.create(name="Congo", iso2="CG", phone_code="+242")
    kinshasa = AdministrativeArea.objects.create(country=rdc, name="Kinshasa")
    brazzaville = AdministrativeArea.objects.create(country=congo, name="Brazzaville")
    locality = Locality.objects.create(administrative_area=kinshasa, name="Lemba")

    with pytest.raises(ValidationError, match="subdivision"):
        Address.objects.create(country=congo, administrative_area=kinshasa)
    with pytest.raises(ValidationError, match="localité"):
        Address.objects.create(country=rdc, administrative_area=brazzaville, locality=locality)


@pytest.mark.django_db
def test_address_allows_free_subdivision_and_city_and_validates_gps_bounds():
    country = Country.objects.create(name="RDC", iso2="CD", phone_code="+243")
    address = Address.objects.create(country=country, state="Kongo-Central", city="Matadi", latitude="-5.817", longitude="13.483")

    assert address.city == "Matadi"
    with pytest.raises(ValidationError, match="latitude"):
        Address.objects.create(country=country, latitude="91")


@pytest.mark.django_db
def test_geographic_reference_endpoints_are_public_and_filtered():
    country = Country.objects.create(name="RDC", iso2="CD", phone_code="+243")
    area = AdministrativeArea.objects.create(country=country, name="Kinshasa")
    locality = Locality.objects.create(administrative_area=area, name="Gombe")
    client = APIClient()

    countries = client.get("/api/v1/countries/?search=RDC")
    areas = client.get(f"/api/v1/administrative-areas/?country_id={country.id}")
    localities = client.get(f"/api/v1/localities/?administrative_area_id={area.id}")

    assert countries.status_code == areas.status_code == localities.status_code == 200
    assert countries.data[0]["iso2"] == "CD"
    assert areas.data[0]["name"] == "Kinshasa"
    assert localities.data[0]["name"] == "Gombe"


@pytest.mark.django_db
def test_business_can_be_created_and_read_with_a_structured_address():
    identity = CarriIdentity.objects.create(carri_subject="address-owner")
    country = Country.objects.create(name="RDC", iso2="CD", phone_code="+243")
    area = AdministrativeArea.objects.create(country=country, name="Kinshasa")
    locality = Locality.objects.create(administrative_area=area, name="Lemba")

    response = auth(identity).post(
        "/api/v1/businesses/",
        {
            "name": "Boutique avec adresse",
            "primary_currency": "CDF",
            "sales_location_type": "PHYSICAL_STORE",
            "sales_channel": "BOTH",
            "delivery_methods": ["PICKUP"],
            "structured_address": {
                "country_id": country.id,
                "administrative_area_id": area.id,
                "locality_id": locality.id,
                "state": "Kinshasa",
                "city": "Lemba",
                "street": "Avenue Exemple",
                "street_number": "12",
            },
        },
        format="json",
    )

    assert response.status_code == 201
    assert response.data["structured_address"]["country"]["iso2"] == "CD"
    assert response.data["structured_address"]["locality"]["name"] == "Lemba"
    assert Business.objects.get().structured_address_id is not None


@pytest.mark.django_db
def test_historic_business_remains_valid_without_a_structured_address():
    business = Business.objects.create(name="Entreprise historique", address="Ancienne adresse")

    assert business.structured_address is None
    assert business.address == "Ancienne adresse"


@pytest.mark.django_db
def test_only_an_authorized_member_can_update_a_business_structured_address():
    owner = CarriIdentity.objects.create(carri_subject="address-update-owner")
    outsider = CarriIdentity.objects.create(carri_subject="address-update-outsider")
    country = Country.objects.create(name="RDC", iso2="CD", phone_code="+243")
    business = Business.objects.create(name="Boutique")
    BusinessMember.objects.create(business=business, identity=owner, is_owner=True, title="Gérant")

    payload = {"structured_address": {"country_id": country.id, "city": "Kinshasa", "street": "Avenue 1"}}
    unauthorized = auth(outsider).patch(f"/api/v1/businesses/{business.public_id}/", payload, format="json")
    authorized = auth(owner).patch(f"/api/v1/businesses/{business.public_id}/", payload, format="json")
    follow_up = auth(owner).patch(
        f"/api/v1/businesses/{business.public_id}/",
        {"structured_address": {"city": "Gombe"}},
        format="json",
    )

    # Les non-membres sont volontairement masqués par la permission existante.
    assert unauthorized.status_code == 404
    assert authorized.status_code == 200, authorized.data
    assert follow_up.status_code == 200
    business.refresh_from_db()
    assert business.structured_address.city == "Gombe"
