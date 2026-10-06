from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import Business, BusinessCategory, BusinessMember, BusinessPaymentMethod


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = BusinessCategory
        fields = (
            "code",
            "name",
            "slug",
            "description",
        )


class BaseBusinessSerializer(serializers.ModelSerializer):
    categories = serializers.ListField(
        child=serializers.CharField(),
        write_only=True,
        required=False,
    )
    primary_category = serializers.CharField(write_only=True, required=False)


class BusinessCreateSerializer(BaseBusinessSerializer):
    class Meta:
        model = Business
        fields = (
            "name",
            "description",
            "address",
            "zone",
            "primary_currency",
            "phone",
            "categories",
            "primary_category",
        )


class BusinessUpdateSerializer(BaseBusinessSerializer):
    def validate(self, attrs):
        """Reject currency changes so historical Business operations keep one currency."""
        if self.instance and "primary_currency" in self.initial_data:
            raise serializers.ValidationError(
                {"primary_currency": "Business primary_currency is immutable."}
            )

        return super().validate(attrs)

    class Meta:
        model = Business
        fields = (
            "name",
            "description",
            "address",
            "zone",
            "primary_currency",
            "phone",
            "categories",
            "primary_category",
        )


class BusinessSerializer(serializers.ModelSerializer):
    categories = serializers.SerializerMethodField()
    primary_category = serializers.SerializerMethodField()

    class Meta:
        model = Business
        fields = (
            "public_id",
            "name",
            "description",
            "address",
            "zone",
            "primary_currency",
            "phone",
            "status",
            "categories",
            "primary_category",
            "created_at",
            "updated_at",
        )

    @extend_schema_field(CategorySerializer(many=True))
    def get_categories(self, business):
        memberships = business.category_memberships.select_related("category").all()
        categories = [membership.category for membership in memberships]

        return CategorySerializer(categories, many=True).data

    @extend_schema_field(CategorySerializer(allow_null=True))
    def get_primary_category(self, business):
        membership = business.category_memberships.select_related("category").filter(
            is_primary=True
        ).first()

        return CategorySerializer(membership.category).data if membership else None


class BusinessMemberSerializer(serializers.ModelSerializer):
    identity_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = BusinessMember
        fields = (
            "id",
            "identity_id",
            "role",
            "status",
            "joined_at",
        )

class BusinessPaymentMethodSerializer(serializers.ModelSerializer):
    class Meta:
        model = BusinessPaymentMethod
        fields = ("public_id", "name", "category", "is_active", "created_at", "updated_at")
        read_only_fields = ("public_id", "created_at", "updated_at")
