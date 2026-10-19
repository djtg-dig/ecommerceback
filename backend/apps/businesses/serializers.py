from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import (
    Business,
    BusinessCurrency,
    BusinessExchangeRate,
    BusinessCategory,
    BusinessMember,
    BusinessMemberInvitation,
    BusinessMemberPermission,
    BusinessPaymentMethod,
    Currency,
)
from .services.invitations import validate_invitation_state
from .permissions import atomic_permission_values


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
        memberships = self._category_memberships(business)
        categories = [membership.category for membership in memberships]

        return CategorySerializer(categories, many=True).data

    @extend_schema_field(CategorySerializer(allow_null=True))
    def get_primary_category(self, business):
        membership = next(
            (item for item in self._category_memberships(business) if item.is_primary),
            None,
        )

        return CategorySerializer(membership.category).data if membership else None

    @staticmethod
    def _category_memberships(business):
        prefetched = getattr(business, "_prefetched_category_memberships", None)
        if prefetched is not None:
            return prefetched
        return business.category_memberships.select_related("category").all()


class CurrencySerializer(serializers.ModelSerializer):
    class Meta:
        model = Currency
        fields = ("code", "name", "symbol", "decimal_places", "is_active")


class BusinessCurrencySerializer(serializers.ModelSerializer):
    currency = CurrencySerializer(read_only=True)
    code = serializers.CharField(source="currency.code", read_only=True)

    class Meta:
        model = BusinessCurrency
        fields = ("code", "currency", "is_primary", "is_enabled", "created_at", "updated_at")


class BusinessCurrencyWriteSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=3)

    def validate_code(self, value):
        code = value.upper()
        if not Currency.objects.filter(code=code, is_active=True).exists():
            raise serializers.ValidationError("Devise inactive ou inconnue.")
        return code


