from datetime import timedelta
from decimal import Decimal

import pytest
from unittest.mock import patch
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.utils import timezone

from apps.accounts.models import CarriIdentity
from apps.businesses.models import Business, BusinessMember, BusinessPaymentMethod
from apps.catalog.models import Product, ProductCategory, ProductVariant
from apps.finance.models import FinancialMovement
from apps.finance.services import create_financial_movement
from apps.inventory.models import InventoryItem, StockMovement
from apps.inventory.services import apply_stock_movement
from apps.receivables.models import Receivable, ReceivableAdjustment, ReceivablePayment
from apps.receivables.services import add_payment
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


def make_return(
    sale,
    actor,
    lines,
    key="key",
    reason="r",
    returned_at=None,
    refund_payment_method=None,
):
    return create_sale_return(
        sale=sale,
        actor=actor,
        reason=reason,
        returned_at=returned_at or timezone.now(),
        lines=lines,
        idempotency_key=key,
        refund_payment_method=refund_payment_method,
    )


def hundred_sale_context():
    business, actor, product, _, sale, line, second = context()
    second.delete()
    line.quantity = Decimal("10.000")
    line.save(update_fields=("quantity", "line_total", "updated_at"))
    return business, actor, product, sale, line


def receivable_context(paid_amount=Decimal("0.00")):
    business, actor, product, sale, line = hundred_sale_context()
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
        payment = add_payment(
            receivable,
            actor,
            paid_amount,
            "CASH",
        )
    return actor, product, sale, line, receivable, payment


def cash_method(business):
    return BusinessPaymentMethod.objects.get(
        business=business,
        category="CASH",
        is_active=True,
    )


def record_direct_collection(sale, actor, amount=Decimal("100.00")):
    movement = create_financial_movement(
        business=sale.business,
        direction=FinancialMovement.Direction.INFLOW,
        amount=amount,
        payment_method="CASH",
        event_type=FinancialMovement.EventType.SALE_PAYMENT,
        created_by=actor,
        sale=sale,
    )
    return movement.payment_transaction.business_payment_method


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
    assert not FinancialMovement.objects.filter(
        event_type=FinancialMovement.EventType.SALE_RETURN_REFUND,
        sale_return=sale_return,
    ).exists()


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
    assert sale_return.refund_amount == Decimal("0.00")
    assert not FinancialMovement.objects.filter(
        event_type=FinancialMovement.EventType.SALE_RETURN_REFUND,
        sale_return=sale_return,
    ).exists()


def test_receivable_credit_is_capped_at_outstanding_balance():
    actor, _, sale, line, receivable, payment = receivable_context(Decimal("40.00"))
    refund_method = cash_method(sale.business)

    sale_return = make_return(
        sale,
        actor,
        [{"sale_line_public_id": line.public_id, "quantity": "7"}],
        key="capped-credit",
        refund_payment_method=refund_method,
    )

    receivable.refresh_from_db()
    assert sale_return.receivable_credit_amount == Decimal("60.00")
    assert sale_return.refund_amount == Decimal("10.00")
    assert receivable.balance == Decimal("0.00")
    assert receivable.status == Receivable.Status.PAID
    assert receivable.settled_at is not None
    assert receivable.original_amount == Decimal("100.00")
    assert ReceivablePayment.objects.get(pk=payment.pk).amount == Decimal("40.00")
    refund = FinancialMovement.objects.get(sale_return=sale_return)
    assert refund.direction == FinancialMovement.Direction.OUTFLOW
    assert refund.amount == Decimal("10.00")


def test_fully_paid_sale_without_receivable_creates_no_adjustment():
    _, actor, _, sale, line = hundred_sale_context()
    refund_method = record_direct_collection(sale, actor)
    stamp = timezone.now()

    sale_return = make_return(
        sale,
        actor,
        [{"sale_line_public_id": line.public_id, "quantity": "3"}],
        key="fully-paid",
        returned_at=stamp,
        refund_payment_method=refund_method,
    )
    retry = make_return(
        sale,
        actor,
        [{"sale_line_public_id": line.public_id, "quantity": "3.000"}],
        key="fully-paid",
        returned_at=stamp,
        refund_payment_method=refund_method,
    )

    assert retry.pk == sale_return.pk
    assert sale_return.receivable_credit_amount == Decimal("0.00")
    assert sale_return.refund_amount == Decimal("30.00")
    assert not ReceivableAdjustment.objects.filter(sale_return=sale_return).exists()
    refund = FinancialMovement.objects.get(sale_return=sale_return)
    assert refund.direction == FinancialMovement.Direction.OUTFLOW
    assert refund.amount == Decimal("30.00")
    assert refund.payment_transaction.business_payment_method == refund_method
    assert FinancialMovement.objects.filter(
        event_type=FinancialMovement.EventType.SALE_RETURN_REFUND,
        sale_return=sale_return,
    ).count() == 1


