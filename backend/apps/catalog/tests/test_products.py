"""Integration tests for tenant-scoped products and variants."""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CarriIdentity
from apps.businesses.models import Business, BusinessMember, BusinessMemberPermission
from apps.businesses.services import grant_permission
from apps.catalog.models import AttributeDefinition, AttributeOption, Product, ProductCategory, ProductVariant

pytestmark = pytest.mark.django_db


@pytest.fixture
def catalog_category():
    root = ProductCategory.objects.create(code="TEST_ROOT", name="Root", slug="test-root")
    leaf = ProductCategory.objects.create(code="TEST_SHOES", name="Shoes", slug="test-shoes", parent=root, product_type_key="SHOES_TEST")
    AttributeDefinition.objects.create(category=root, code="brand", name="Brand", data_type="text", is_required=True)
    size = AttributeDefinition.objects.create(category=leaf, code="size", name="Size", data_type="choice", is_required=True, is_variant_axis=True)
    AttributeOption.objects.create(attribute_definition=size, value="42", label="42")
    AttributeOption.objects.create(attribute_definition=size, value="43", label="43")
    return root, leaf


@pytest.fixture
def actors():
    business = Business.objects.create(name="A", primary_currency="USD")
    other_business = Business.objects.create(name="B", primary_currency="CDF")
    owner = CarriIdentity.objects.create(carri_subject="owner")
    manager = CarriIdentity.objects.create(carri_subject="manager")
    employee = CarriIdentity.objects.create(carri_subject="employee")
    outsider = CarriIdentity.objects.create(carri_subject="outsider")
    owner_member = BusinessMember.objects.create(identity=owner, business=business, role="OWNER")
    BusinessMember.objects.create(identity=owner, business=other_business, role="OWNER")
    manager_member = BusinessMember.objects.create(identity=manager, business=business, role="MANAGER")
    BusinessMember.objects.create(identity=employee, business=business, role="EMPLOYEE")
    grant_permission(
        owner_member,
        manager_member,
        BusinessMemberPermission.Permission.UPDATE_BUSINESS,
    )
    return business, other_business, owner, manager, employee, outsider


