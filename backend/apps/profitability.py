"""SQL-backed, compact economic profitability projections."""

from decimal import Decimal

from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.expenses.models import Expense
from apps.sales.models import Sale, SaleLine, SaleReturn, SaleReturnLine


MONEY = DecimalField(max_digits=16, decimal_places=2)
LINE_COST = ExpressionWrapper(
    F("quantity") * F("unit_cost_snapshot"),
    output_field=MONEY,
)
RETURN_LINE_COST = ExpressionWrapper(
    F("quantity") * F("unit_cost_snapshot"),
    output_field=MONEY,
)


def build_profitability_summary(business, start, end):
    """Return independent sale, return and expense economic aggregates."""
    sales = SaleLine.objects.filter(
        sale__business=business,
        sale__status=Sale.Status.COMPLETED,
        sale__completed_at__date__range=(start, end),
    ).aggregate(
        revenue=Coalesce(Sum("line_total"), Decimal("0"), output_field=MONEY),
        cost_of_goods_sold=Coalesce(Sum(LINE_COST), Decimal("0"), output_field=MONEY),
    )
    returns = SaleReturnLine.objects.filter(
        sale_return__business=business,
        sale_return__status=SaleReturn.Status.POSTED,
        sale_return__returned_at__date__range=(start, end),
    ).aggregate(
        revenue=Coalesce(Sum("line_total"), Decimal("0"), output_field=MONEY),
        cost_of_goods_sold=Coalesce(
            Sum(RETURN_LINE_COST),
            Decimal("0"),
            output_field=MONEY,
        ),
    )
    expenses = Expense.objects.filter(
        business=business,
        status=Expense.Status.ACTIVE,
        expense_date__range=(start, end),
    ).aggregate(
        total=Coalesce(Sum("amount"), Decimal("0"), output_field=MONEY)
    )["total"]
    sales_revenue = sales["revenue"]
    returns_revenue = returns["revenue"]
    net_revenue = sales_revenue - returns_revenue
    sales_cogs = sales["cost_of_goods_sold"]
    returns_cogs = returns["cost_of_goods_sold"]
    net_cogs = sales_cogs - returns_cogs
    gross_margin = net_revenue - net_cogs
    return {
        "generated_at": timezone.now(),
        "currency": business.primary_currency,
        "period": {"date_from": start, "date_to": end},
        "revenue": net_revenue,
        "cost_of_goods_sold": net_cogs,
        "sales_revenue": sales_revenue,
        "returns_revenue": returns_revenue,
        "net_revenue": net_revenue,
        "sales_cogs": sales_cogs,
        "returns_cogs": returns_cogs,
        "net_cogs": net_cogs,
        "gross_margin": gross_margin,
        "expenses": expenses,
        "net_result": gross_margin - expenses,
    }
