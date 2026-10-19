"""Safely inspect the media-storage configuration without uploading a file."""

import os

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Diagnose la configuration Cloudinary sans afficher de secret ni téléverser de média."

    def add_arguments(self, parser):
        parser.add_argument(
            "--verify",
            action="store_true",
            help="Effectue un ping Cloudinary authentifié, sans créer de ressource.",
        )

    def handle(self, *args, **options):
        individual = {
            "cloud_name": bool(os.getenv("CLOUDINARY_CLOUD_NAME")),
            "api_key": bool(os.getenv("CLOUDINARY_API_KEY")),
            "api_secret": bool(os.getenv("CLOUDINARY_API_SECRET")),
        }
        url_present = bool(os.getenv("CLOUDINARY_URL"))
        self.stdout.write(f"configured={settings.CLOUDINARY_ENABLED}")
        self.stdout.write(f"cloud_name={settings.CLOUDINARY_CLOUD_NAME or '<absent>'}")
        self.stdout.write("active_source=individual environment variables")
        self.stdout.write(f"individual_present={all(individual.values())}")
        self.stdout.write(f"cloudinary_url_present={url_present}")
        if url_present:
            self.stdout.write(self.style.WARNING("CLOUDINARY_URL est présent mais les uploads e-commerce configurent explicitement les variables individuelles."))
        if not all(individual.values()):
            self.stdout.write(self.style.ERROR("Configuration incomplète : renseignez les trois variables individuelles."))
            return
        if not options["verify"]:
            self.stdout.write("Aucun appel Cloudinary effectué. Utilisez --verify pour un ping authentifié sans upload.")
            return
        try:
            import cloudinary
            import cloudinary.api

            cloudinary.config(
                cloud_name=settings.CLOUDINARY_CLOUD_NAME,
                api_key=settings.CLOUDINARY_API_KEY,
                api_secret=settings.CLOUDINARY_API_SECRET,
                secure=True,
            )
            cloudinary.api.ping()
        except Exception:
            self.stdout.write(self.style.ERROR("Le ping Cloudinary a échoué. Vérifiez la paire cloud_name / clé API / secret et les droits de la clé."))
            return
        self.stdout.write(self.style.SUCCESS("Le ping Cloudinary authentifié a réussi. Ce contrôle ne vérifie pas le droit de création."))
