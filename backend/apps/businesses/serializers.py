from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import (
    Business,
    BusinessCategory,
    BusinessMember,
    BusinessMemberInvitation,
    BusinessMemberPermission,
    BusinessPaymentMethod,
)
from .services.invitations import validate_invitation_state


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
    """Compact administrative projection of one Business membership."""

    permissions = serializers.SerializerMethodField()

    class Meta:
        model = BusinessMember
        fields = (
            "public_id",
            "title",
            "is_owner",
            "status",
            "permissions",
            "joined_at",
        )
        read_only_fields = fields

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_permissions(self, member):
        if member.is_owner:
            return list(BusinessMemberPermission.Permission.values)
        prefetched = getattr(member, "_prefetched_permissions", None)
        if prefetched is not None:
            return [row.permission for row in prefetched]
        return list(
            member.permissions.values_list("permission", flat=True)
        )


class BusinessMemberTitleSerializer(serializers.ModelSerializer):
    """Title-only update; ownership, role, status and permissions stay read-only."""

    class Meta:
        model = BusinessMember
        fields = ("title",)
        extra_kwargs = {"title": {"required": True, "allow_blank": False}}


class BusinessMemberPermissionSerializer(serializers.Serializer):
    """Compact projection of one registered Business permission."""

    permission = serializers.ChoiceField(
        choices=BusinessMemberPermission.Permission.choices,
    )


class BusinessMemberPermissionGrantSerializer(serializers.Serializer):
    """Payload used to grant one registered permission to a member."""

    permission = serializers.ChoiceField(
        choices=BusinessMemberPermission.Permission.choices,
    )


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


class BusinessMemberInvitationSerializer(serializers.ModelSerializer):
    """Compact administrative projection that never exposes invitation secrets."""

    status = serializers.SerializerMethodField()

    class Meta:
        model = BusinessMemberInvitation
        fields = (
            "public_id",
            "email",
            "title",
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
            "acted_at",
        )
        read_only_fields = fields


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
