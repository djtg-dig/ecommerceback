"""SQL-backed, compact economic profitability projections."""

from decimal import Decimal

from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.expenses.models import Expense
from apps.sales.models import SaleLine


MONEY = DecimalField(max_digits=16, decimal_places=2)
LINE_COST = ExpressionWrapper(F("quantity") * F("unit_cost_snapshot"), output_field=MONEY)


def build_profitability_summary(business, start, end):
    """Return economic aggregates without payment, ledger, or purchase balances."""
    sales = SaleLine.objects.filter(
        sale__business=business,
        sale__status="COMPLETED",
        sale__completed_at__date__range=(start, end),
    ).aggregate(
        revenue=Coalesce(Sum("line_total"), Decimal("0"), output_field=MONEY),
        cost_of_goods_sold=Coalesce(Sum(LINE_COST), Decimal("0"), output_field=MONEY),
    )
    expenses = Expense.objects.filter(
        business=business,
        status=Expense.Status.ACTIVE,
        expense_date__range=(start, end),
    ).aggregate(total=Coalesce(Sum("amount"), Decimal("0"), output_field=MONEY))["total"]
    revenue = sales["revenue"]
    cogs = sales["cost_of_goods_sold"]
    gross_margin = revenue - cogs
    return {"generated_at": timezone.now(), "currency": business.primary_currency, "period": {"date_from": start, "date_to": end}, "revenue": revenue, "cost_of_goods_sold": cogs, "gross_margin": gross_margin, "expenses": expenses, "net_result": gross_margin - expenses}
