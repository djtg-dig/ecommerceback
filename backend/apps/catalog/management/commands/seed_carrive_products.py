"""Idempotent Carrive demonstration catalog seeder."""
from collections import Counter
from decimal import Decimal
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.migrations.executor import MigrationExecutor
from apps.accounts.models import CarriIdentity
from apps.businesses.models import BusinessMember
from apps.catalog.models import Product
from apps.catalog.registry import get_category, validate_registry
from apps.catalog.serializers import ProductVariantWriteSerializer, ProductWriteSerializer
from apps.catalog.services import create_product, create_variant
from apps.inventory.models import StockMovement
from apps.inventory.services import apply_stock_movement, create_inventory_item
OWNER_EMAIL="carrivemubaraka@gmail.com"; BUSINESS_NAME="Carrive"; PREFIX="CARRIVE-DEMO-"
DISTRIBUTION=(("televisions",10),("smartphones",10),("laptops",10),("game_consoles",8),("shoes",10),("clothing",10),("computer_accessories",8),("air_conditioners",8),("refrigerators",8),("printers",6),("washing_machines",6),("furniture",6))
NAMES={"televisions":("Téléviseur Samsung","Téléviseur LG"),"smartphones":("Smartphone Samsung Galaxy","Smartphone Tecno Spark"),"laptops":("HP EliteBook","Lenovo ThinkPad"),"game_consoles":("Console PlayStation","Console Xbox"),"shoes":("Chaussures Adidas","Chaussures Nike"),"clothing":("Chemise homme","T-shirt unisexe"),"computer_accessories":("Souris Logitech","Clavier HP"),"air_conditioners":("Climatiseur LG","Climatiseur Hisense"),"refrigerators":("Réfrigérateur Hisense","Réfrigérateur Samsung"),"printers":("Imprimante HP LaserJet","Imprimante Epson"),"washing_machines":("Machine à laver Samsung","Machine à laver LG"),"furniture":("Bureau en bois","Étagère en bois")}
def attrs(c,i):
 color=("Noir","Blanc","Bleu","Gris")[i%4]
 return {"televisions":{"brand":"Samsung","model":f"TV-{i}","screen_size":"43","display_technology":"LED","resolution":"4K","smart_tv":True,"operating_system":"WebOS","wifi":True,"bluetooth":True,"hdmi_ports":3,"usb_ports":2,"color":color},"smartphones":{"brand":"Samsung","model":f"Galaxy-{i}","screen_size":"6.6","ram":8,"battery_capacity":5000,"operating_system":"Android","network":"4G","sim_count":2,"esim":False,"main_camera":"50","color":color},"laptops":{"brand":"HP","model":f"Elite-{i}","processor":"Intel Core i5","storage_type":"SSD","screen_size":"15.6","resolution":"1920x1080","graphics":"Integrated","operating_system":"Windows 11","color":color},"game_consoles":{"manufacturer":"Sony","model":f"Console-{i}","generation":"Current","edition":"Standard","disc_drive":True,"color":color,"controllers_included":1},"shoes":{"brand":"Adidas","model":f"Run-{i}","shoe_type":"SNEAKERS","size_system":"EU","color":color,"material":"Textile","target_audience":"unisex"},"clothing":{"clothing_type":"SHIRT","brand":"Carrive Demo","size_system":"International","color":color,"material":"Coton","fit":"Regular","target_audience":"unisex"},"computer_accessories":{"accessory_type":"MOUSE","brand":"Logitech","model":f"ACC-{i}","connectivity":["USB","Bluetooth"],"compatibility":["Windows","macOS"],"power":"5","color":color},"air_conditioners":{"brand":"LG","model":f"AC-{i}","unit_type":"SPLIT","cooling_capacity":12000,"inverter":True,"power_consumption":"1100","voltage":"220","refrigerant":"R32","recommended_area":"25"},"refrigerators":{"brand":"Hisense","model":f"RF-{i}","unit_type":"Double porte","capacity":"250","door_count":2,"power_consumption":"180","inverter":True,"color":color},"printers":{"brand":"HP","model":f"Print-{i}","print_technology":"Laser","color_mode":"MONOCHROME","connectivity":["USB","Wi-Fi"],"paper_formats":["A4","Letter"]},"washing_machines":{"brand":"Samsung","model":f"Wash-{i}","capacity":"8","loading_type":"FRONT","spin_speed":1200,"power_consumption":"500"},"furniture":{"furniture_type":"Bureau","material":"Bois","dimensions":"120 x 60 x 75 cm","color":color,"assembly_required":True}}[c]
