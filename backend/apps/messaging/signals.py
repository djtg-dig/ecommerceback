"""Nettoyage transactionnel des pièces jointes supprimées administrativement."""

from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Message


@receiver(post_delete, sender=Message)
def delete_private_attachment_after_commit(sender, instance, **kwargs):
    """Supprime le fichier seulement si la suppression SQL est définitivement validée."""
    if not instance.file:
        return
    storage = instance.file.storage
    name = instance.file.name
    transaction.on_commit(lambda: storage.delete(name) if storage.exists(name) else None)
