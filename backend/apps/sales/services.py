import hashlib
import json
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.businesses.models import BusinessPaymentMethod
from apps.common.choices import PaymentMethod
from apps.finance.models import FinancialMovement
from apps.finance.services import create_financial_movement
from apps.inventory.models import InventoryItem, StockMovement
from apps.inventory.services import apply_stock_movement, validate_inventory_target

from .models import Sale, SaleLine, SaleReturn, SaleReturnLine


class SaleReturnIdempotencyConflict(ValidationError):
    """Raised when a return key is reused with another business intent."""


def sale_return_fingerprint(*, sale, reason, returned_at, lines, refund_payment_method=None):
    """Hash normalized return intent independently from client line ordering."""
    def canonical_quantity(value):
        quantity = Decimal(str(value))
        return format(quantity.normalize(), "f")

    payload = {
        "sale": sale.public_id,
        "reason": reason or "",
        "returned_at": returned_at.isoformat(),
        "refund_payment_method": (
            refund_payment_method.public_id if refund_payment_method else None
        ),
        "lines": sorted(
            ({"sale_line": line_id, "quantity": canonical_quantity(quantity)} for line_id, quantity in lines),
            key=lambda value: value["sale_line"],
        ),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def create_sale_return(
    *,
    sale,
    actor,
    reason,
    returned_at,
    lines,
    idempotency_key,
    refund_payment_method=None,
):
    """Append immutable return lines from locked sale snapshots in one transaction."""
    if not idempotency_key:
        raise ValidationError("Idempotency-Key is required.")
    if not lines:
        raise ValidationError("At least one return line is required.")
    normalized = [(str(line["sale_line_public_id"]), Decimal(str(line["quantity"]))) for line in lines]
    if any(quantity <= 0 for _, quantity in normalized):
        raise ValidationError("Return quantities must be positive.")
    if len({line_id for line_id, _ in normalized}) != len(normalized):
        raise ValidationError("A sale line may appear only once per return.")
    with transaction.atomic():
        locked_sale = Sale.objects.select_for_update().get(pk=sale.pk)
        fingerprint = sale_return_fingerprint(
            sale=locked_sale,
            reason=reason,
            returned_at=returned_at,
            lines=normalized,
            refund_payment_method=refund_payment_method,
        )
        existing = SaleReturn.objects.select_for_update().filter(business=locked_sale.business, idempotency_key=idempotency_key).first()
        if existing:
            if existing.idempotency_fingerprint != fingerprint:
                raise SaleReturnIdempotencyConflict("Idempotency key conflicts with a different return.")
            return existing
        if locked_sale.status != Sale.Status.COMPLETED:
            raise ValidationError("Only completed sales can be returned.")
        locked_lines = {line.public_id: line for line in SaleLine.objects.select_for_update().filter(sale=locked_sale, public_id__in=[line_id for line_id, _ in normalized])}
        if len(locked_lines) != len(normalized):
            raise ValidationError("Return line does not belong to this sale.")
        returned = {}
        for line in SaleReturnLine.objects.select_for_update().filter(sale_line__in=locked_lines.values(), sale_return__status=SaleReturn.Status.POSTED):
            returned[line.sale_line_id] = returned.get(line.sale_line_id, Decimal("0.000")) + line.quantity
        for line_id, quantity in normalized:
            line = locked_lines[line_id]
            if returned.get(line.pk, Decimal("0.000")) + quantity > line.quantity:
                raise ValidationError("Return quantity exceeds sold quantity.")

        from apps.receivables.models import Receivable, ReceivableAdjustment

        return_total = sum(
            (
                (locked_lines[line_id].unit_price * quantity).quantize(
                    Decimal("0.01")
                )
                for line_id, quantity in normalized
            ),
            Decimal("0.00"),
        )
        receivable = (
            Receivable.objects.select_for_update()
            .filter(sale=locked_sale)
            .first()
        )
        receivable_credit_amount = (
            min(return_total, receivable.balance)
            if receivable is not None
            else Decimal("0.00")
        )
        collected_amount = (
            FinancialMovement.objects.filter(
                sale=locked_sale,
                event_type=FinancialMovement.EventType.SALE_PAYMENT,
                direction=FinancialMovement.Direction.INFLOW,
            ).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        if receivable is not None:
            collected_amount += (
                FinancialMovement.objects.filter(
                    receivable_payment__receivable=receivable,
                    event_type=FinancialMovement.EventType.RECEIVABLE_PAYMENT,
                    direction=FinancialMovement.Direction.INFLOW,
                ).aggregate(total=Sum("amount"))["total"]
                or Decimal("0.00")
            )
        already_refunded_amount = (
            FinancialMovement.objects.filter(
                sale_return__sale=locked_sale,
                event_type=FinancialMovement.EventType.SALE_RETURN_REFUND,
                direction=FinancialMovement.Direction.OUTFLOW,
            ).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        refundable_collected_amount = max(
            collected_amount - already_refunded_amount,
            Decimal("0.00"),
        )
        refund_amount = min(
            return_total - receivable_credit_amount,
            refundable_collected_amount,
        )
        locked_refund_payment_method = None
        if refund_amount > 0:
            if refund_payment_method is None:
                raise ValidationError("An active refund payment method is required.")
            locked_refund_payment_method = (
                BusinessPaymentMethod.objects.select_for_update()
                .filter(
                    pk=refund_payment_method.pk,
                    business=locked_sale.business,
                    is_active=True,
                )
                .first()
            )
            if locked_refund_payment_method is None:
                raise ValidationError("Invalid refund payment method.")
        sale_return = SaleReturn.objects.create(
            business=locked_sale.business,
            sale=locked_sale,
            customer=locked_sale.customer,
            reason=reason or "",
            returned_at=returned_at,
            created_by=actor,
            idempotency_key=idempotency_key,
            idempotency_fingerprint=fingerprint,
            receivable_credit_amount=receivable_credit_amount,
            refund_amount=refund_amount,
            refund_payment_method=locked_refund_payment_method,
        )
        for line_id, quantity in normalized:
            line = locked_lines[line_id]
            return_line = SaleReturnLine.objects.create(sale_return=sale_return, sale_line=line, quantity=quantity, unit_price_snapshot=line.unit_price, unit_cost_snapshot=line.unit_cost_snapshot, line_total=(quantity * line.unit_price).quantize(Decimal("0.01")))
            inventory_item = InventoryItem.objects.select_for_update().get(product=line.product) if line.product_id else InventoryItem.objects.select_for_update().get(variant=line.variant)
            apply_stock_movement(inventory_item=inventory_item, movement_type=StockMovement.Type.RETURN, performed_by=actor, quantity=quantity, reference_type="SALE_RETURN_LINE", reference_id=return_line.public_id, allow_archived_target=True)

        if receivable_credit_amount > 0:
            ReceivableAdjustment.objects.create(
                business=locked_sale.business,
                receivable=receivable,
                sale_return=sale_return,
                adjustment_type=ReceivableAdjustment.Type.RETURN_CREDIT,
                amount=receivable_credit_amount,
                created_by=actor,
            )
            if receivable.balance == 0:
                receivable.status = Receivable.Status.PAID
                receivable.settled_at = timezone.now()
            elif receivable.paid_amount > 0:
                receivable.status = Receivable.Status.PARTIALLY_PAID
                receivable.settled_at = None
            else:
                receivable.status = Receivable.Status.OPEN
                receivable.settled_at = None
            receivable.save(update_fields=("status", "settled_at", "updated_at"))
        if refund_amount > 0:
            create_financial_movement(
                business=locked_sale.business,
                direction=FinancialMovement.Direction.OUTFLOW,
                amount=refund_amount,
                payment_method=locked_refund_payment_method.category,
                business_payment_method=locked_refund_payment_method,
                event_type=FinancialMovement.EventType.SALE_RETURN_REFUND,
                created_by=actor,
                sale_return=sale_return,
                occurred_at=returned_at,
                idempotency_key=f"sale-return-refund:{sale_return.public_id}",
            )
        return sale_return


def target(sale, product=None, variant=None):
    if bool(product) == bool(variant):
        raise ValidationError("Choose one target")
    validate_inventory_target(business=sale.business, product=product, variant=variant)


def complete(sale, actor, amount_paid, payment_method=None):
    """Finalize a sale, stock mutation and real collection as one transaction.

    A fully-paid sale writes one ``SALE_PAYMENT``. A partial payment first
    creates a receivable payment and therefore writes only its corresponding
    ``RECEIVABLE_PAYMENT``. A credit sale writes no Finance event.
    """
    if amount_paid is None:
        raise ValidationError("amount_paid is required.")
    if amount_paid > 0 and payment_method not in PaymentMethod.values:
        raise ValidationError("payment_method is required for a payment.")
    if amount_paid == 0 and payment_method is not None:
        raise ValidationError("payment_method must be absent for a credit sale.")

    with transaction.atomic():
        locked_sale = Sale.objects.select_for_update().get(pk=sale.pk)
        if locked_sale.status != Sale.Status.DRAFT or not locked_sale.lines.exists():
            raise ValidationError("Only non-empty drafts complete.")

        total = locked_sale.total
        if amount_paid < 0 or amount_paid > total:
            raise ValidationError("Invalid paid amount.")
        if amount_paid < total and not locked_sale.customer_id:
            raise ValidationError("Customer is required for credit.")

        lines = list(
            locked_sale.lines.select_related("product", "variant__product").order_by("public_id")
        )
        snapshots = {}

        for line in lines:
            unit_cost_snapshot = (
                line.variant.effective_cost_price if line.variant else line.product.cost_price
            )
            if unit_cost_snapshot is None:
                raise ValidationError(
                    "A historical unit cost is required before completing a sale."
                )
            snapshots[line.pk] = unit_cost_snapshot

        for line in lines:
            target(locked_sale, line.product, line.variant)
            inventory_item = (
                InventoryItem.objects.filter(product=line.product).first()
                if line.product
                else InventoryItem.objects.filter(variant=line.variant).first()
            )
            if not inventory_item:
                raise ValidationError("Inventory item missing.")
            line.unit_cost_snapshot = snapshots[line.pk]
            line.save(update_fields=("unit_cost_snapshot", "updated_at"))
            apply_stock_movement(
                inventory_item=inventory_item,
                movement_type=StockMovement.Type.SALE,
                performed_by=actor,
                quantity=line.quantity,
                reference_type="SALE",
                reference_id=line.public_id,
                reason=f"Sale {locked_sale.public_id}",
            )

        completed_at = timezone.now()
        locked_sale.status = Sale.Status.COMPLETED
        locked_sale.completed_at = completed_at
        locked_sale.completed_by = actor
        locked_sale.save(update_fields=("status", "completed_at", "completed_by", "updated_at"))

        if amount_paid == total:
            create_financial_movement(
                business=locked_sale.business,
                direction=FinancialMovement.Direction.INFLOW,
                amount=total,
                payment_method=payment_method,
                event_type=FinancialMovement.EventType.SALE_PAYMENT,
                created_by=actor,
                sale=locked_sale,
                occurred_at=completed_at,
            )
        elif amount_paid < total:
            from apps.receivables.models import Receivable
            from apps.receivables.services import add_payment

            receivable = Receivable.objects.create(
                business=locked_sale.business,
                sale=locked_sale,
                customer=locked_sale.customer,
                currency=locked_sale.currency,
                original_amount=total,
                status=Receivable.Status.OPEN,
            )
            if amount_paid > 0:
                add_payment(
                    receivable,
                    actor,
                    amount_paid,
                    payment_method,
                )
        return locked_sale


def cancel(sale, actor):
    with transaction.atomic():
        locked_sale = Sale.objects.select_for_update().get(pk=sale.pk)
        if locked_sale.status != Sale.Status.DRAFT:
            raise ValidationError("Only drafts cancel.")
        locked_sale.status = Sale.Status.CANCELLED
        locked_sale.cancelled_at = timezone.now()
        locked_sale.cancelled_by = actor
        locked_sale.save(
            update_fields=("status", "cancelled_at", "cancelled_by", "updated_at")
        )
        return locked_sale
