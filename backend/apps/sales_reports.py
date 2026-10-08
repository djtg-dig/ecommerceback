"""Compact independent sales and return projections for reporting."""

from decimal import Decimal

from django.db.models import (
    CharField,
    Count,
    DecimalField,
    ExpressionWrapper,
    F,
    Sum,
)
from django.db.models.functions import Coalesce, TruncDay, TruncMonth, TruncWeek
from django.utils import timezone

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
GROUPERS = {"day": TruncDay, "week": TruncWeek, "month": TruncMonth}


def completed_lines(business, start, end):
    return SaleLine.objects.filter(
        sale__business=business,
        sale__status=Sale.Status.COMPLETED,
        sale__completed_at__date__range=(start, end),
    )


def posted_return_lines(business, start, end):
    return SaleReturnLine.objects.filter(
        sale_return__business=business,
        sale_return__status=SaleReturn.Status.POSTED,
        sale_return__returned_at__date__range=(start, end),
    )


def _economic_values(sales, returns):
    sales_revenue = sales.get("sales_revenue", Decimal("0"))
    returns_revenue = returns.get("returns_revenue", Decimal("0"))
    sales_cogs = sales.get("sales_cogs", Decimal("0"))
    returns_cogs = returns.get("returns_cogs", Decimal("0"))
    net_revenue = sales_revenue - returns_revenue
    net_cogs = sales_cogs - returns_cogs
    return {
        "revenue": net_revenue,
        "cost_of_goods_sold": net_cogs,
        "sales_revenue": sales_revenue,
        "returns_revenue": returns_revenue,
        "net_revenue": net_revenue,
        "sales_cogs": sales_cogs,
        "returns_cogs": returns_cogs,
        "net_cogs": net_cogs,
        "gross_margin": net_revenue - net_cogs,
    }


def build_sales_series(business, start, end, group_by):
    """Merge independent sale and return aggregates into economic periods."""
    lines = completed_lines(business, start, end)
    return_lines = posted_return_lines(business, start, end)
    sales_totals = lines.aggregate(
        sales_revenue=Coalesce(
            Sum("line_total"),
            Decimal("0"),
            output_field=MONEY,
        ),
        sales_cogs=Coalesce(
            Sum(LINE_COST),
            Decimal("0"),
            output_field=MONEY,
        ),
        sales_count=Count("sale", distinct=True),
    )
    return_totals = return_lines.aggregate(
        returns_revenue=Coalesce(
            Sum("line_total"),
            Decimal("0"),
            output_field=MONEY,
        ),
        returns_cogs=Coalesce(
            Sum(RETURN_LINE_COST),
            Decimal("0"),
            output_field=MONEY,
        ),
        returns_count=Count("sale_return", distinct=True),
    )
    totals = {
        **_economic_values(sales_totals, return_totals),
        "sales_count": sales_totals["sales_count"],
        "returns_count": return_totals["returns_count"],
    }

    sales_rows = (
        lines.annotate(bucket=GROUPERS[group_by]("sale__completed_at"))
        .values("bucket")
        .annotate(
            sales_revenue=Coalesce(
                Sum("line_total"),
                Decimal("0"),
                output_field=MONEY,
            ),
            sales_cogs=Coalesce(
                Sum(LINE_COST),
                Decimal("0"),
                output_field=MONEY,
            ),
            sales_count=Count("sale", distinct=True),
        )
    )
    return_rows = (
        return_lines.annotate(
            bucket=GROUPERS[group_by]("sale_return__returned_at")
        )
        .values("bucket")
        .annotate(
            returns_revenue=Coalesce(
                Sum("line_total"),
                Decimal("0"),
                output_field=MONEY,
            ),
            returns_cogs=Coalesce(
                Sum(RETURN_LINE_COST),
                Decimal("0"),
                output_field=MONEY,
            ),
            returns_count=Count("sale_return", distinct=True),
        )
    )
    buckets = {}
    for row in sales_rows:
        buckets[row["bucket"]] = {
            "sales_revenue": row["sales_revenue"],
            "sales_cogs": row["sales_cogs"],
            "sales_count": row["sales_count"],
        }
    for row in return_rows:
        buckets.setdefault(row["bucket"], {}).update(
            returns_revenue=row["returns_revenue"],
            returns_cogs=row["returns_cogs"],
            returns_count=row["returns_count"],
        )

    series = []
    for bucket, values in sorted(buckets.items()):
        series.append(
            {
                "period": bucket.date(),
                **_economic_values(values, values),
                "sales_count": values.get("sales_count", 0),
                "returns_count": values.get("returns_count", 0),
            }
        )
    return {
        "generated_at": timezone.now(),
        "currency": business.primary_currency,
        "period": {"date_from": start, "date_to": end},
        "group_by": group_by,
        "totals": totals,
        "series": series,
    }