def api(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def payload(category, **overrides):
    value = {"name": "Nike Runner", "category": category.code, "selling_price": "10.50", "attributes": {"brand": "Nike"}}
    value.update(overrides)
    return value


def create_product(client, business, category, **kwargs):
    response = client.post(f"/api/v1/businesses/{business.public_id}/products/", payload(category, **kwargs), format="json")
    assert response.status_code == 201, response.data
    return response.data


def test_owner_and_manager_create_products_with_pr_and_default_currency(catalog_category, actors):
    _, category = catalog_category
    business, _, owner, manager, _, _ = actors
    first = create_product(api(owner), business, category)
    second = create_product(api(manager), business, category, name="Manager product")
    assert first["public_id"].startswith("PR") and len(first["public_id"]) == 12
    assert first["currency"] == "USD"
    assert second["public_id"] != first["public_id"]


def test_employee_cannot_create_but_can_read(catalog_category, actors):
    _, category = catalog_category
    business, _, owner, _, employee, _ = actors
    created = create_product(api(owner), business, category)
    assert api(employee).post(f"/api/v1/businesses/{business.public_id}/products/", payload(category), format="json").status_code == 403
    assert api(employee).get(f"/api/v1/businesses/{business.public_id}/products/{created['public_id']}/").status_code == 200


def test_category_and_dynamic_attributes_are_validated(catalog_category, actors):
    root, category = catalog_category
    business, _, owner, _, _, _ = actors
    client = api(owner)
    url = f"/api/v1/businesses/{business.public_id}/products/"
    assert client.post(url, payload(root), format="json").status_code == 400
    assert client.post(url, payload(category, attributes={"unknown": "x"}), format="json").status_code == 400
    assert client.post(url, payload(category, attributes={}), format="json").status_code == 400
    assert client.post(url, payload(category, attributes={"brand": 7}), format="json").status_code == 400
    assert client.post(url, payload(category, attributes={"brand": "Nike", "size": "42"}), format="json").status_code == 400


def test_product_price_sku_and_tenant_isolation(catalog_category, actors):
    _, category = catalog_category
    business, other, owner, _, _, outsider = actors
    created = create_product(api(owner), business, category, internal_reference="SKU-1", cost_price="5.25")
    assert Product.objects.get(public_id=created["public_id"]).selling_price == Decimal("10.50")
    assert api(owner).post(f"/api/v1/businesses/{business.public_id}/products/", payload(category, internal_reference="SKU-1"), format="json").status_code == 400
    assert create_product(api(owner), other, category, internal_reference="SKU-1")["internal_reference"] == "SKU-1"
    detail = f"/api/v1/businesses/{other.public_id}/products/{created['public_id']}/"
    assert api(owner).get(detail).status_code == 404
    assert api(outsider).get(f"/api/v1/businesses/{business.public_id}/products/").status_code == 404


def test_patch_revalidates_category_and_attributes(catalog_category, actors):
    _, category = catalog_category
    business, _, owner, _, _, _ = actors
    product = create_product(api(owner), business, category)
    url = f"/api/v1/businesses/{business.public_id}/products/{product['public_id']}/"
    assert api(owner).patch(url, {"attributes": {"brand": 9}}, format="json").status_code == 400
    assert api(owner).patch(url, {"selling_price": "-1.00"}, format="json").status_code == 400
    updated = api(owner).patch(url, {"name": "Updated"}, format="json")
    assert updated.status_code == 200 and updated.data["public_id"] == product["public_id"]


def test_variants_use_axes_signature_and_effective_prices(catalog_category, actors):
    _, category = catalog_category
    business, _, owner, _, employee, _ = actors
    product = create_product(api(owner), business, category, internal_reference="PRODUCT-SKU")
    endpoint = f"/api/v1/businesses/{business.public_id}/products/{product['public_id']}/variants/"
    created = api(owner).post(endpoint, {"attributes": {"size": "42"}, "internal_reference": "VAR-SKU"}, format="json")
    assert created.status_code == 201, created.data
    assert created.data["public_id"].startswith("PV")
    assert created.data["effective_selling_price"] == "10.50"
    assert api(owner).post(endpoint, {"attributes": {"size": "42"}}, format="json").status_code == 400
    assert api(owner).post(endpoint, {"attributes": {"brand": "Nike"}}, format="json").status_code == 400
    assert api(owner).post(endpoint, {"attributes": {"size": "99"}}, format="json").status_code == 400
    assert api(owner).post(endpoint, {"attributes": {"size": "43"}, "internal_reference": "PRODUCT-SKU"}, format="json").status_code == 400
    detail = endpoint + created.data["public_id"] + "/"
    assert api(employee).patch(detail, {"selling_price": "12.00"}, format="json").status_code == 403
    overridden = api(owner).patch(detail, {"selling_price": "12.00"}, format="json")
    assert overridden.status_code == 200 and overridden.data["effective_selling_price"] == "12.00"


def test_product_archive_and_cross_product_variant_scope(catalog_category, actors):
    _, category = catalog_category
    business, other, owner, _, _, _ = actors
    product = create_product(api(owner), business, category)
    other_product = create_product(api(owner), other, category)
    variants = f"/api/v1/businesses/{business.public_id}/products/{product['public_id']}/variants/"
    variant = api(owner).post(variants, {"attributes": {"size": "42"}}, format="json").data
    foreign_path = f"/api/v1/businesses/{other.public_id}/products/{other_product['public_id']}/variants/{variant['public_id']}/"
    assert api(owner).get(foreign_path).status_code == 404
    sibling = create_product(api(owner), business, category, name="Sibling")
    sibling_path = f"/api/v1/businesses/{business.public_id}/products/{sibling['public_id']}/variants/{variant['public_id']}/"
    assert api(owner).get(sibling_path).status_code == 404
    archive = api(owner).post(f"/api/v1/businesses/{business.public_id}/products/{product['public_id']}/archive/")
    assert archive.status_code == 200 and archive.data["status"] == "ARCHIVED"


def test_all_dynamic_attribute_types_are_checked_and_public_ids_immutable(catalog_category, actors):
    _, category = catalog_category
    business, _, owner, _, _, _ = actors
    root = category.parent
    AttributeDefinition.objects.create(category=root, code="count", name="Count", data_type="integer")
    AttributeDefinition.objects.create(category=root, code="weight", name="Weight", data_type="decimal")
    AttributeDefinition.objects.create(category=root, code="organic", name="Organic", data_type="boolean")
    AttributeDefinition.objects.create(category=root, code="released", name="Released", data_type="date")
    client = api(owner)
    valid = create_product(client, business, category, attributes={
        "brand": "Nike", "count": 2, "weight": "3.50", "organic": True, "released": "2026-10-05",
    })
    product = Product.objects.get(public_id=valid["public_id"])
    assert product.attributes["weight"] == "3.50"
    product.public_id = "PR2222222222"
    with pytest.raises(Exception, match="immuable"):
        product.save()
    invalid = {"brand": "Nike", "count": "2", "weight": "broken", "organic": "true", "released": "tomorrow"}
    assert client.post(f"/api/v1/businesses/{business.public_id}/products/", payload(category, attributes=invalid), format="json").status_code == 400
