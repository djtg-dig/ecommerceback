"""Transactional business creation keeps ownership and category data consistent."""
from django.db import IntegrityError,transaction
from .identifiers import generate_business_public_id
from .models import Business,BusinessCategory,BusinessCategoryMembership,BusinessMember
MAX_PUBLIC_ID_ATTEMPTS=5
def create_business(identity,validated_data):
 """Create Business, its active OWNER and requested categories atomically; retry only ID collisions."""
 categories=validated_data.pop("categories",[]); primary=validated_data.pop("primary_category",None)
 active={c.code:c for c in BusinessCategory.objects.filter(code__in=categories,is_active=True)}
 if len(active)!=len(set(categories)) or (primary and primary not in active): raise ValueError("Invalid business categories.")
 for _ in range(MAX_PUBLIC_ID_ATTEMPTS):
  try:
   with transaction.atomic():
    b=Business.objects.create(public_id=generate_business_public_id(),**validated_data);BusinessMember.objects.create(business=b,identity=identity,role="OWNER",status="ACTIVE")
    for code,c in active.items():BusinessCategoryMembership.objects.create(business=b,category=c,is_primary=code==primary)
    return b
  except IntegrityError:
   continue
 raise RuntimeError("Unable to allocate business public identifier.")
def replace_categories(business,codes,primary):
 active={c.code:c for c in BusinessCategory.objects.filter(code__in=codes,is_active=True)}
 if len(active)!=len(set(codes)) or (primary and primary not in active):raise ValueError("Invalid business categories.")
 with transaction.atomic():
  BusinessCategoryMembership.objects.filter(business=business).delete()
  for code,c in active.items():BusinessCategoryMembership.objects.create(business=business,category=c,is_primary=code==primary)
