import uuid
from django.core.exceptions import ValidationError
from django.db import models
from apps.accounts.models import CarriIdentity

class Business(models.Model):
    class Status(models.TextChoices): ACTIVE="ACTIVE", "Active"; SUSPENDED="SUSPENDED", "Suspended"; ARCHIVED="ARCHIVED", "Archived"
    class Currency(models.TextChoices): CDF="CDF", "CDF"; USD="USD", "USD"
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    name=models.CharField(max_length=180); description=models.TextField(blank=True); address=models.TextField(blank=True); zone=models.CharField(max_length=120,blank=True)
    primary_currency=models.CharField(max_length=3,choices=Currency.choices,default=Currency.CDF); phone=models.CharField(max_length=40,blank=True)
    status=models.CharField(max_length=12,choices=Status.choices,default=Status.ACTIVE)
    created_at=models.DateTimeField(auto_now_add=True); updated_at=models.DateTimeField(auto_now=True)
    class Meta: ordering=["name"]

class BusinessMember(models.Model):
    class Role(models.TextChoices): OWNER="OWNER", "Owner"; MANAGER="MANAGER", "Manager"; EMPLOYEE="EMPLOYEE", "Employee"
    class Status(models.TextChoices): ACTIVE="ACTIVE", "Active"; SUSPENDED="SUSPENDED", "Suspended"
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    identity=models.ForeignKey(CarriIdentity,on_delete=models.PROTECT,related_name="business_memberships")
    business=models.ForeignKey(Business,on_delete=models.PROTECT,related_name="members")
    role=models.CharField(max_length=10,choices=Role.choices); status=models.CharField(max_length=10,choices=Status.choices,default=Status.ACTIVE)
    joined_at=models.DateTimeField(auto_now_add=True); updated_at=models.DateTimeField(auto_now=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=["identity","business"],name="unique_business_identity")]
    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def clean(self):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            old=type(self).objects.get(pk=self.pk)
            removing_owner=old.role==self.Role.OWNER and old.status==self.Status.ACTIVE and (self.role!=self.Role.OWNER or self.status!=self.Status.ACTIVE)
            if removing_owner and not type(self).objects.filter(business=self.business,role=self.Role.OWNER,status=self.Status.ACTIVE).exclude(pk=self.pk).exists():
                raise ValidationError("A business must retain an active owner.")
