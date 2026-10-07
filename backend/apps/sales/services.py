from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.common.choices import PaymentMethod
from apps.finance.models import FinancialMovement
from apps.finance.services import create_financial_movement
from apps.inventory.models import InventoryItem, StockMovement
from apps.inventory.services import apply_stock_movement, validate_inventory_target

from .models import Sale


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
