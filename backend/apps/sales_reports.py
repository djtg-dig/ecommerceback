"""Compact SQL projections for sales reporting."""

from decimal import Decimal

from django.db.models import CharField, Count, DecimalField, ExpressionWrapper, F, Sum
from django.db.models.functions import Coalesce, TruncDay, TruncMonth, TruncWeek
from django.utils import timezone

from apps.sales.models import SaleLine


MONEY = DecimalField(max_digits=16, decimal_places=2)
LINE_COST = ExpressionWrapper(F("quantity") * F("unit_cost_snapshot"), output_field=MONEY)
GROUPERS = {"day": TruncDay, "week": TruncWeek, "month": TruncMonth}


def completed_lines(business, start, end):
    return SaleLine.objects.filter(
        sale__business=business,
        sale__status="COMPLETED",
        sale__completed_at__date__range=(start, end),
    )


def build_sales_series(business, start, end, group_by):
    """Return pre-aggregated revenue and distinct completed-sale counts."""
    lines = completed_lines(business, start, end)
    totals = lines.aggregate(
        revenue=Coalesce(Sum("line_total"), Decimal("0"), output_field=MONEY),
        sales_count=Count("sale", distinct=True),
    )
    rows = lines.annotate(bucket=GROUPERS[group_by]("sale__completed_at")).values("bucket").annotate(
        revenue=Coalesce(Sum("line_total"), Decimal("0"), output_field=MONEY),
        sales_count=Count("sale", distinct=True),
    ).order_by("bucket")
    return {
        "generated_at": timezone.now(),
        "currency": business.primary_currency,
        "period": {"date_from": start, "date_to": end},
        "group_by": group_by,
        "totals": totals,
        "series": [{"period": row["bucket"].date(), "revenue": row["revenue"], "sales_count": row["sales_count"]} for row in rows],
    }


def build_product_top(business, start, end, limit):
    """Aggregate direct products and variants under their shared product parent."""
    rows = completed_lines(business, start, end).annotate(
        parent_public_id=Coalesce("product__public_id", "variant__product__public_id", output_field=CharField()),
        parent_name=Coalesce("product__name", "variant__product__name", output_field=CharField()),
    ).values("parent_public_id", "parent_name").annotate(
        quantity_sold=Sum("quantity"),
        revenue=Coalesce(Sum("line_total"), Decimal("0"), output_field=MONEY),
        cost_of_goods_sold=Coalesce(Sum(LINE_COST), Decimal("0"), output_field=MONEY),
    ).order_by("-revenue")[:limit]
    rows = [{"product_public_id": row["parent_public_id"], "name": row["parent_name"], **{key: row[key] for key in ("quantity_sold", "revenue", "cost_of_goods_sold")}} for row in rows]
    for row in rows:
        row["gross_margin"] = row["revenue"] - row["cost_of_goods_sold"]
        row["margin_rate"] = row["gross_margin"] * Decimal("100") / row["revenue"] if row["revenue"] else None
    return {"generated_at": timezone.now(), "currency": business.primary_currency, "period": {"date_from": start, "date_to": end}, "limit": limit, "products": rows}
