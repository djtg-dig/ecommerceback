import hashlib
import secrets
import uuid
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class CarriIdentity(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    carri_subject = models.CharField(max_length=255, unique=True)
    linked_at = models.DateTimeField(auto_now_add=True)
    last_login_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["carri_subject"]

    @property
    def is_authenticated(self):
        return True

    @property
    def is_active(self):
        return True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            original = type(self).objects.only("carri_subject").get(pk=self.pk)
            if original.carri_subject != self.carri_subject:
                raise ValidationError("carri_subject is immutable.")
        super().save(*args, **kwargs)

    def __str__(self):
        return self.carri_subject


class OAuthLoginAttempt(models.Model):
    state_hash = models.CharField(max_length=64, unique=True, editable=False)
    nonce = models.CharField(max_length=255)
    code_verifier = models.CharField(max_length=128)
    redirect_uri = models.URLField(max_length=500)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @classmethod
    def create(cls, *, state, nonce, code_verifier, redirect_uri, lifetime_seconds=600):
        return cls.objects.create(
            state_hash=hashlib.sha256(state.encode()).hexdigest(),
            nonce=nonce,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
            expires_at=timezone.now() + timedelta(seconds=lifetime_seconds),
        )

    @property
    def is_usable(self):
        return self.consumed_at is None and self.expires_at > timezone.now()


class IDTokenReplay(models.Model):
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)


class OAuthHandoff(models.Model):
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    identity = models.ForeignKey(CarriIdentity, on_delete=models.CASCADE, related_name="handoffs")
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @classmethod
    def create_for(cls, identity, lifetime_seconds=120):
        token = secrets.token_urlsafe(32)
        cls.objects.create(
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            identity=identity,
            expires_at=timezone.now() + timedelta(seconds=lifetime_seconds),
        )
        return token

    @property
    def is_usable(self):
        return self.consumed_at is None and self.expires_at > timezone.now()
