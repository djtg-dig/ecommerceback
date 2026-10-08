from rest_framework import serializers


class ProfitabilityPeriodSerializer(serializers.Serializer):
    date_from = serializers.DateField()
    date_to = serializers.DateField()


class ProfitabilitySummarySerializer(serializers.Serializer):
    generated_at = serializers.DateTimeField()
    currency = serializers.ChoiceField(choices=("CDF", "USD"))
    period = ProfitabilityPeriodSerializer()
    revenue = serializers.DecimalField(max_digits=16, decimal_places=2)
    cost_of_goods_sold = serializers.DecimalField(max_digits=16, decimal_places=2)
    sales_revenue = serializers.DecimalField(max_digits=16, decimal_places=2)
    returns_revenue = serializers.DecimalField(max_digits=16, decimal_places=2)
    net_revenue = serializers.DecimalField(max_digits=16, decimal_places=2)
    sales_cogs = serializers.DecimalField(max_digits=16, decimal_places=2)
    returns_cogs = serializers.DecimalField(max_digits=16, decimal_places=2)
    net_cogs = serializers.DecimalField(max_digits=16, decimal_places=2)
    gross_margin = serializers.DecimalField(max_digits=16, decimal_places=2)
    expenses = serializers.DecimalField(max_digits=16, decimal_places=2)
    net_result = serializers.DecimalField(max_digits=16, decimal_places=2)