def variants(c): return {"smartphones":[{"storage":128},{"storage":256}],"laptops":[{"ram":8,"storage":256},{"ram":16,"storage":512}],"game_consoles":[{"storage":512},{"storage":1024}],"shoes":[{"size":"42"},{"size":"43"}],"clothing":[{"size":"M"},{"size":"L"}]}.get(c,[])
class Command(BaseCommand):
 help="Crée les 100 produits de démonstration Carrive sans doublon."
 def add_arguments(self,p): p.add_argument("--dry-run",action="store_true");p.add_argument("--count",type=int,default=100)
 def handle(self,*a,**o):
  if not 1<=o["count"]<=100: raise CommandError("--count doit être compris entre 1 et 100.")
  validate_registry();self.migrations();owner,business=self.target();plan=[(c,i) for c,n in DISTRIBUTION for i in range(1,n+1)][:o["count"]]
  self.stdout.write(f"Entreprise vérifiée : {business.name} ({business.public_id}); propriétaire : {owner.verified_email}");self.stdout.write(f"Répartition : {dict(Counter(c for c,_ in plan))}")
  if o["dry_run"]: made,skipped=self.run(owner,business,plan,True);self.stdout.write(self.style.SUCCESS(f"Dry-run valide : {made} à créer, {skipped} ignorés."));return
  with transaction.atomic(): made,skipped=self.run(owner,business,plan,False)
  self.stdout.write(self.style.SUCCESS(f"Terminé : {made} créés, {skipped} ignorés."))
 def migrations(self):
  e=MigrationExecutor(transaction.get_connection())
  if e.migration_plan(e.loader.graph.leaf_nodes()): raise CommandError("Des migrations sont en attente.")
 def target(self):
  users=list(CarriIdentity.objects.filter(verified_email__iexact=OWNER_EMAIL))
  if len(users)!=1: raise CommandError(f"Utilisateur attendu ambigu ou introuvable : {OWNER_EMAIL}.")
  rows=list(BusinessMember.objects.select_related("business").filter(identity=users[0],is_owner=True,status=BusinessMember.Status.ACTIVE,business__name=BUSINESS_NAME))
  if len(rows)!=1: raise CommandError(f"Entreprise Carrive ambiguë ou propriété non confirmée ({len(rows)} résultat(s)).")
  return users[0],rows[0].business
 def payload(self,c,i):
  ref=f"{PREFIX}{c.upper()}-{i:03d}"
  minimum=Decimal(25+i*17)
  return {"name":f"{NAMES[c][(i-1)%2]} Démo {i}","description":"Donnée de démonstration ; caractéristiques et prix non contractuels.","category_code":c,"internal_reference":ref,"min_price":minimum,"max_price":minimum+Decimal("10.00"),"is_negotiable":True,"cost_price":Decimal(15+i*10),"attributes":attrs(c,i),"status":"ACTIVE"}
 def run(self,owner,business,plan,dry):
  made=skipped=0
  for c,i in plan:
   if get_category(c) is None: raise CommandError(f"Catégorie inconnue : {c}.")
   data=self.payload(c,i)
   if Product.objects.filter(business=business,internal_reference=data["internal_reference"]).exists(): skipped+=1;continue
   s=ProductWriteSerializer(data=data,context={"business":business})
   if not s.is_valid(): raise CommandError(f"Produit invalide {data['internal_reference']} : {s.errors}")
   product=Product(business=business,**s.validated_data) if dry else create_product(business=business,values=dict(s.validated_data));targets=[]
   for j,value in enumerate(variants(c),1):
    v=ProductVariantWriteSerializer(data={"internal_reference":f"{data['internal_reference']}-V{j}","attributes":value},context={"product":product})
    if not v.is_valid(): raise CommandError(f"Variante invalide {data['internal_reference']} : {v.errors}")
    if not dry: targets.append(create_variant(product=product,values=dict(v.validated_data)))
   if not dry:
    for j,target in enumerate(targets or [product],1):
     item=create_inventory_item(business=business,product=target if target is product else None,variant=target if target is not product else None,low_stock_threshold=Decimal("3"));q=0 if i%5==0 and j==1 else (i*(j+2))%51
     if q: apply_stock_movement(inventory_item=item,movement_type=StockMovement.Type.IN,performed_by=owner,quantity=Decimal(q),reason="Stock initial de démonstration Carrive.",idempotency_key=f"{data['internal_reference']}-STOCK-{j}")
   made+=1
  return made,skipped