def test_receivable_credit_is_idempotent_and_uses_remaining_balance():
    actor, _, sale, line, receivable, _ = receivable_context(Decimal("40.00"))
    refund_method = cash_method(sale.business)
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
        refund_payment_method=refund_method,
    )

    receivable.refresh_from_db()
    assert retry.pk == first.pk
    assert first.receivable_credit_amount == Decimal("30.00")
    assert second.receivable_credit_amount == Decimal("30.00")
    assert second.refund_amount == Decimal("20.00")
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


def test_refund_requires_active_payment_method_from_same_business():
    business, actor, product, sale, line = hundred_sale_context()
    record_direct_collection(sale, actor)
    inactive = BusinessPaymentMethod.objects.create(
        business=business,
        name="Inactive refund",
        category="CASH",
        is_active=False,
    )
    other_business = Business.objects.create(name="Other refund business")
    foreign = BusinessPaymentMethod.objects.create(
        business=other_business,
        name="Foreign refund",
        category="CASH",
    )
    stock_before = InventoryItem.objects.get(product=product).quantity

    for key, method in (
        ("missing-refund-method", None),
        ("inactive-refund-method", inactive),
        ("foreign-refund-method", foreign),
    ):
        with pytest.raises(ValidationError):
            make_return(
                sale,
                actor,
                [{"sale_line_public_id": line.public_id, "quantity": "3"}],
                key=key,
                refund_payment_method=method,
            )

    assert not SaleReturn.objects.filter(sale=sale).exists()
    assert InventoryItem.objects.get(product=product).quantity == stock_before
    assert not FinancialMovement.objects.filter(
        event_type=FinancialMovement.EventType.SALE_RETURN_REFUND,
        sale_return__sale=sale,
    ).exists()


def test_successive_refunds_never_exceed_collected_amount():
    _, actor, _, sale, line = hundred_sale_context()
    refund_method = record_direct_collection(sale, actor)

    first = make_return(
        sale,
        actor,
        [{"sale_line_public_id": line.public_id, "quantity": "7"}],
        key="refund-one",
        refund_payment_method=refund_method,
    )
    second = make_return(
        sale,
        actor,
        [{"sale_line_public_id": line.public_id, "quantity": "3"}],
        key="refund-two",
        refund_payment_method=refund_method,
    )

    refunds = FinancialMovement.objects.filter(
        event_type=FinancialMovement.EventType.SALE_RETURN_REFUND,
        sale_return__sale=sale,
    )
    assert first.refund_amount == Decimal("70.00")
    assert second.refund_amount == Decimal("30.00")
    assert refunds.count() == 2
    assert refunds.aggregate(total=Sum("amount"))["total"] == Decimal("100.00")


def test_finance_failure_rolls_back_return_inventory_and_receivable_credit():
    actor, product, sale, line, receivable, _ = receivable_context(Decimal("40.00"))
    refund_method = cash_method(sale.business)
    stock_before = InventoryItem.objects.get(product=product).quantity

    with patch(
        "apps.sales.services.create_financial_movement",
        side_effect=RuntimeError("finance unavailable"),
    ):
        with pytest.raises(RuntimeError, match="finance unavailable"):
            make_return(
                sale,
                actor,
                [{"sale_line_public_id": line.public_id, "quantity": "7"}],
                key="finance-rollback",
                refund_payment_method=refund_method,
            )

    receivable.refresh_from_db()
    assert not SaleReturn.objects.filter(idempotency_key="finance-rollback").exists()
    assert not SaleReturnLine.objects.filter(sale_line=line).exists()
    assert not ReceivableAdjustment.objects.filter(receivable=receivable).exists()
    assert InventoryItem.objects.get(product=product).quantity == stock_before
    assert not StockMovement.objects.filter(
        movement_type=StockMovement.Type.RETURN,
        inventory_item__product=product,
    ).exists()
    assert not FinancialMovement.objects.filter(
        event_type=FinancialMovement.EventType.SALE_RETURN_REFUND,
        sale_return__sale=sale,
    ).exists()
    assert receivable.balance == Decimal("60.00")
