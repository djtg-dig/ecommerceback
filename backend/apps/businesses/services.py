from django.db import transaction
from .models import Business, BusinessMember

def create_business(identity, validated_data):
    with transaction.atomic():
        business=Business.objects.create(**validated_data)
        BusinessMember.objects.create(business=business,identity=identity,role=BusinessMember.Role.OWNER,status=BusinessMember.Status.ACTIVE)
        return business