def build_product_top(business, start, end, limit):
    """Merge sales and returns under the immutable original Product parent."""
    sales_rows = (
        completed_lines(business, start, end)
        .annotate(
            parent_public_id=Coalesce(
                "product__public_id",
                "variant__product__public_id",
                output_field=CharField(),
            ),
            parent_name=Coalesce(
                "product__name",
                "variant__product__name",
                output_field=CharField(),
            ),
        )
        .values("parent_public_id", "parent_name")
        .annotate(
            sold_quantity=Sum("quantity"),
            sales_revenue=Coalesce(
                Sum("line_total"),
                Decimal("0"),
                output_field=MONEY,
            ),
            sales_cogs=Coalesce(
                Sum(LINE_COST),
                Decimal("0"),
                output_field=MONEY,
            ),
        )
    )
    return_rows = (
        posted_return_lines(business, start, end)
        .annotate(
            parent_public_id=Coalesce(
                "sale_line__product__public_id",
                "sale_line__variant__product__public_id",
                output_field=CharField(),
            ),
            parent_name=Coalesce(
                "sale_line__product__name",
                "sale_line__variant__product__name",
                output_field=CharField(),
            ),
        )
        .values("parent_public_id", "parent_name")
        .annotate(
            returned_quantity=Sum("quantity"),
            returns_revenue=Coalesce(
                Sum("line_total"),
                Decimal("0"),
                output_field=MONEY,
            ),
            returns_cogs=Coalesce(
                Sum(RETURN_LINE_COST),
                Decimal("0"),
                output_field=MONEY,
            ),
        )
    )
    products = {}
    for row in sales_rows:
        products[row["parent_public_id"]] = {
            "product_public_id": row["parent_public_id"],
            "name": row["parent_name"],
            "sold_quantity": row["sold_quantity"],
            "sales_revenue": row["sales_revenue"],
            "sales_cogs": row["sales_cogs"],
        }
    for row in return_rows:
        product = products.setdefault(
            row["parent_public_id"],
            {
                "product_public_id": row["parent_public_id"],
                "name": row["parent_name"],
            },
        )
        product.update(
            returned_quantity=row["returned_quantity"],
            returns_revenue=row["returns_revenue"],
            returns_cogs=row["returns_cogs"],
        )

    rows = []
    for product in products.values():
        sold_quantity = product.get("sold_quantity", Decimal("0"))
        returned_quantity = product.get("returned_quantity", Decimal("0"))
        economic = _economic_values(product, product)
        row = {
            "product_public_id": product["product_public_id"],
            "name": product["name"],
            "quantity_sold": sold_quantity,
            "sold_quantity": sold_quantity,
            "returned_quantity": returned_quantity,
            "net_quantity": sold_quantity - returned_quantity,
            **economic,
        }
        row["margin_rate"] = (
            row["gross_margin"] * Decimal("100") / row["net_revenue"]
            if row["net_revenue"]
            else None
        )
        rows.append(row)
    rows.sort(
        key=lambda row: (
            -row["net_revenue"],
            row["name"].casefold(),
            row["product_public_id"],
        )
    )
    return {
        "generated_at": timezone.now(),
        "currency": business.primary_currency,
        "period": {"date_from": start, "date_to": end},
        "limit": limit,
        "products": rows[:limit],
    }
