"""Audite les anciennes adresses texte et effectue une conversion explicitement validée."""

import json

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, transaction

from apps.businesses.models import Address, Business, Country


class Command(BaseCommand):
    help = "Audite les adresses texte historiques des entreprises sans les modifier par défaut."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Convertit une entreprise explicitement ciblée.")
        parser.add_argument("--business-public-id", help="Référence publique de l'entreprise à convertir.")
        parser.add_argument("--country-iso2", help="Pays confirmé manuellement pour cette conversion.")
        parser.add_argument("--json", action="store_true", help="Produit le rapport au format JSON.")

    @staticmethod
    def _businesses():
        try:
            return list(
                Business.objects.order_by("public_id").only(
                    "id", "public_id", "address", "structured_address"
                )
            )
        except DatabaseError as exc:
            raise CommandError("Impossible de lire la base de données pour auditer les adresses.") from exc

    def handle(self, *args, **options):
        apply = options["apply"]
        public_id = (options.get("business_public_id") or "").strip()
        country_iso2 = (options.get("country_iso2") or "").strip().upper()
        if apply and (not public_id or not country_iso2):
            raise CommandError("--apply exige --business-public-id et --country-iso2.")
        if not apply and (public_id or country_iso2):
            raise CommandError("Les options de ciblage sont réservées à une conversion avec --apply.")

        businesses = self._businesses()
        report = {
            "analysed": len(businesses),
            "already_structured": 0,
            "converted": 0,
            "requires_manual_review": 0,
            "without_address": 0,
            "manual_review_public_ids": [],
        }

        converted = False
        if apply:
            country = Country.objects.filter(iso2=country_iso2).first()
            if country is None:
                raise CommandError(f"Pays ISO2 inconnu : {country_iso2}.")
            business = next((item for item in businesses if item.public_id == public_id), None)
            if business is None:
                raise CommandError("Entreprise introuvable.")
            with transaction.atomic():
                business = Business.objects.select_for_update().get(pk=business.pk)
                legacy_address = business.address.strip()
                if business.structured_address_id:
                    pass
                elif not legacy_address:
                    pass
                else:
                    # Le pays est fourni par un opérateur après vérification :
                    # aucun pays, ville ou subdivision n'est inféré du texte.
                    business.structured_address = Address.objects.create(
                        country=country,
                        additional_information=legacy_address,
                    )
                    business.save(update_fields=("structured_address", "updated_at"))
                    converted = True

            businesses = self._businesses()

        for business in businesses:
            if business.structured_address_id:
                report["already_structured"] += 1
            elif not business.address.strip():
                report["without_address"] += 1
            else:
                report["requires_manual_review"] += 1
                report["manual_review_public_ids"].append(business.public_id)

        if converted:
            report["converted"] = 1
            report["already_structured"] -= 1

        if options["json"]:
            self.stdout.write(json.dumps(report, ensure_ascii=False, sort_keys=True))
            return
        self.stdout.write(
            "Entreprises analysées : {analysed} | déjà structurées : {already_structured} | "
            "converties : {converted} | à vérifier : {requires_manual_review} | sans adresse : {without_address}.".format(**report)
        )
        if report["manual_review_public_ids"]:
            self.stdout.write("Intervention manuelle requise : " + ", ".join(report["manual_review_public_ids"]))
