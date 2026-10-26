from django.core.exceptions import ValidationError
from rest_framework.exceptions import NotFound, PermissionDenied

from .models import Business, BusinessMember, BusinessMemberPermission

LEGACY_PERMISSION_VALUES = frozenset({
    "VIEW_MEMBERS", "MANAGE_MEMBERS", "UPDATE_BUSINESS", "VIEW_PAYMENT_METHODS",
    "MANAGE_PAYMENT_METHODS", "VIEW_CUSTOMERS", "MANAGE_CUSTOMERS", "VIEW_CATALOG",
    "MANAGE_CATALOG", "VIEW_INVENTORY", "MANAGE_INVENTORY", "MANAGE_EXPENSE_CATEGORIES",
    "CREATE_EXPENSES", "VIEW_EXPENSES", "MANAGE_EXPENSES", "VIEW_PURCHASES",
    "MANAGE_PURCHASES", "USE_POS", "VIEW_SALES", "MANAGE_SALES",
    "MANAGE_SALE_RETURNS", "VIEW_RECEIVABLES", "MANAGE_RECEIVABLES",
    "VIEW_FINANCIAL_SUMMARY", "VIEW_DASHBOARD", "VIEW_PROFITABILITY", "VIEW_REPORTS",
})


def atomic_permission_values():
    return [value for value in BusinessMemberPermission.Permission.values if value not in LEGACY_PERMISSION_VALUES]


# Référence immuable utilisée aussi par le schéma OpenAPI pour nommer sans
# ambiguïté le sous-ensemble de permissions effectivement attribuables.
ATOMIC_PERMISSION_VALUES = tuple(atomic_permission_values())


def effective_permissions(member):
    """Return the current member's effective atomic permissions in registry order.

    This is intentionally a UI projection, not an authorization bypass: every
    protected endpoint still calls ``require_permission`` independently.
    """
    permissions = atomic_permission_values()
    if not member or member.status != BusinessMember.Status.ACTIVE:
        return []
    if member.is_owner:
        return permissions
    granted = set(
        member.permissions.filter(permission__in=permissions).values_list(
            "permission", flat=True
        )
    )
    return [permission for permission in permissions if permission in granted]


def validate_permission(permission):
    """Reject permission names that are not part of the server-side registry."""
    if permission not in atomic_permission_values():
        raise ValidationError({"permission": "Unknown Business permission."})

    return permission


def membership_for(identity, business, *, include_suspended=False):
    """Return an identity's membership without crossing the Business boundary."""
    memberships = BusinessMember.objects.select_related("business").filter(
        identity=identity,
        business=business,
    )
    if include_suspended:
        memberships = memberships.filter(
            status__in=(
                BusinessMember.Status.ACTIVE,
                BusinessMember.Status.SUSPENDED,
            )
        )
    else:
        memberships = memberships.filter(status=BusinessMember.Status.ACTIVE)

    return memberships.first()


def has_permission(member, permission, *, write=False):
    """Evaluate one registered permission from trusted membership data.

    Reads remain possible on an inactive Business for an active authorized member,
    so administrative status information stays available. Business writes are
    denied unless the Business itself is active.
    """
    validate_permission(permission)

    if not member or member.status != BusinessMember.Status.ACTIVE:
        return False
    if write and member.business.status != Business.Status.ACTIVE:
        return False
    if member.is_owner:
        return True
    return BusinessMemberPermission.objects.filter(
        member=member, permission=permission
    ).exists()


def require_permission(identity, business, permission, *, write=False):
    """Return the authorized member or raise the API's canonical 404/403 errors.

    A missing or removed membership is deliberately indistinguishable from an
    unknown Business. A suspended member is known to the tenant but has no
    authorization, so it receives 403. Callers mark business mutations with
    ``write=True``.
    """
    validate_permission(permission)
    member = membership_for(identity, business, include_suspended=True)

    if member is None:
        raise NotFound("Not found.")
    if not has_permission(member, permission, write=write):
        raise PermissionDenied("Forbidden.")

    return member


def require_any_permission(identity, business, permissions, *, write=False):
    """Require at least one registered permission with canonical tenant errors."""
    permissions = tuple(permissions)
    if not permissions:
        raise ValidationError({"permission": "At least one permission is required."})
    for permission in permissions:
        validate_permission(permission)

    member = membership_for(identity, business, include_suspended=True)
    if member is None:
        raise NotFound("Not found.")
    if not any(
        has_permission(member, permission, write=write)
        for permission in permissions
    ):
        raise PermissionDenied("Forbidden.")

    return member
