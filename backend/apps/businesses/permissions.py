from .models import BusinessMember, BusinessMemberPermission


def membership_for(identity, business):
    """Return the identity's active membership in a Business, when it exists."""
    return BusinessMember.objects.filter(
        identity=identity,
        business=business,
        status=BusinessMember.Status.ACTIVE,
    ).first()


def can_manage_business(member):
    """Transitional gate backed by ownership or one explicit permission.

    Existing endpoints still call this broad helper. Later API-specific lots can
    replace it with their granular permission without consulting ``role``.
    """
    return has_permission(
        member,
        BusinessMemberPermission.Permission.UPDATE_BUSINESS,
    )


def can_view_members(member):
    """Allow owners or members holding the explicit member-view permission."""
    return has_permission(
        member,
        BusinessMemberPermission.Permission.VIEW_MEMBERS,
    )


def has_permission(member, permission):
    """Return True if the member is an active owner or holds the explicit permission."""
    if not member or member.status != BusinessMember.Status.ACTIVE:
        return False
    if member.is_owner:
        return True
    return BusinessMemberPermission.objects.filter(
        member=member, permission=permission
    ).exists()
