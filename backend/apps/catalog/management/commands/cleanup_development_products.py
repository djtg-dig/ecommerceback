"""Safely inspect and remove only explicitly-marked development products."""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.businesses.models import Business
from apps.catalog.models import Product
from apps.inventory.models import InventoryItem, StockMovement
from apps.purchases.models import PurchaseLine
from apps.sales.models import SaleLine


DEMO_REFERENCE_PREFIX = "CARRIVE-DEMO-"
DEMO_DESCRIPTION = "Donnée de démonstration ; caractéristiques et prix non contractuels."


class Command(BaseCommand):
    help = "Inspecte ou supprime, de façon transactionnelle, les seuls produits de démonstration explicitement marqués."

    def add_arguments(self, parser):
        parser.add_argument("--business-id", required=True, help="Identifiant public exact de l’entreprise de développement.")
        parser.add_argument("--dry-run", action="store_true", help="Affiche le plan et les dépendances sans modifier de donnée.")
        parser.add_argument("--confirm", action="store_true", help="Confirme une suppression réelle après revue du dry-run.")

    def _candidates(self, business):
        return Product.objects.filter(
            business=business,
            internal_reference__startswith=DEMO_REFERENCE_PREFIX,
            description=DEMO_DESCRIPTION,
        ).only("id", "public_id", "internal_reference", "description").prefetch_related("variants")

    def _dependencies(self, product):
        variants = list(product.variants.all())
        variant_ids = [variant.pk for variant in variants]
        inventory = list(InventoryItem.objects.filter(product=product)) + list(InventoryItem.objects.filter(variant_id__in=variant_ids))
        inventory_ids = [item.pk for item in inventory]
        return {
            "variants": variants,
            "inventory_items": inventory,
            "stock_movements": list(StockMovement.objects.filter(inventory_item_id__in=inventory_ids)),
            "purchase_lines": list(PurchaseLine.objects.filter(product=product)) + list(PurchaseLine.objects.filter(variant_id__in=variant_ids)),
            "sale_lines": list(SaleLine.objects.filter(product=product)) + list(SaleLine.objects.filter(variant_id__in=variant_ids)),
        }

    @staticmethod
    def _ids(values):
        return ", ".join(str(value.public_id) for value in values) or "aucun"

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Cette commande est réservée à DEBUG=True.")
        if options["dry_run"] and options["confirm"]:
            raise CommandError("Utilisez soit --dry-run, soit --confirm.")
        if not options["dry_run"] and not options["confirm"]:
            raise CommandError("Exécutez d’abord avec --dry-run; la suppression exige ensuite --confirm.")

        business = Business.objects.filter(public_id=options["business_id"]).first()
        if business is None:
            raise CommandError("Entreprise introuvable.")
        candidates = list(self._candidates(business))
        self.stdout.write(f"Entreprise ciblée : {business.name} ({business.public_id})")
        self.stdout.write(f"Produits de démonstration explicitement marqués : {len(candidates)}")

        deletable = []
        blocked = []
        for product in candidates:
            dependencies = self._dependencies(product)
            has_dependencies = any(dependencies[name] for name in ("inventory_items", "stock_movements", "purchase_lines", "sale_lines"))
            details = "; ".join(
                f"{name}={len(values)} [{self._ids(values)}]" for name, values in dependencies.items()
            )
            if has_dependencies:
                blocked.append(product)
                self.stdout.write(self.style.WARNING(f"BLOQUÉ {product.public_id} ({product.internal_reference}) : {details}"))
            else:
                deletable.append(product)
                self.stdout.write(f"SUPPRIMABLE {product.public_id} ({product.internal_reference}) : {details}")

        self.stdout.write(f"Bilan : {len(deletable)} supprimable(s), {len(blocked)} bloqué(s), aucune opération commerciale ou comptable ne sera supprimée.")
        if options["dry_run"]:
            return
        if blocked:
            raise CommandError("Suppression annulée : au moins un produit a des dépendances protégées. Corrigez ou recréez uniquement les données de démonstration non référencées.")
        with transaction.atomic():
            # Variants are cascade-owned by a product; candidates are otherwise dependency-free.
            Product.objects.filter(pk__in=[product.pk for product in deletable]).delete()
        self.stdout.write(self.style.SUCCESS(f"{len(deletable)} produit(s) de démonstration supprimé(s) transactionnellement."))
