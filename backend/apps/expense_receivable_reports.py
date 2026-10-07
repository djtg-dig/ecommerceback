"""SQL-backed compact projections for expenses and customer receivables."""

from decimal import Decimal

from django.db.models import Count, DecimalField, F, OuterRef, Subquery, Sum
from django.db.models.functions import Coalesce, TruncDay, TruncMonth, TruncWeek
from django.utils import timezone

from apps.expenses.models import Expense
from apps.receivables.models import Receivable, ReceivablePayment


MONEY = DecimalField(max_digits=16, decimal_places=2)
GROUPERS = {"day": TruncDay, "week": TruncWeek, "month": TruncMonth}


def build_expenses_report(business, start, end, group_by):
    expenses = Expense.objects.filter(business=business, status=Expense.Status.ACTIVE, expense_date__range=(start, end))
    total = expenses.aggregate(value=Coalesce(Sum("amount"), Decimal("0"), output_field=MONEY))["value"]
    by_category = expenses.values("category__public_id", "category__name").annotate(amount=Coalesce(Sum("amount"), Decimal("0"), output_field=MONEY)).order_by("-amount", "category__name")
    series = expenses.annotate(bucket=GROUPERS[group_by]("expense_date")).values("bucket").annotate(amount=Coalesce(Sum("amount"), Decimal("0"), output_field=MONEY)).order_by("bucket")
    return {"generated_at": timezone.now(), "currency": business.primary_currency, "period": {"date_from": start, "date_to": end}, "group_by": group_by, "total_expenses": total, "by_category": [{"category_public_id": row["category__public_id"], "name": row["category__name"], "amount": row["amount"]} for row in by_category], "series": [{"period": row["bucket"], "amount": row["amount"]} for row in series]}


def receivable_queryset(business):
    paid = ReceivablePayment.objects.filter(receivable=OuterRef("pk")).values("receivable").annotate(total=Sum("amount")).values("total")
    return Receivable.objects.filter(business=business, status__in=[Receivable.Status.OPEN, Receivable.Status.PARTIALLY_PAID]).annotate(paid=Coalesce(Subquery(paid, output_field=MONEY), Decimal("0"), output_field=MONEY)).annotate(balance=F("original_amount") - F("paid"))


def receivables_summary(queryset):
    return {"total_outstanding": queryset.aggregate(value=Coalesce(Sum("balance"), Decimal("0"), output_field=MONEY))["value"], "open_count": queryset.count(), "overdue_count": queryset.filter(due_date__lt=timezone.localdate()).count()}
