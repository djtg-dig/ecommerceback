"""Charge le référentiel versionné des pays ISO 3166-1."""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.businesses.models import Country


DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "countries.json"


class Command(BaseCommand):
    help = "Importe ou actualise les pays depuis le référentiel ISO versionné."

    def handle(self, *args, **options):
        try:
            countries = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f"Référentiel des pays illisible : {exc}") from exc

        if not isinstance(countries, list):
            raise CommandError("Le référentiel des pays doit être une liste JSON.")

        seen_iso2 = set()
        for index, row in enumerate(countries, start=1):
            if not isinstance(row, dict):
                raise CommandError(f"Entrée {index} invalide : objet JSON attendu.")
            name = str(row.get("name", "")).strip()
            iso2 = str(row.get("iso2", "")).strip().upper()
            phone_code = str(row.get("phone_code", "")).strip()
            if not name or len(iso2) != 2 or not iso2.isalpha() or not phone_code.startswith("+"):
                raise CommandError(f"Entrée {index} invalide dans le référentiel des pays.")
            if iso2 in seen_iso2:
                raise CommandError(f"Le code ISO2 {iso2} est dupliqué dans le référentiel.")
            seen_iso2.add(iso2)

        created = updated = unchanged = 0
        with transaction.atomic():
            for row in countries:
                defaults = {
                    "name": row["name"].strip(),
                    "phone_code": row["phone_code"].strip(),
                }
                iso2 = row["iso2"].strip().upper()
                previous = Country.objects.filter(iso2=iso2).values("name", "phone_code").first()
                country, was_created = Country.objects.update_or_create(
                    iso2=iso2,
                    defaults=defaults,
                )
                if was_created:
                    created += 1
                elif previous == defaults:
                    unchanged += 1
                else:
                    updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Pays traités : {len(countries)} | créés : {created} | mis à jour : {updated} | inchangés : {unchanged}."
            )
        )
