from rest_framework import serializers


class ReportPeriodSerializer(serializers.Serializer):
    date_from = serializers.DateField()
    date_to = serializers.DateField()


class EconomicMetricsSerializer(serializers.Serializer):
    revenue = serializers.DecimalField(max_digits=16, decimal_places=2)
    cost_of_goods_sold = serializers.DecimalField(max_digits=16, decimal_places=2)
    sales_revenue = serializers.DecimalField(max_digits=16, decimal_places=2)
    returns_revenue = serializers.DecimalField(max_digits=16, decimal_places=2)
    net_revenue = serializers.DecimalField(max_digits=16, decimal_places=2)
    sales_cogs = serializers.DecimalField(max_digits=16, decimal_places=2)
    returns_cogs = serializers.DecimalField(max_digits=16, decimal_places=2)
    net_cogs = serializers.DecimalField(max_digits=16, decimal_places=2)
    gross_margin = serializers.DecimalField(max_digits=16, decimal_places=2)


class SalesTotalsSerializer(EconomicMetricsSerializer):
    sales_count = serializers.IntegerField()
    returns_count = serializers.IntegerField()


class SalesSeriesRowSerializer(SalesTotalsSerializer):
    period = serializers.DateField()


class SalesReportSerializer(serializers.Serializer):
    generated_at = serializers.DateTimeField()
    currency = serializers.ChoiceField(choices=("CDF", "USD"))
    period = ReportPeriodSerializer()
    group_by = serializers.ChoiceField(choices=("day", "week", "month"))
    totals = SalesTotalsSerializer()
    series = SalesSeriesRowSerializer(many=True)


class ProductReportRowSerializer(EconomicMetricsSerializer):
    product_public_id = serializers.CharField()
    name = serializers.CharField()
    quantity_sold = serializers.DecimalField(max_digits=14, decimal_places=3)
    sold_quantity = serializers.DecimalField(max_digits=14, decimal_places=3)
    returned_quantity = serializers.DecimalField(max_digits=14, decimal_places=3)
    net_quantity = serializers.DecimalField(max_digits=14, decimal_places=3)
    margin_rate = serializers.DecimalField(
        max_digits=24,
        decimal_places=6,
        allow_null=True,
    )


class ProductReportSerializer(serializers.Serializer):
    generated_at = serializers.DateTimeField()
    currency = serializers.ChoiceField(choices=("CDF", "USD"))
    period = ReportPeriodSerializer()
    limit = serializers.IntegerField()
    products = ProductReportRowSerializer(many=True)
