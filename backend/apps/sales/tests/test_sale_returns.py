from datetime import timedelta
from decimal import Decimal

import pytest
from unittest.mock import patch
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.accounts.models import CarriIdentity
from apps.businesses.models import Business, BusinessMember
from apps.catalog.models import Product, ProductCategory, ProductVariant
from apps.inventory.models import InventoryItem, StockMovement
from apps.inventory.services import apply_stock_movement
from apps.receivables.models import Receivable, ReceivableAdjustment, ReceivablePayment
from apps.sales.models import Customer, Sale, SaleLine, SaleReturn, SaleReturnLine
from apps.sales.services import SaleReturnIdempotencyConflict, create_sale_return, sale_return_fingerprint


pytestmark = pytest.mark.django_db


def context():
    category, _ = ProductCategory.objects.get_or_create(code="RET", defaults={"name": "Returns", "slug": "returns"})
    business = Business.objects.create(name="Returns")
    actor = CarriIdentity.objects.create(carri_subject="returns")
    BusinessMember.objects.create(business=business, identity=actor, role="OWNER")
    product = Product.objects.create(business=business, category=category, name="P", selling_price="10", cost_price="4", currency="CDF", attributes={})
    variant = ProductVariant.objects.create(product=product, attributes={"size": "M"}, selling_price="12", cost_price="5", status="INACTIVE")
    InventoryItem.objects.create(business=business, product=product, quantity=Decimal("7"))
    InventoryItem.objects.create(business=business, variant=variant, quantity=Decimal("3"))
    sale = Sale.objects.create(business=business, currency="CDF", created_by=actor, completed_by=actor, status=Sale.Status.COMPLETED)
    first = SaleLine.objects.create(sale=sale, product=product, quantity=Decimal("5"), unit_price=Decimal("10"), unit_cost_snapshot=Decimal("4"))
    second = SaleLine.objects.create(sale=sale, variant=variant, quantity=Decimal("2"), unit_price=Decimal("12"), unit_cost_snapshot=Decimal("5"))
    return business, actor, product, variant, sale, first, second


def make_return(sale, actor, lines, key="key", reason="r", returned_at=None):
    return create_sale_return(sale=sale, actor=actor, reason=reason, returned_at=returned_at or timezone.now(), lines=lines, idempotency_key=key)


def receivable_context(paid_amount=Decimal("0.00")):
    business, actor, product, _, sale, line, second = context()
    second.delete()
    line.quantity = Decimal("10.000")
    line.save(update_fields=("quantity", "line_total", "updated_at"))
    customer = Customer.objects.create(
        business=business,
        name="Return customer",
    )
    sale.customer = customer
    sale.save(update_fields=("customer", "updated_at"))
    receivable = Receivable.objects.create(
        business=business,
        sale=sale,
        customer=customer,
        currency=sale.currency,
        original_amount=Decimal("100.00"),
        status=(
            Receivable.Status.PARTIALLY_PAID
            if paid_amount
            else Receivable.Status.OPEN
        ),
    )
    payment = None
    if paid_amount:
        payment = ReceivablePayment.objects.create(
            business=business,
            receivable=receivable,
            amount=paid_amount,
            payment_method="CASH",
            received_by=actor,
        )
    return actor, product, sale, line, receivable, payment


def test_return_quantities_snapshots_totals_and_catalog_changes():
    _, actor, product, variant, sale, first, second = context()
    returned_at = timezone.now()
    product.selling_price, product.cost_price = Decimal("99"), Decimal("88")
    product.save(update_fields=("selling_price", "cost_price"))
    variant.selling_price, variant.cost_price = Decimal("77"), Decimal("66")
    variant.save(update_fields=("selling_price", "cost_price"))
    result = make_return(sale, actor, [{"sale_line_public_id": first.public_id, "quantity": "2"}, {"sale_line_public_id": second.public_id, "quantity": "1"}], returned_at=returned_at)
    rows = list(result.lines.order_by("sale_line__public_id"))
    assert {row.sale_line_id: (row.unit_price_snapshot, row.unit_cost_snapshot, row.line_total) for row in rows} == {first.id: (Decimal("10"), Decimal("4"), Decimal("20")), second.id: (Decimal("12"), Decimal("5"), Decimal("12"))}
    assert sum(row.line_total for row in rows) == Decimal("32")
    assert InventoryItem.objects.get(product=product).quantity == Decimal("9")
    assert InventoryItem.objects.get(variant=variant).quantity == Decimal("4")
    movements = StockMovement.objects.filter(movement_type=StockMovement.Type.RETURN)
    assert movements.count() == 2
    assert {movement.reference_type for movement in movements} == {"SALE_RETURN_LINE"}
    assert {movement.reference_id for movement in movements} == {row.public_id for row in rows}
    assert Sale.objects.get(pk=sale.pk).status == Sale.Status.COMPLETED
    make_return(sale, actor, [{"sale_line_public_id": first.public_id, "quantity": "3"}], key="second")
    with pytest.raises(ValidationError): make_return(sale, actor, [{"sale_line_public_id": first.public_id, "quantity": "0.001"}], key="third")


