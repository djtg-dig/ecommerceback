from decimal import Decimal
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from apps.businesses.models import BusinessPaymentMethod
from apps.catalog.models import Product, ProductVariant
from apps.common.choices import PaymentMethod
from .models import Customer, Sale, SaleLine, SaleReturn, SaleReturnLine


class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = (
            "public_id",
            "name",
            "phone",
            "email",
            "address",
            "notes",
            "is_active",
        )
        read_only_fields = ("public_id",)


class PosCustomerSerializer(serializers.ModelSerializer):
    """Compact customer identity used only to attach a customer at the POS."""

    class Meta:
        model = Customer
        fields = ("public_id", "name", "phone")
        read_only_fields = fields


class SaleSerializer(serializers.ModelSerializer):
    customer = serializers.CharField(
        source="customer.public_id", read_only=True, allow_null=True
    )
    total = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)

    class Meta:
        model = Sale
        fields = (
            "public_id",
            "customer",
            "status",
            "currency",
            "reference",
            "notes",
            "total",
            "created_at",
            "completed_at",
        )


class SaleWrite(serializers.ModelSerializer):
    customer = serializers.SlugRelatedField(
        slug_field="public_id",
        queryset=Customer.objects.all(),
        allow_null=True,
        required=False,
    )
    currency = serializers.ChoiceField(choices=("CDF", "USD"), required=False)

    class Meta:
        model = Sale
        fields = ("customer", "currency", "reference", "notes")

    def validate_currency(self, value):
        business = self.context["business"]
        if value != business.primary_currency:
            raise serializers.ValidationError(
                "Currency must match the Business primary currency."
            )
        return value

    def validate_customer(self, x):
        if x and x.business_id != self.context["business"].id:
            raise serializers.ValidationError("External customer")
        return x


class LineSerializer(serializers.ModelSerializer):
    product = serializers.CharField(
        source="product.public_id", read_only=True, allow_null=True
    )
    variant = serializers.CharField(
        source="variant.public_id", read_only=True, allow_null=True
    )

    class Meta:
        model = SaleLine
        fields = (
            "public_id",
            "product",
            "variant",
            "quantity",
            "unit_price",
            "unit_cost_snapshot",
            "line_total",
        )


class LineWrite(serializers.Serializer):
    product = serializers.SlugRelatedField(
        slug_field="public_id", queryset=Product.objects.all(), required=False
    )
    variant = serializers.SlugRelatedField(
        slug_field="public_id", queryset=ProductVariant.objects.all(), required=False
    )
    quantity = serializers.DecimalField(
        max_digits=14, decimal_places=3, min_value=Decimal(".001")
    )
    unit_price = serializers.DecimalField(
        max_digits=14, decimal_places=2, min_value=0, required=False
    )

    def validate(self, a):
        from .services import target

        target(self.context["sale"], a.get("product"), a.get("variant"))
        if "unit_price" not in a:
            a["unit_price"] = (
                a["variant"].effective_selling_price
                if a.get("variant")
                else a["product"].selling_price
            )
        return a


class SaleCompleteSerializer(serializers.Serializer):
    amount_paid = serializers.DecimalField(
        max_digits=16, decimal_places=2, min_value=Decimal("0")
    )
    payment_method = serializers.ChoiceField(
        choices=PaymentMethod.choices,
        required=False,
        allow_null=True,
    )

    def validate(self, attrs):
        amount_paid = attrs["amount_paid"]
        payment_method = attrs.get("payment_method")
        if amount_paid > 0 and not payment_method:
            raise serializers.ValidationError(
                {"payment_method": "Required when amount_paid is positive."}
            )
        if amount_paid == 0 and payment_method is not None:
            raise serializers.ValidationError(
                {"payment_method": "Must be omitted for a credit sale."}
            )
        return attrs


class SaleReturnRequestLineSerializer(serializers.Serializer):
    sale_line = serializers.CharField()
    quantity = serializers.DecimalField(
        max_digits=14,
        decimal_places=3,
        min_value=Decimal("0.001"),
    )


class SaleReturnRequestSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, default="")
    returned_at = serializers.DateTimeField()
    refund_payment_method = serializers.SlugRelatedField(
        slug_field="public_id",
        queryset=BusinessPaymentMethod.objects.all(),
        required=False,
        allow_null=True,
    )
    lines = SaleReturnRequestLineSerializer(many=True, allow_empty=False)


class SaleReturnLineSerializer(serializers.ModelSerializer):
    sale_line = serializers.CharField(source="sale_line.public_id", read_only=True)

    class Meta:
        model = SaleReturnLine
        fields = (
            "public_id",
            "sale_line",
            "quantity",
            "unit_price_snapshot",
            "unit_cost_snapshot",
            "line_total",
        )


class SaleReturnSerializer(serializers.ModelSerializer):
    return_total = serializers.SerializerMethodField()
    refund_payment_method = serializers.SlugRelatedField(
        slug_field="public_id",
        read_only=True,
        allow_null=True,
    )
    lines = SaleReturnLineSerializer(many=True, read_only=True)

    class Meta:
        model = SaleReturn
        fields = (
            "public_id",
            "status",
            "reason",
            "returned_at",
            "return_total",
            "receivable_credit_amount",
            "refund_amount",
            "refund_payment_method",
            "lines",
        )

    @extend_schema_field(serializers.DecimalField(max_digits=16, decimal_places=2))
    def get_return_total(self, sale_return):
        return sum(
            (line.line_total for line in sale_return.lines.all()),
            Decimal("0.00"),
        )
