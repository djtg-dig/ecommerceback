from .models import BusinessMember

def membership_for(identity, business):
    return BusinessMember.objects.filter(identity=identity,business=business,status=BusinessMember.Status.ACTIVE).first()
def can_manage_business(member): return member and member.role in {BusinessMember.Role.OWNER,BusinessMember.Role.MANAGER}
def can_view_members(member): return can_manage_business(member)