class BusinessExchangeRateSerializer(serializers.ModelSerializer):
    from_currency = serializers.SlugRelatedField(slug_field="code", queryset=Currency.objects.all())
    to_currency = serializers.SlugRelatedField(slug_field="code", queryset=Currency.objects.all())

    class Meta:
        model = BusinessExchangeRate
        fields = ("id", "from_currency", "to_currency", "rate", "effective_at", "expires_at", "is_active", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")

    def validate(self, attrs):
        business = self.context["business"]
        from_currency = attrs.get("from_currency", getattr(self.instance, "from_currency", None))
        to_currency = attrs.get("to_currency", getattr(self.instance, "to_currency", None))
        if from_currency == to_currency:
            raise serializers.ValidationError({"to_currency": "Les devises doivent être différentes."})
        codes = [from_currency.code, to_currency.code]
        if business.currencies.filter(currency_id__in=codes, is_enabled=True).count() != 2:
            raise serializers.ValidationError("Les deux devises doivent être acceptées par l’entreprise.")
        return attrs


class BusinessMemberSerializer(serializers.ModelSerializer):
    """Compact administrative projection of one Business membership."""

    permissions = serializers.SerializerMethodField()
    identity_email = serializers.EmailField(
        source="identity.verified_email",
        read_only=True,
    )

    class Meta:
        model = BusinessMember
        fields = (
            "public_id",
            "identity_email",
            "title",
            "is_owner",
            "status",
            "permissions",
            "joined_at",
        )
        read_only_fields = fields

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_permissions(self, member):
        from .permissions import atomic_permission_values

        if not self.context.get("include_permissions", True):
            return []
        if member.is_owner:
            return atomic_permission_values()
        prefetched = getattr(member, "_prefetched_permissions", None)
        if prefetched is not None:
            return [row.permission for row in prefetched if row.permission in atomic_permission_values()]
        return list(
            member.permissions.filter(permission__in=atomic_permission_values()).values_list("permission", flat=True)
        )


class BusinessMemberTitleSerializer(serializers.ModelSerializer):
    """Title-only update; ownership, role, status and permissions stay read-only."""

    class Meta:
        model = BusinessMember
        fields = ("title",)
        extra_kwargs = {"title": {"required": True, "allow_blank": False}}


class BusinessMemberPermissionSerializer(serializers.Serializer):
    """Compact projection of one registered Business permission."""

    permission = serializers.ChoiceField(choices=atomic_permission_values())


class BusinessMemberPermissionGrantSerializer(serializers.Serializer):
    """Payload used to grant one registered permission to a member."""

    permission = serializers.ChoiceField(choices=atomic_permission_values())


class BusinessMemberInvitationCreateSerializer(serializers.Serializer):
    """Validated administrative request for one email invitation."""

    email = serializers.EmailField(
        max_length=254,
        error_messages={
            "invalid": "Veuillez saisir une adresse e-mail valide.",
            "required": "L'adresse e-mail est obligatoire.",
            "blank": "L'adresse e-mail est obligatoire.",
        },
    )
    title = serializers.CharField(
        max_length=120,
        required=False,
        allow_blank=True,
        trim_whitespace=True,
        default="",
    )
    permissions = serializers.ListField(
        child=serializers.ChoiceField(
            choices=BusinessMemberPermission.Permission.choices,
        ),
        required=False,
        allow_empty=True,
        default=list,
    )

    def validate_permissions(self, permissions):
        return list(dict.fromkeys(permissions))


class BusinessMemberInvitationSerializer(serializers.ModelSerializer):
    """Compact administrative projection that never exposes invitation secrets."""

    status = serializers.SerializerMethodField()

    class Meta:
        model = BusinessMemberInvitation
        fields = (
            "public_id",
            "email",
            "title",
            "permissions",
            "status",
            "expires_at",
            "last_sent_at",
            "resend_count",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    @extend_schema_field(
        serializers.ChoiceField(
            choices=BusinessMemberInvitation.Status.choices,
        )
    )
    def get_status(self, invitation):
        return validate_invitation_state(invitation)


class BusinessMemberInvitationTokenSerializer(serializers.Serializer):
    """One-time invitation secret supplied by the authenticated recipient."""

    token = serializers.CharField(
        min_length=20,
        max_length=255,
        trim_whitespace=False,
        write_only=True,
        error_messages={
            "required": "Le jeton d'invitation est obligatoire.",
            "blank": "Le jeton d'invitation est obligatoire.",
            "min_length": "Le jeton d'invitation est invalide.",
        },
    )


class BusinessMemberInvitationActionSerializer(serializers.ModelSerializer):
    """Compact terminal state returned without email or invitation secret."""

    business_public_id = serializers.CharField(
        source="business.public_id",
        read_only=True,
    )
    business_name = serializers.CharField(
        source="business.name",
        read_only=True,
    )
    member_public_id = serializers.CharField(
        source="member.public_id",
        allow_null=True,
        read_only=True,
    )
    member_title = serializers.CharField(
        source="member.title",
        allow_null=True,
        read_only=True,
    )

    class Meta:
        model = BusinessMemberInvitation
        fields = (
            "public_id",
            "status",
            "business_public_id",
            "business_name",
            "member_public_id",
            "member_title",
            "permissions",
            "acted_at",
        )
        read_only_fields = fields


class BusinessMemberInvitationRecipientSerializer(serializers.ModelSerializer):
    """Invitation visible only to its authenticated Carri recipient."""

    business_public_id = serializers.CharField(
        source="business.public_id",
        read_only=True,
    )
    business_name = serializers.CharField(
        source="business.name",
        read_only=True,
    )
    business_description = serializers.CharField(
        source="business.description",
        read_only=True,
    )
    business_address = serializers.CharField(
        source="business.address",
        read_only=True,
    )
    business_zone = serializers.CharField(
        source="business.zone",
        read_only=True,
    )
    business_primary_category = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()

    class Meta:
        model = BusinessMemberInvitation
        fields = (
            "public_id",
            "business_public_id",
            "business_name",
            "business_description",
            "business_address",
            "business_zone",
            "business_primary_category",
            "title",
            "permissions",
            "status",
            "expires_at",
            "created_at",
        )
        read_only_fields = fields

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_business_primary_category(self, invitation):
        membership = next(
            (
                item
                for item in invitation.business.category_memberships.all()
                if item.is_primary
            ),
            None,
        )
        return membership.category.name if membership else None

    @extend_schema_field(
        serializers.ChoiceField(
            choices=BusinessMemberInvitation.Status.choices,
        )
    )
    def get_status(self, invitation):
        return validate_invitation_state(invitation)


class BusinessPermissionCatalogSerializer(serializers.Serializer):
    """Compact projection of the server-side permission registry."""

    permission = serializers.ChoiceField(
        choices=BusinessMemberPermission.Permission.choices,
    )
    label = serializers.CharField(read_only=True)


class BusinessPaymentMethodSerializer(serializers.ModelSerializer):
    class Meta:
        model = BusinessPaymentMethod
        fields = ("public_id", "name", "category", "is_active", "created_at", "updated_at")
        read_only_fields = ("public_id", "created_at", "updated_at")
