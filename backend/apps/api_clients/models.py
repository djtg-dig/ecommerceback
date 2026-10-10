"""Application-level client registry and replay protection.

An ``ApiClient`` identifies the application calling the API, never the user.
It carries no secret: HMAC secrets live exclusively in the environment, so a
database compromise cannot disclose a signing key.

``ClientNonce`` makes signed requests single-use. The uniqueness constraint is
enforced by PostgreSQL, which keeps replay detection atomic across every
worker and every instance, unlike a per-process in-memory cache.
"""

import uuid

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone

from .identifiers import generate_api_client_public_id


class ApiClient(models.Model):
    """One application or service authorised to call the ecommerce API."""

    class ClientType(models.TextChoices):
        WEB = "WEB", "Web"
        MOBILE_ANDROID = "MOBILE_ANDROID", "Mobile Android"
        MOBILE_IOS = "MOBILE_IOS", "Mobile iOS"
        DESKTOP = "DESKTOP", "Desktop"
        PARTNER = "PARTNER", "Partner"
        INTERNAL_SERVICE = "INTERNAL_SERVICE", "Service interne"
        WORKER = "WORKER", "Worker"
        OTHER = "OTHER", "Autre"

    class AuthMethod(models.TextChoices):
        HMAC = "HMAC", "HMAC"
        PLAY_INTEGRITY = "PLAY_INTEGRITY", "Play Integrity"
        APP_ATTEST = "APP_ATTEST", "App Attest"
        PUBLIC_KEY = "PUBLIC_KEY", "Cle publique"
        OAUTH_CLIENT_CREDENTIALS = (
            "OAUTH_CLIENT_CREDENTIALS",
            "OAuth Client Credentials",
        )
        MTLS = "MTLS", "mTLS"
        NONE = "NONE", "Aucune"
        OTHER = "OTHER", "Autre"

    client_id_validator = RegexValidator(
        regex=r"^[a-z0-9][a-z0-9_-]*[a-z0-9]$|^[a-z0-9]$",
        message=(
            "Le client_id doit contenir uniquement des lettres minuscules, "
            "des chiffres, des tirets ou des underscores, sans separateur aux extremites."
        ),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reference = models.CharField(
        "reference",
        max_length=12,
        unique=True,
        db_index=True,
        editable=False,
        help_text="Reference publique unique du client applicatif, format AC + 10 caracteres.",
    )
    name = models.CharField(
        "nom",
        max_length=150,
        help_text="Nom humain du client applicatif, par exemple Ecommerce Web.",
    )
    client_id = models.CharField(
        "client_id",
        max_length=80,
        unique=True,
        db_index=True,
        validators=[client_id_validator],
        help_text="Identifiant technique stable envoye dans X-Ecommerce-Client-Id.",
    )
    client_type = models.CharField(
        "type de client",
        max_length=40,
        choices=ClientType.choices,
        default=ClientType.OTHER,
        help_text="Famille applicative du client consommateur.",
    )
    auth_method = models.CharField(
        "methode d'authentification",
        max_length=40,
        choices=AuthMethod.choices,
        default=AuthMethod.HMAC,
        help_text="Methode attendue pour authentifier ce client.",
    )
    is_active = models.BooleanField(
        "actif",
        default=True,
        help_text="Permet de revoquer un client sans supprimer son historique.",
    )
    description = models.TextField(
        "description",
        blank=True,
        default="",
        help_text="Informations non sensibles sur l'usage du client.",
    )
    metadata = models.JSONField(
        "metadata",
        blank=True,
        default=dict,
        help_text="Metadonnees non sensibles reservees aux futurs besoins.",
    )
    last_seen_at = models.DateTimeField(
        "derniere utilisation",
        blank=True,
        null=True,
        help_text="Derniere authentification client reussie.",
    )
    created_at = models.DateTimeField("date de creation", auto_now_add=True)
    updated_at = models.DateTimeField("date de derniere modification", auto_now=True)

    class Meta:
        verbose_name = "client applicatif API"
        verbose_name_plural = "clients applicatifs API"
        ordering = ["name", "client_id"]
        indexes = [
            models.Index(fields=["client_id"], name="api_client_client_id_idx"),
            models.Index(
                fields=["is_active", "auth_method"],
                name="api_client_auth_idx",
            ),
        ]

    def save(self, *args, **kwargs):
        """Generate the public reference without touching an existing one."""
        if self._state.adding:
            if not self.reference:
                self.reference = generate_api_client_public_id()
        elif not self.reference:
            self.reference = (
                type(self).objects.only("reference").get(pk=self.pk).reference
            )

        super().save(*args, **kwargs)

    def clean(self):
        """Reject an HMAC client type that cannot hold a server-side secret."""
        if self.auth_method == self.AuthMethod.HMAC and self.client_type in {
            self.ClientType.MOBILE_ANDROID,
            self.ClientType.MOBILE_IOS,
        }:
            raise ValidationError(
                {
                    "auth_method": (
                        "Un client mobile public ne peut pas utiliser un secret HMAC "
                        "partage : choisissez une autre methode d'authentification."
                    )
                }
            )

    def __str__(self):
        return f"{self.name} ({self.client_id})"


class ClientNonce(models.Model):
    """One recorded nonce of one signed request, unique per client."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client = models.ForeignKey(
        ApiClient,
        on_delete=models.CASCADE,
        related_name="nonces",
    )
    nonce = models.CharField(max_length=128)
    seen_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        verbose_name = "nonce client"
        verbose_name_plural = "nonces clients"
        ordering = ["-seen_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["client", "nonce"],
                name="unique_client_nonce",
            ),
        ]

    def __str__(self):
        return f"{self.client_id}:{self.nonce}"

    @classmethod
    def record(cls, client, nonce):
        """Record one nonce, returning False when it has already been used.

        The unique constraint on ``(client, nonce)`` is the atomic replay
        guard: a concurrent duplicate insert raises ``IntegrityError`` in the
        database rather than in application code, so no lock or shared cache
        is required and the behaviour is identical across workers.
        """

        from django.db import IntegrityError

        try:
            cls.objects.create(client=client, nonce=nonce)
        except IntegrityError:
            return False
        return True

    @classmethod
    def purge_expired(cls, *, retention_seconds):
        """Delete nonces older than ``retention_seconds`` and return the count."""

        if retention_seconds <= 0:
            raise ValidationError(
                {"retention_seconds": "La conservation doit etre positive."}
            )
        cutoff = timezone.now() - timezone.timedelta(seconds=retention_seconds)
        deleted, _details = cls.objects.filter(seen_at__lt=cutoff).delete()
        return deleted
