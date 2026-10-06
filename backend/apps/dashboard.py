"""Compact SQL-backed projections for the internal Business dashboard."""
from decimal import Decimal
from django.db.models import Count, DecimalField, F, OuterRef, Subquery, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from apps.finance.models import FinancialMovement
from apps.inventory.models import InventoryItem
from apps.purchases.models import Purchase, PurchaseLine, SupplierPayment
from apps.receivables.models import Receivable, ReceivablePayment
from apps.sales.models import SaleLine

MONEY = DecimalField(max_digits=16, decimal_places=2)

def build_dashboard(business, start, end):
    """Return compact aggregates; each domain uses bounded SQL, never N+1 properties."""
    sales = SaleLine.objects.filter(sale__business=business, sale__status='COMPLETED', sale__completed_at__date__range=(start, end)).aggregate(total=Coalesce(Sum('line_total'), Decimal('0'), output_field=MONEY), count=Count('sale', distinct=True))
    movement_totals = FinancialMovement.objects.filter(business=business, occurred_at__date__range=(start, end)).values('direction').annotate(total=Sum('amount'))
    cash = {row['direction']: row['total'] or Decimal('0') for row in movement_totals}
    paid = ReceivablePayment.objects.filter(receivable=OuterRef('pk')).values('receivable').annotate(total=Sum('amount')).values('total')
    receivables = Receivable.objects.filter(business=business, status__in=['OPEN','PARTIALLY_PAID']).annotate(paid=Coalesce(Subquery(paid, output_field=MONEY), Decimal('0'), output_field=MONEY))
    receivable_total = receivables.aggregate(total=Coalesce(Sum(F('original_amount')-F('paid'), output_field=MONEY), Decimal('0'), output_field=MONEY))['total']
    lines = PurchaseLine.objects.filter(purchase=OuterRef('pk')).values('purchase').annotate(total=Sum('line_total')).values('total')
    payments = SupplierPayment.objects.filter(purchase=OuterRef('pk'), reversed_at__isnull=True).values('purchase').annotate(total=Sum('amount')).values('total')
    purchases = Purchase.objects.filter(business=business, status__in=['CONFIRMED','RECEIVED']).annotate(total_amount=Coalesce(Subquery(lines, output_field=MONEY), Decimal('0'), output_field=MONEY), paid_amount=Coalesce(Subquery(payments, output_field=MONEY), Decimal('0'), output_field=MONEY)).annotate(balance_amount=F('total_amount') - F('paid_amount'))
    purchase_total = purchases.aggregate(total=Coalesce(Sum('balance_amount'), Decimal('0'), output_field=MONEY))['total']
    inflow=cash.get('INFLOW',Decimal('0')); outflow=cash.get('OUTFLOW',Decimal('0'))
    return {'generated_at': timezone.now(), 'currency': business.primary_currency, 'period': {'date_from':start,'date_to':end}, 'sales': {'total':sales['total'],'count':sales['count']}, 'cash': {'inflow':inflow,'outflow':outflow,'net':inflow-outflow}, 'receivables': {'open_count':receivables.count(),'outstanding_amount':receivable_total,'overdue_count':receivables.filter(due_date__lt=timezone.localdate()).count()}, 'inventory': {'out_of_stock_count':InventoryItem.objects.filter(business=business,quantity=F('reserved_quantity')).count()}, 'purchases': {'outstanding_amount':purchase_total}}
