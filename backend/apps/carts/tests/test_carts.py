from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CarriIdentity
from apps.businesses.models import Business, BusinessMember
from apps.catalog.models import Product, ProductCategory, UnitOfMeasure
from apps.carts.models import Cart, CartItem


pytestmark = pytest.mark.django_db


def api(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def setup():
    pcs, _ = UnitOfMeasure.objects.get_or_create(
        code="PCS", defaults={"name": "Pièce", "symbol": "pcs", "category": "COUNT", "allows_decimal_quantity": False}
    )
    kg, _ = UnitOfMeasure.objects.get_or_create(
        code="KG", defaults={"name": "Kilogramme", "symbol": "kg", "category": "WEIGHT", "allows_decimal_quantity": True}
    )
    category = ProductCategory.objects.create(code="CART_CAT", name="Cart", slug="cart")
    business = Business.objects.create(name="Shop A")
    other = Business.objects.create(name="Shop B")
    buyer = CarriIdentity.objects.create(carri_subject="cart-buyer")
    other_buyer = CarriIdentity.objects.create(carri_subject="cart-other-buyer")
    product = Product.objects.create(business=business, category=category, name="Piece", unit_of_measure=pcs, selling_price="1", currency="CDF", attributes={}, is_public=True, is_online_purchasable=True)
    kilogram_product = Product.objects.create(business=business, category=category, name="Weight", unit_of_measure=kg, selling_price="1", currency="CDF", attributes={}, is_public=True, is_online_purchasable=True)
    foreign = Product.objects.create(business=other, category=category, name="Foreign", unit_of_measure=pcs, selling_price="1", currency="CDF", attributes={}, is_public=True, is_online_purchasable=True)
    return buyer, other_buyer, business, other, product, kilogram_product, foreign


def create_cart(client, business, name):
    response = client.post("/api/v1/carts/", {"business": business.public_id, "name": name}, format="json")
    assert response.status_code == 201, response.data
    return response.data["reference"]


def test_multiple_carts_normalized_names_and_buyer_business_scope(setup):
    buyer, other_buyer, business, other, _, _, _ = setup
    client = api(buyer)
    first = create_cart(client, business, "Maison")
    assert first.startswith("CT")
    assert client.post("/api/v1/carts/", {"business": business.public_id, "name": " maison "}, format="json").status_code == 400
    assert client.post("/api/v1/carts/", {"business": business.public_id, "name": "  "}, format="json").status_code == 400
    assert create_cart(client, other, "Maison")
    assert create_cart(api(other_buyer), business, "Maison")
    listed = client.get("/api/v1/carts/", {"business": business.public_id})
    assert listed.status_code == 200 and listed.data["count"] == 1


def test_add_merge_quantities_and_unit_validation(setup):
    buyer, _, business, _, product, kg_product, foreign = setup
    client = api(buyer)
    cart = create_cart(client, business, "Main")
    endpoint = f"/api/v1/carts/{cart}/items/"
    assert client.post(endpoint, {"product": product.public_id, "quantity": "2"}, format="json").status_code == 201
    merged = client.post(endpoint, {"product": product.public_id, "quantity": "3"}, format="json")
    assert merged.status_code == 201 and merged.data["items"][0]["quantity"] == "5.000"
    assert client.post(endpoint, {"product": product.public_id, "quantity": "1.5"}, format="json").status_code == 400
    assert client.post(endpoint, {"product": kg_product.public_id, "quantity": "1.5"}, format="json").status_code == 201
    assert client.post(endpoint, {"product": foreign.public_id, "quantity": "1"}, format="json").status_code == 400


def test_private_or_offline_product_cannot_be_added(setup):
    buyer, _, business, _, product, _, _ = setup
    client = api(buyer)

    product.is_public = False
    product.save(update_fields=("is_public",))
    private = client.post("/api/v1/carts/items/", {"product": product.public_id, "quantity": "1"}, format="json")

    product.is_public = True
    product.is_online_purchasable = False
    product.save(update_fields=("is_public", "is_online_purchasable"))
    offline = client.post("/api/v1/carts/items/", {"product": product.public_id, "quantity": "1"}, format="json")

    assert private.status_code == 400
    assert offline.status_code == 400
    assert not Cart.objects.filter(buyer=buyer, business=business).exists()


def test_cart_payload_exposes_safe_presentation_data(setup):
    buyer, _, business, _, product, _, _ = setup
    client = api(buyer)
    cart = create_cart(client, business, "Main")
    assert client.post(f"/api/v1/carts/{cart}/items/", {"product": product.public_id, "quantity": "2"}, format="json").status_code == 201

    payload = client.get(f"/api/v1/carts/{cart}/").data

    assert payload["business_name"] == business.name
    assert payload["items"][0] == {
        "product": product.public_id,
        "product_name": product.name,
        "unit_code": product.unit_of_measure.code,
        "unit": product.unit_of_measure.symbol,
        "allows_decimal_quantity": False,
        "quantity": "2.000",
        "selling_price": "1.00",
        "currency": "CDF",
        "primary_image_url": None,
        "created_at": payload["items"][0]["created_at"],
        "updated_at": payload["items"][0]["updated_at"],
    }


def test_auto_cart_selection_and_item_transfer(setup):
    buyer, _, business, _, product, _, _ = setup
    client = api(buyer)
    added = client.post("/api/v1/carts/items/", {"product": product.public_id, "quantity": "5"}, format="json")
    assert added.status_code == 201 and added.data["name"] == "Mon panier"
    source = added.data["reference"]
    destination = create_cart(client, business, "Other")
    transfer = client.post("/api/v1/carts/transfers/", {"source_cart": source, "destination_cart": destination, "product": product.public_id, "quantity": "2"}, format="json")
    assert transfer.status_code == 200 and transfer.data["items"][0]["quantity"] == "2.000"
    assert CartItem.objects.get(cart__reference=source, product=product).quantity == Decimal("3.000")
    assert client.post("/api/v1/carts/transfers/", {"source_cart": source, "destination_cart": destination, "product": product.public_id, "quantity": "3"}, format="json").status_code == 200
    assert not CartItem.objects.filter(cart__reference=source, product=product).exists()


def test_cross_business_ownership_and_locked_cart_mutations(setup):
    buyer, other_buyer, business, other, product, _, _ = setup
    client = api(buyer)
    cart_reference = create_cart(client, business, "Locked")
    cart = Cart.objects.get(reference=cart_reference)
    CartItem.objects.create(cart=cart, product=product, quantity="1")
    foreign_cart = create_cart(client, other, "Foreign")
    assert client.post("/api/v1/carts/transfers/", {"source_cart": cart_reference, "destination_cart": foreign_cart, "product": product.public_id, "quantity": "1"}, format="json").status_code == 400
    assert api(other_buyer).get(f"/api/v1/carts/{cart_reference}/").status_code == 404
    cart.status = Cart.Status.LOCKED
    cart.save(update_fields=("status",))
    assert client.patch(f"/api/v1/carts/{cart_reference}/", {"name": "No"}, format="json").status_code == 409
    assert client.post(f"/api/v1/carts/{cart_reference}/items/", {"product": product.public_id, "quantity": "1"}, format="json").status_code == 409
    assert client.patch(f"/api/v1/carts/{cart_reference}/items/{product.public_id}/", {"quantity": "2"}, format="json").status_code == 409
    assert client.delete(f"/api/v1/carts/{cart_reference}/items/{product.public_id}/").status_code == 409
    assert client.post(f"/api/v1/carts/{cart_reference}/clear/", {}, format="json").status_code == 409
    assert client.delete(f"/api/v1/carts/{cart_reference}/").status_code == 409


@pytest.mark.parametrize(
    ("role", "is_owner", "title"),
    [
        (BusinessMember.Role.OWNER, True, "Gérant"),
        (BusinessMember.Role.MANAGER, False, "Administrateur"),
        (BusinessMember.Role.EMPLOYEE, False, "Employé"),
    ],
)
def test_active_business_members_cannot_create_or_auto_create_carts(setup, role, is_owner, title):
    buyer, _, business, _, product, _, _ = setup
    BusinessMember.objects.create(
        identity=buyer,
        business=business,
        role=role,
        is_owner=is_owner,
        title=title,
        status=BusinessMember.Status.ACTIVE,
    )
    client = api(buyer)

    created = client.post("/api/v1/carts/", {"business": business.public_id, "name": "Interdit"}, format="json")
    automatic = client.post("/api/v1/carts/items/", {"product": product.public_id, "quantity": "1"}, format="json")

    for response in (created, automatic):
        assert response.status_code == 403
        assert response.data == {
            "code": "BUSINESS_MEMBER_CANNOT_PURCHASE",
            "detail": "Vous ne pouvez pas acheter de produits dans une boutique dont vous êtes membre.",
        }
    assert not Cart.objects.filter(buyer=buyer, business=business).exists()


def test_member_status_and_business_scope_determine_purchase_eligibility(setup):
    buyer, _, business, other, product, _, foreign = setup
    BusinessMember.objects.create(
        identity=buyer,
        business=business,
        role=BusinessMember.Role.EMPLOYEE,
        title="Ancien membre",
        status=BusinessMember.Status.SUSPENDED,
    )
    client = api(buyer)
    assert create_cart(client, business, "Autorisé")

    BusinessMember.objects.filter(identity=buyer, business=business).update(status=BusinessMember.Status.REMOVED)
    assert create_cart(client, other, "Autre boutique")

    BusinessMember.objects.filter(identity=buyer, business=business).update(status=BusinessMember.Status.ACTIVE)
    assert client.post("/api/v1/carts/items/", {"product": foreign.public_id, "quantity": "1"}, format="json").status_code == 201


def test_existing_cart_remains_readable_but_member_cannot_mutate_after_joining(setup):
    buyer, other_buyer, business, _, product, _, _ = setup
    client = api(buyer)
    source = create_cart(client, business, "Avant adhésion")
    destination = create_cart(client, business, "Destination")
    assert client.post(f"/api/v1/carts/{source}/items/", {"product": product.public_id, "quantity": "2"}, format="json").status_code == 201
    BusinessMember.objects.create(
        identity=buyer,
        business=business,
        role=BusinessMember.Role.EMPLOYEE,
        title="Membre",
        status=BusinessMember.Status.ACTIVE,
    )

    assert client.get(f"/api/v1/carts/{source}/").status_code == 200
    assert api(other_buyer).get(f"/api/v1/carts/{source}/").status_code == 404
    for response in (
        client.patch(f"/api/v1/carts/{source}/", {"name": "Interdit"}, format="json"),
        client.post("/api/v1/carts/items/", {"cart": source, "product": product.public_id, "quantity": "1"}, format="json"),
        client.post(f"/api/v1/carts/{source}/items/", {"product": product.public_id, "quantity": "1"}, format="json"),
        client.patch(f"/api/v1/carts/{source}/items/{product.public_id}/", {"quantity": "1"}, format="json"),
        client.delete(f"/api/v1/carts/{source}/items/{product.public_id}/"),
        client.post(f"/api/v1/carts/{source}/clear/", {}, format="json"),
        client.delete(f"/api/v1/carts/{source}/"),
        client.post("/api/v1/carts/transfers/", {"source_cart": source, "destination_cart": destination, "product": product.public_id, "quantity": "1"}, format="json"),
    ):
        assert response.status_code == 403
        assert response.data["code"] == "BUSINESS_MEMBER_CANNOT_PURCHASE"

    membership = BusinessMember.objects.get(identity=buyer, business=business)
    membership.status = BusinessMember.Status.SUSPENDED
    membership.save(update_fields=("status",))
    assert client.patch(f"/api/v1/carts/{source}/", {"name": "De nouveau autorisé"}, format="json").status_code == 200

    BusinessMember.objects.filter(pk=membership.pk).update(status=BusinessMember.Status.ACTIVE)
    response = client.patch(f"/api/v1/carts/{source}/", {"name": "Encore interdit"}, format="json")
    assert response.status_code == 403
    assert response.data["code"] == "BUSINESS_MEMBER_CANNOT_PURCHASE"
