from .models import BusinessMember


def membership_for(identity, business):
    """Return the identity's active membership in a Business, when it exists."""
    return BusinessMember.objects.filter(
        identity=identity,
        business=business,
        status=BusinessMember.Status.ACTIVE,
    ).first()


def can_manage_business(member):
    """Allow active owners and managers to perform Business management actions."""
    return member and member.role in {
        BusinessMember.Role.OWNER,
        BusinessMember.Role.MANAGER,
    }


def can_view_members(member):
    """Member visibility follows the existing Business management rule."""
    return can_manage_business(member)
