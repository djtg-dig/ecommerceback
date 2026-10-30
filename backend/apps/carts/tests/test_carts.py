from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CarriIdentity
from apps.businesses.models import Business
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
    product = Product.objects.create(business=business, category=category, name="Piece", unit_of_measure=pcs, selling_price="1", currency="CDF", attributes={})
    kilogram_product = Product.objects.create(business=business, category=category, name="Weight", unit_of_measure=kg, selling_price="1", currency="CDF", attributes={})
    foreign = Product.objects.create(business=other, category=category, name="Foreign", unit_of_measure=pcs, selling_price="1", currency="CDF", attributes={})
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
        "unit": product.unit_of_measure.symbol,
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
