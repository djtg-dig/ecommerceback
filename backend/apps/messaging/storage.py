"""Stockage privé des pièces jointes, sans URL publique."""

from django.conf import settings
from django.core.files.storage import FileSystemStorage, Storage
from django.utils.deconstruct import deconstructible


@deconstructible
class PrivateMessagingStorage(Storage):
    """Délègue au système de fichiers privé configuré au moment de l'appel."""

    @staticmethod
    def _backend() -> FileSystemStorage:
        return FileSystemStorage(
            location=settings.MESSAGING_PRIVATE_MEDIA_ROOT,
            base_url=None,
        )

    def _open(self, name, mode="rb"):
        return self._backend().open(name, mode)

    def _save(self, name, content):
        return self._backend().save(name, content)

    def delete(self, name):
        return self._backend().delete(name)

    def exists(self, name):
        return self._backend().exists(name)

    def size(self, name):
        return self._backend().size(name)

    def path(self, name):
        return self._backend().path(name)

    def url(self, name):
        raise ValueError("Les pièces jointes privées ne possèdent pas d'URL publique.")
