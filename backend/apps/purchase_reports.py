"""Compact SQL projections for received purchases and supplier debts."""
from decimal import Decimal
from django.db.models import Count, DecimalField, F, OuterRef, Subquery, Sum
from django.db.models.functions import Coalesce, TruncDay, TruncMonth, TruncWeek
from django.utils import timezone
from apps.purchases.models import Purchase, PurchaseLine, SupplierPayment

MONEY = DecimalField(max_digits=16, decimal_places=2)
GROUPERS = {"day": TruncDay, "week": TruncWeek, "month": TruncMonth}

def received_lines(business, start, end):
    return PurchaseLine.objects.filter(purchase__business=business, purchase__status=Purchase.Status.RECEIVED, purchase__received_at__date__range=(start, end))

def build_purchases_report(business, start, end, group_by):
    lines = received_lines(business, start, end)
    totals = lines.aggregate(total_purchases=Coalesce(Sum("line_total"), Decimal("0"), output_field=MONEY), purchases_count=Count("purchase", distinct=True))
    series = lines.annotate(bucket=GROUPERS[group_by]("purchase__received_at")).values("bucket").annotate(amount=Coalesce(Sum("line_total"), Decimal("0"), output_field=MONEY), purchases_count=Count("purchase", distinct=True)).order_by("bucket")
    return {"generated_at": timezone.now(), "currency": business.primary_currency, "period": {"date_from": start, "date_to": end}, "group_by": group_by, **totals, "series": [{"period": row["bucket"].date(), "amount": row["amount"], "purchases_count": row["purchases_count"]} for row in series]}

def debt_queryset(business):
    lines = PurchaseLine.objects.filter(purchase=OuterRef("pk")).values("purchase").annotate(total=Sum("line_total")).values("total")
    payments = SupplierPayment.objects.filter(purchase=OuterRef("pk"), reversed_at__isnull=True).values("purchase").annotate(total=Sum("amount")).values("total")
    return Purchase.objects.filter(business=business, status__in=[Purchase.Status.CONFIRMED, Purchase.Status.RECEIVED]).annotate(purchase_total=Coalesce(Subquery(lines, output_field=MONEY), Decimal("0"), output_field=MONEY), paid=Coalesce(Subquery(payments, output_field=MONEY), Decimal("0"), output_field=MONEY)).annotate(balance=F("purchase_total") - F("paid")).filter(balance__gt=0)