def test_return_rejections_and_idempotency():
    _, actor, _, _, sale, first, second = context()
    for quantity in ("0", "-1", "6"):
        with pytest.raises(ValidationError): make_return(sale, actor, [{"sale_line_public_id": first.public_id, "quantity": quantity}], key=f"bad-{quantity}")
    other = Sale.objects.create(business=sale.business, currency="CDF", created_by=actor, status=Sale.Status.COMPLETED)
    foreign = SaleLine.objects.create(sale=other, product=first.product, quantity=Decimal("1"), unit_price=Decimal("10"))
    with pytest.raises(ValidationError): make_return(sale, actor, [{"sale_line_public_id": foreign.public_id, "quantity": "1"}], key="foreign")
    stamp = timezone.now()
    lines = [{"sale_line_public_id": first.public_id, "quantity": "1"}, {"sale_line_public_id": second.public_id, "quantity": "1"}]
    one = make_return(sale, actor, lines, key="retry", returned_at=stamp)
    retry = make_return(sale, actor, list(reversed(lines)), key="retry", returned_at=stamp)
    assert one.pk == retry.pk and SaleReturnLine.objects.filter(sale_return=one).count() == 2
    with pytest.raises(SaleReturnIdempotencyConflict): make_return(sale, actor, [{"sale_line_public_id": first.public_id, "quantity": "2"}], key="retry", returned_at=stamp)
    sale.status = Sale.Status.DRAFT; sale.save(update_fields=("status",))
    with pytest.raises(ValidationError): make_return(sale, actor, [{"sale_line_public_id": first.public_id, "quantity": "1"}], key="draft")


def test_fingerprint_canonicalizes_decimal_quantities():
    _, _, _, _, sale, first, second = context()
    stamp = timezone.now()
    def fingerprint(quantity):
        return sale_return_fingerprint(sale=sale, reason="r", returned_at=stamp, lines=[(first.public_id, quantity), (second.public_id, Decimal("1"))])
    assert len({fingerprint(value) for value in (1, 1.0, 1.000, Decimal("1"), Decimal("1.000"))}) == 1
    assert len({fingerprint(value) for value in (1.25, 1.250, Decimal("1.25"), Decimal("1.250"))}) == 1
    assert fingerprint(Decimal("1.25")) != fingerprint(Decimal("1.26"))


def test_successive_returns_and_idempotent_retry_do_not_duplicate_inventory():
    _, actor, product, _, sale, first, _ = context()
    first_return = make_return(sale, actor, [{"sale_line_public_id": first.public_id, "quantity": "2"}], key="one")
    stamp = timezone.now()
    second_return = make_return(sale, actor, [{"sale_line_public_id": first.public_id, "quantity": "1"}], key="two", returned_at=stamp)
    before_retry = InventoryItem.objects.get(product=product).quantity
    retry = make_return(sale, actor, [{"sale_line_public_id": first.public_id, "quantity": "1.000"}], key="two", returned_at=stamp)
    assert retry.pk == second_return.pk
    assert InventoryItem.objects.get(product=product).quantity == before_retry == Decimal("10")
    assert StockMovement.objects.filter(movement_type="RETURN", inventory_item__product=product).count() == 2
    assert first_return.pk != second_return.pk


def test_archived_targets_return_and_normal_mutation_stays_forbidden():
    _, actor, product, variant, sale, first, second = context()
    variant.status = "INACTIVE"; variant.save(update_fields=("status",))
    product.status = "ARCHIVED"; product.save(update_fields=("status",))
    returned_product = make_return(sale, actor, [{"sale_line_public_id": first.public_id, "quantity": "1"}], key="archived-product")
    assert product.status == "ARCHIVED" and returned_product.lines.count() == 1
    with pytest.raises(ValidationError):
        apply_stock_movement(inventory_item=InventoryItem.objects.get(product=product), movement_type="IN", performed_by=actor, quantity=Decimal("1"))
    product.status = "ACTIVE"; product.save(update_fields=("status",))
    variant.status = "ARCHIVED"; variant.save(update_fields=("status",))
    returned_variant = make_return(sale, actor, [{"sale_line_public_id": second.public_id, "quantity": "1"}], key="archived-variant")
    assert variant.status == "ARCHIVED" and returned_variant.lines.count() == 1


def test_inventory_failure_rolls_back_return_and_stock():
    _, actor, product, _, sale, first, _ = context()
    before = InventoryItem.objects.get(product=product).quantity
    with patch("apps.sales.services.apply_stock_movement", side_effect=RuntimeError("inventory unavailable")):
        with pytest.raises(RuntimeError):
            make_return(sale, actor, [{"sale_line_public_id": first.public_id, "quantity": "1"}], key="rollback")
    assert not SaleReturn.objects.filter(idempotency_key="rollback").exists()
    assert not SaleReturnLine.objects.filter(sale_line=first).exists()
    assert InventoryItem.objects.get(product=product).quantity == before
    assert not StockMovement.objects.filter(movement_type="RETURN", inventory_item__product=product).exists()


