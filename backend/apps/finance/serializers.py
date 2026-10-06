from rest_framework import serializers

from .models import FinancialMovement


class FinancialMovementSerializer(serializers.ModelSerializer):
    sale = serializers.CharField(source="sale.public_id", read_only=True)
    receivable_payment = serializers.CharField(
        source="receivable_payment.public_id", read_only=True
    )
    expense = serializers.CharField(source="expense.public_id", read_only=True)
    expense_payment = serializers.CharField(source="expense_payment.public_id", read_only=True)
    reversal_of = serializers.CharField(source="reversal_of.public_id", read_only=True)

    class Meta:
        model = FinancialMovement
        fields = (
            "public_id",
            "direction",
            "amount",
            "currency",
            "payment_method",
            "event_type",
            "occurred_at",
            "reason",
            "sale",
            "receivable_payment",
            "expense",
            "expense_payment",
            "reversal_of",
            "created_at",
        )
        read_only_fields = fields
