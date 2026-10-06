"""Schema serializers for the Expenses HTTP contract."""

from decimal import Decimal

from rest_framework import serializers

from apps.common.choices import PaymentMethod

from .models import Expense


class ExpenseCategorySerializer(serializers.Serializer):
    public_id = serializers.CharField(read_only=True)
    code = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField(allow_blank=True)
    is_system = serializers.BooleanField(read_only=True)
    is_active = serializers.BooleanField()
    sort_order = serializers.IntegerField()


class ExpenseCategoryCreateSerializer(serializers.Serializer):
    code = serializers.CharField(required=False)
    name = serializers.CharField()
    description = serializers.CharField(required=False, allow_blank=True)
    sort_order = serializers.IntegerField(required=False)


class ExpenseCategoryUpdateSerializer(serializers.Serializer):
    code = serializers.CharField(required=False)
    name = serializers.CharField(required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    is_active = serializers.BooleanField(required=False)
    sort_order = serializers.IntegerField(required=False)


class ExpenseSerializer(serializers.Serializer):
    public_id = serializers.CharField(read_only=True)
    category = serializers.CharField()
    amount = serializers.DecimalField(max_digits=16, decimal_places=2)
    currency = serializers.ChoiceField(choices=Expense.Currency.choices)
    payment_method = serializers.ChoiceField(
        choices=PaymentMethod.choices,
        help_text="Classification déclarative uniquement ; aucune transaction externe n'est exécutée.",
    )
    expense_date = serializers.DateField()
    description = serializers.CharField()
    reference = serializers.CharField(allow_blank=True)
    status = serializers.ChoiceField(choices=Expense.Status.choices, read_only=True)
    created_by = serializers.UUIDField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)
    cancelled_by = serializers.UUIDField(read_only=True, allow_null=True)
    cancelled_at = serializers.DateTimeField(read_only=True, allow_null=True)
    cancellation_reason = serializers.CharField(read_only=True, allow_blank=True)
    paid_amount = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    balance = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    payment_status = serializers.ChoiceField(choices=Expense.PaymentStatus.choices, read_only=True)


class ExpenseCreateSerializer(serializers.Serializer):
    category = serializers.CharField()
    amount = serializers.DecimalField(max_digits=16, decimal_places=2)
    currency = serializers.ChoiceField(choices=Expense.Currency.choices, required=False)
    payment_method = serializers.ChoiceField(
        choices=PaymentMethod.choices,
        required=False,
        help_text="Classification déclarative uniquement ; aucune transaction externe n'est exécutée.",
    )
    expense_date = serializers.DateField(required=False)
    description = serializers.CharField(required=False)
    reference = serializers.CharField(required=False, allow_blank=True)


class ExpenseUpdateSerializer(serializers.Serializer):
    category = serializers.CharField(required=False)
    amount = serializers.DecimalField(max_digits=16, decimal_places=2, required=False)
    currency = serializers.ChoiceField(choices=Expense.Currency.choices, required=False)
    payment_method = serializers.ChoiceField(choices=PaymentMethod.choices, required=False)
    expense_date = serializers.DateField(required=False)
    description = serializers.CharField(required=False)
    reference = serializers.CharField(required=False, allow_blank=True)


class ExpenseCancelSerializer(serializers.Serializer):
    cancellation_reason = serializers.CharField(
        help_text="Motif obligatoire de l'annulation définitive.",
    )


class ExpensePaymentSerializer(serializers.Serializer):
    public_id = serializers.CharField(read_only=True)
    amount = serializers.DecimalField(max_digits=16, decimal_places=2)
    payment_method = serializers.ChoiceField(choices=PaymentMethod.choices)
    paid_at = serializers.DateTimeField(read_only=True)
    created_by = serializers.UUIDField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    is_reversed = serializers.BooleanField(read_only=True)
    reversed_at = serializers.DateTimeField(read_only=True, allow_null=True)
    reversed_by = serializers.UUIDField(read_only=True, allow_null=True)
    reversal_reason = serializers.CharField(read_only=True, allow_blank=True)


class ExpensePaymentCreateSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=16, decimal_places=2, min_value=Decimal("0.01"))
    payment_method = serializers.ChoiceField(choices=PaymentMethod.choices)


class ExpensePaymentReverseSerializer(serializers.Serializer):
    reason = serializers.CharField()
