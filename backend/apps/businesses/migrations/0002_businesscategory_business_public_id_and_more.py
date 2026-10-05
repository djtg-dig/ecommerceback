import uuid
from django.db import migrations,models
import django.db.models.deletion

def public_id():
 import secrets
 a='23456789ABCDEFGHJKLMNPQRSTUVWXYZ';return 'SH'+''.join(secrets.choice(a) for _ in range(10))
def backfill(apps,schema_editor):
 B=apps.get_model('businesses','Business')
 for b in B.objects.filter(public_id__isnull=True):
  while True:
   v=public_id()
   if not B.objects.filter(public_id=v).exists():b.public_id=v;b.save(update_fields=['public_id']);break
def seed(apps,schema_editor):
 C=apps.get_model('businesses','BusinessCategory')
 for code,name in [('GENERAL_STORE','Alimentation générale'),('SUPERMARKET','Supermarché'),('PHARMACY','Pharmacie'),('FASHION','Mode / Habillement'),('ELECTRONICS','Électronique'),('PHONES','Téléphonie'),('COMPUTERS','Informatique'),('HARDWARE','Quincaillerie'),('BEAUTY','Beauté et soins'),('RESTAURANT','Restaurant'),('BAKERY','Boulangerie'),('BOOKSTORE','Librairie'),('AUTO_PARTS','Pièces automobiles'),('FURNITURE','Meubles'),('AGRICULTURE','Agriculture'),('OTHER','Autre')]:C.objects.get_or_create(code=code,defaults={'name':name,'slug':code.lower().replace('_','-')})
class Migration(migrations.Migration):
 dependencies=[('businesses','0001_initial')]
 operations=[migrations.CreateModel(name='BusinessCategory',fields=[('id',models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False,serialize=False)),('code',models.CharField(max_length=40,unique=True)),('name',models.CharField(max_length=120)),('slug',models.SlugField(unique=True)),('description',models.TextField(blank=True)),('is_active',models.BooleanField(default=True)),('created_at',models.DateTimeField(auto_now_add=True)),('updated_at',models.DateTimeField(auto_now=True))],options={'ordering':['name']}),migrations.AddField(model_name='business',name='public_id',field=models.CharField(max_length=12,unique=True,null=True,editable=False,db_index=True)),migrations.RunPython(backfill,migrations.RunPython.noop),migrations.AlterField(model_name='business',name='public_id',field=models.CharField(max_length=12,unique=True,editable=False,db_index=True)),migrations.CreateModel(name='BusinessCategoryMembership',fields=[('id',models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False,serialize=False)),('is_primary',models.BooleanField(default=False)),('created_at',models.DateTimeField(auto_now_add=True)),('business',models.ForeignKey(to='businesses.business',on_delete=django.db.models.deletion.PROTECT,related_name='category_memberships')),('category',models.ForeignKey(to='businesses.businesscategory',on_delete=django.db.models.deletion.PROTECT,related_name='business_memberships'))]),migrations.AddConstraint(model_name='businesscategorymembership',constraint=models.UniqueConstraint(fields=('business','category'),name='unique_business_category')),migrations.AddConstraint(model_name='businesscategorymembership',constraint=models.UniqueConstraint(fields=('business',),condition=models.Q(('is_primary',True)),name='one_primary_business_category')),migrations.RunPython(seed,migrations.RunPython.noop)]
