"""Local development settings."""

from .base import *  # noqa: F403

DEBUG = True
SECRET_KEY = SECRET_KEY or "django-insecure-development-only-not-for-production"  # noqa: F405
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1", "testserver"])  # noqa: F405
