"""Delete application client nonces older than the replay window."""

from django.core.management.base import BaseCommand

from apps.api_clients.models import ClientNonce


class Command(BaseCommand):
    help = (
        "Purge les nonces clients expires. La conservation depasse toujours "
        "la fenetre de tolerance d'horloge afin qu'un nonce rejoué reste "
        "detectable."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--seconds",
            type=int,
            default=None,
            help=(
                "Conservation en secondes. Par defaut, la valeur de "
                "ECOMMERCE_HMAC_NONCE_TTL_SECONDS."
            ),
        )

    def handle(self, *args, **options):
        retention = options["seconds"]
        if retention is None:
            from django.conf import settings

            retention = int(getattr(settings, "ECOMMERCE_HMAC_NONCE_TTL_SECONDS", 900))

        deleted = ClientNonce.purge_expired(retention_seconds=retention)
        self.stdout.write(
            self.style.SUCCESS(f"{deleted} nonce(s) purgé(s).")
        )
