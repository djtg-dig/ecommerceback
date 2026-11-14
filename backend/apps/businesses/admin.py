from django.contrib import admin

from .models import (
    Address,
    AdministrativeArea,
    Business,
    BusinessMember,
    BusinessMemberPermission,
    BusinessPaymentMethod,
    Country,
    Locality,
)


@admin.register(Business)
class BusinessAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "structured_address",
        "status",
        "verification_status",
        "primary_currency",
        "created_at",
    )
    list_filter = ("is_verified", "status", "primary_currency")
    search_fields = ("name", "public_id", "phone", "zone", "structured_address__formatted_address")
    list_select_related = ("structured_address",)

    @admin.display(boolean=True, description="Entreprise vérifiée")
    def verification_status(self, business):
        return business.is_verified

    def get_readonly_fields(self, request, obj=None):
        """Allow the initial currency choice but protect it once history may exist."""
        readonly_fields = list(super().get_readonly_fields(request, obj))
        if obj:
            readonly_fields.append("primary_currency")

        return tuple(readonly_fields)


@admin.register(Country)
class CountryAdmin(admin.ModelAdmin):
    list_display = ("name", "iso2", "phone_code")
    search_fields = ("name", "iso2", "phone_code")
    ordering = ("name",)


@admin.register(AdministrativeArea)
class AdministrativeAreaAdmin(admin.ModelAdmin):
    list_display = ("name", "country", "code")
    list_filter = ("country",)
    search_fields = ("name", "code", "country__name", "country__iso2")
    list_select_related = ("country",)


@admin.register(Locality)
class LocalityAdmin(admin.ModelAdmin):
    list_display = ("name", "administrative_area", "country")
    list_filter = ("administrative_area__country",)
    search_fields = ("name", "code", "administrative_area__name", "administrative_area__country__name")
    list_select_related = ("administrative_area__country",)

    @admin.display(ordering="administrative_area__country__name", description="Pays")
    def country(self, locality):
        return locality.administrative_area.country


@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = ("id", "country", "administrative_area", "locality", "city", "street", "formatted_address")
    list_filter = ("country", "administrative_area")
    search_fields = ("state", "city", "neighborhood", "street", "postal_code", "formatted_address")
    list_select_related = ("country", "administrative_area", "locality")


@admin.register(BusinessMember)
class BusinessMemberAdmin(admin.ModelAdmin):
    list_display = (
        "business",
        "identity",
        "role",
        "title",
        "is_owner",
        "status",
        "joined_at",
    )
    readonly_fields = (
        "identity",
        "business",
        "role",
        "title",
        "is_owner",
        "status",
        "joined_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(BusinessMemberPermission)
class BusinessMemberPermissionAdmin(admin.ModelAdmin):
    list_display = (
        "member",
        "permission",
        "created_at",
    )
    readonly_fields = (
        "member",
        "permission",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
