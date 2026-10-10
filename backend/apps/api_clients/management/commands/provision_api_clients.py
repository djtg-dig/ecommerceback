"""Provision the registered application clients.

The command is idempotent: it may run on every deployment and never reads,
writes or prints a secret. Secrets stay in the environment, so the registry can
be provisioned before any key is distributed.
"""

from django.core.management.base import BaseCommand

from apps.api_clients.models import ApiClient


# Confidential BFF client of the future Next.js server. A mobile client is
# deliberately absent: a shared HMAC secret embedded in an application is
# extractible, so Flutter keeps JWT + PKCE S256 only.
PROVISIONED_CLIENTS = (
    {
        "name": "Ecommerce Web",
        "client_id": "ecommerce-web",
        "client_type": ApiClient.ClientType.WEB,
        "auth_method": ApiClient.AuthMethod.HMAC,
        "is_active": True,
        "description": (
            "Backend for Frontend Next.js. Client confidentiel serveur a serveur "
            "qui signe les routes reservees au BFF."
        ),
    },
)


class Command(BaseCommand):
    help = (
        "Cree ou met a jour les clients applicatifs enregistres, sans jamais "
        "manipuler de secret. Idempotent, executable a chaque deploiement."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--deactivate-unknown",
            action="store_true",
            help=(
                "Desactive les clients HMAC enregistres qui ne sont plus "
                "provisionnes par cette commande."
            ),
        )

    def handle(self, *args, **options):
        from django.conf import settings

        provisioned_ids = set()

        for attributes in PROVISIONED_CLIENTS:
            client_id = attributes["client_id"]
            provisioned_ids.add(client_id)
            client, created = ApiClient.objects.update_or_create(
                client_id=client_id,
                defaults=attributes,
            )
            verb = "créé" if created else "à jour"
            configured = self._secret_is_configured(client_id)
            self.stdout.write(
                self.style.SUCCESS(
                    f"{client.name} ({client_id}, {client.reference}) {verb}."
                )
            )
            if not configured:
                self.stdout.write(
                    self.style.WARNING(
                        f"  Aucun secret HMAC n'est configure pour {client_id} : "
                        "la signature sera refusee tant qu'aucune cle n'est "
                        "distribuee."
                    )
                )
            if client.auth_method == ApiClient.AuthMethod.HMAC and (
                client.client_type
                in {
                    ApiClient.ClientType.MOBILE_ANDROID,
                    ApiClient.ClientType.MOBILE_IOS,
                }
            ):
                self.stdout.write(
                    self.style.ERROR(
                        f"  {client_id} est un client mobile public et ne doit "
                        "pas utiliser HMAC."
                    )
                )

        if options["deactivate_unknown"]:
            stale = ApiClient.objects.filter(
                auth_method=ApiClient.AuthMethod.HMAC,
                is_active=True,
            ).exclude(client_id__in=provisioned_ids)
            for client in stale:
                client.is_active = False
                client.save(update_fields=["is_active"])
                self.stdout.write(
                    self.style.WARNING(
                        f"{client.client_id} desactive (plus provisionne)."
                    )
                )

    @staticmethod
    def _secret_is_configured(client_id):
        """Return whether an environment secret exists, without reading it."""

        from django.conf import settings

        mapping = getattr(settings, "ECOMMERCE_HMAC_CLIENT_SECRETS", {})
        entry = mapping.get(client_id) if isinstance(mapping, dict) else None
        if not isinstance(entry, (dict, str)):
            return False
        current = entry.get("current", "") if isinstance(entry, dict) else entry
        return bool(current)
