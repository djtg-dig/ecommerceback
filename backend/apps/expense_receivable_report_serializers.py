from rest_framework import serializers


class ReceivableCustomerReportSerializer(serializers.Serializer):
    customer_public_id = serializers.CharField()
    name = serializers.CharField()
    original_amount = serializers.DecimalField(max_digits=16, decimal_places=2)
    paid_amount = serializers.DecimalField(max_digits=16, decimal_places=2)
    return_credit_amount = serializers.DecimalField(max_digits=16, decimal_places=2)
    outstanding_amount = serializers.DecimalField(max_digits=16, decimal_places=2)
    open_receivables_count = serializers.IntegerField()
    overdue_receivables_count = serializers.IntegerField()


class ReceivablesReportSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = ReceivableCustomerReportSerializer(many=True)
    total_outstanding = serializers.DecimalField(max_digits=16, decimal_places=2)
    return_credit_amount = serializers.DecimalField(max_digits=16, decimal_places=2)
    open_count = serializers.IntegerField()
    overdue_count = serializers.IntegerField()
