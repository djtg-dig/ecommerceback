from django.contrib import admin

from .models import Business, BusinessMember


@admin.register(Business)
class BusinessAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "status",
        "primary_currency",
        "created_at",
    )

    def get_readonly_fields(self, request, obj=None):
        """Allow the initial currency choice but protect it once history may exist."""
        readonly_fields = list(super().get_readonly_fields(request, obj))
        if obj:
            readonly_fields.append("primary_currency")

        return tuple(readonly_fields)


@admin.register(BusinessMember)
class BusinessMemberAdmin(admin.ModelAdmin):
    list_display = (
        "business",
        "identity",
        "role",
        "status",
        "joined_at",
    )
    readonly_fields = (
        "identity",
        "business",
        "role",
        "status",
        "joined_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
