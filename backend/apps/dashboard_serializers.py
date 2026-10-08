from rest_framework import serializers


class DashboardPeriodSerializer(serializers.Serializer):
    date_from = serializers.DateField()
    date_to = serializers.DateField()


class DashboardSalesSerializer(serializers.Serializer):
    total = serializers.DecimalField(max_digits=16, decimal_places=2)
    count = serializers.IntegerField()
    sales_revenue = serializers.DecimalField(max_digits=16, decimal_places=2)
    returns_revenue = serializers.DecimalField(max_digits=16, decimal_places=2)
    net_revenue = serializers.DecimalField(max_digits=16, decimal_places=2)


class DashboardCashSerializer(serializers.Serializer):
    inflow = serializers.DecimalField(max_digits=16, decimal_places=2)
    outflow = serializers.DecimalField(max_digits=16, decimal_places=2)
    net = serializers.DecimalField(max_digits=16, decimal_places=2)


class DashboardReceivablesSerializer(serializers.Serializer):
    open_count = serializers.IntegerField()
    outstanding_amount = serializers.DecimalField(max_digits=16, decimal_places=2)
    overdue_count = serializers.IntegerField()


class DashboardInventorySerializer(serializers.Serializer):
    out_of_stock_count = serializers.IntegerField()


class DashboardPurchasesSerializer(serializers.Serializer):
    outstanding_amount = serializers.DecimalField(max_digits=16, decimal_places=2)


class DashboardSerializer(serializers.Serializer):
    generated_at = serializers.DateTimeField()
    currency = serializers.ChoiceField(choices=("CDF", "USD"))
    period = DashboardPeriodSerializer()
    sales = DashboardSalesSerializer()
    cash = DashboardCashSerializer()
    receivables = DashboardReceivablesSerializer()
    inventory = DashboardInventorySerializer()
    purchases = DashboardPurchasesSerializer()