def test_unpaid_sale_return_credits_receivable():
    actor, _, sale, line, receivable, _ = receivable_context()

    sale_return = make_return(
        sale,
        actor,
        [{"sale_line_public_id": line.public_id, "quantity": "3"}],
        key="unpaid-credit",
    )

    adjustment = ReceivableAdjustment.objects.get(sale_return=sale_return)
    receivable.refresh_from_db()
    assert sale_return.receivable_credit_amount == Decimal("30.00")
    assert sale_return.refund_amount == Decimal("0.00")
    assert adjustment.adjustment_type == ReceivableAdjustment.Type.RETURN_CREDIT
    assert adjustment.amount == Decimal("30.00")
    assert receivable.balance == Decimal("70.00")
    assert receivable.status == Receivable.Status.OPEN
    assert receivable.original_amount == Decimal("100.00")


def test_partially_paid_sale_return_credits_remaining_receivable():
    actor, _, sale, line, receivable, payment = receivable_context(Decimal("40.00"))
    payment_values = (payment.pk, payment.amount, payment.payment_method, payment.paid_at)

    sale_return = make_return(
        sale,
        actor,
        [{"sale_line_public_id": line.public_id, "quantity": "3"}],
        key="partial-credit",
    )

    receivable.refresh_from_db()
    payment.refresh_from_db()
    assert sale_return.receivable_credit_amount == Decimal("30.00")
    assert receivable.balance == Decimal("30.00")
    assert receivable.status == Receivable.Status.PARTIALLY_PAID
    assert receivable.original_amount == Decimal("100.00")
    assert ReceivablePayment.objects.filter(receivable=receivable).count() == 1
    assert (payment.pk, payment.amount, payment.payment_method, payment.paid_at) == payment_values


def test_receivable_credit_is_capped_at_outstanding_balance():
    actor, _, sale, line, receivable, payment = receivable_context(Decimal("40.00"))

    sale_return = make_return(
        sale,
        actor,
        [{"sale_line_public_id": line.public_id, "quantity": "7"}],
        key="capped-credit",
    )

    receivable.refresh_from_db()
    assert sale_return.receivable_credit_amount == Decimal("60.00")
    assert sale_return.refund_amount == Decimal("0.00")
    assert receivable.balance == Decimal("0.00")
    assert receivable.status == Receivable.Status.PAID
    assert receivable.settled_at is not None
    assert receivable.original_amount == Decimal("100.00")
    assert ReceivablePayment.objects.get(pk=payment.pk).amount == Decimal("40.00")


def test_fully_paid_sale_without_receivable_creates_no_adjustment():
    _, actor, _, _, sale, line, _ = context()

    sale_return = make_return(
        sale,
        actor,
        [{"sale_line_public_id": line.public_id, "quantity": "3"}],
        key="fully-paid",
    )

    assert sale_return.receivable_credit_amount == Decimal("0.00")
    assert sale_return.refund_amount == Decimal("0.00")
    assert not ReceivableAdjustment.objects.filter(sale_return=sale_return).exists()


def test_receivable_credit_is_idempotent_and_uses_remaining_balance():
    actor, _, sale, line, receivable, _ = receivable_context(Decimal("40.00"))
    stamp = timezone.now()
    first = make_return(
        sale,
        actor,
        [{"sale_line_public_id": line.public_id, "quantity": "3"}],
        key="credit-one",
        returned_at=stamp,
    )
    retry = make_return(
        sale,
        actor,
        [{"sale_line_public_id": line.public_id, "quantity": "3.000"}],
        key="credit-one",
        returned_at=stamp,
    )
    second = make_return(
        sale,
        actor,
        [{"sale_line_public_id": line.public_id, "quantity": "5"}],
        key="credit-two",
    )

    receivable.refresh_from_db()
    assert retry.pk == first.pk
    assert first.receivable_credit_amount == Decimal("30.00")
    assert second.receivable_credit_amount == Decimal("30.00")
    assert ReceivableAdjustment.objects.filter(receivable=receivable).count() == 2
    assert receivable.balance == Decimal("0.00")


def test_receivable_failure_rolls_back_return_and_inventory():
    actor, product, sale, line, receivable, _ = receivable_context()
    stock_before = InventoryItem.objects.get(product=product).quantity

    with patch(
        "apps.receivables.models.ReceivableAdjustment.objects.create",
        side_effect=RuntimeError("receivables unavailable"),
    ):
        with pytest.raises(RuntimeError, match="receivables unavailable"):
            make_return(
                sale,
                actor,
                [{"sale_line_public_id": line.public_id, "quantity": "3"}],
                key="receivable-rollback",
            )

    receivable.refresh_from_db()
    assert not SaleReturn.objects.filter(idempotency_key="receivable-rollback").exists()
    assert not SaleReturnLine.objects.filter(sale_line=line).exists()
    assert not ReceivableAdjustment.objects.filter(receivable=receivable).exists()
    assert InventoryItem.objects.get(product=product).quantity == stock_before
    assert not StockMovement.objects.filter(
        movement_type=StockMovement.Type.RETURN,
        inventory_item__product=product,
    ).exists()
    assert receivable.balance == Decimal("100.00")
