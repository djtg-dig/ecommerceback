"""Shared Django settings for all environments."""

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = BACKEND_DIR.parent
load_dotenv(PROJECT_DIR / ".env")


def env_list(name: str, default: list[str] | None = None) -> list[str]:
    """Return a comma-separated environment variable as a clean list."""
    value = os.getenv(name, "")
    if not value:
        return default or []
    return [item.strip() for item in value.split(",") if item.strip()]


SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "")
DEBUG = False
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "django_filters",
    "rest_framework",
    "drf_spectacular",
    "apps.accounts.apps.AccountsConfig",
    "apps.businesses.apps.BusinessesConfig",
    "apps.catalog.apps.CatalogConfig",
    "apps.inventory.apps.InventoryConfig",
    "apps.purchases.apps.PurchasesConfig",
    "apps.sales.apps.SalesConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
TEMPLATES = [{"BACKEND": "django.template.backends.django.DjangoTemplates", "DIRS": [], "APP_DIRS": True, "OPTIONS": {"context_processors": ["django.template.context_processors.request", "django.contrib.auth.context_processors.auth", "django.contrib.messages.context_processors.messages"]}}]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {"default": {"ENGINE": "django.db.backends.postgresql", "NAME": os.getenv("POSTGRES_DB", ""), "USER": os.getenv("POSTGRES_USER", ""), "PASSWORD": os.getenv("POSTGRES_PASSWORD", ""), "HOST": os.getenv("POSTGRES_HOST", ""), "PORT": os.getenv("POSTGRES_PORT", "5432")}}
AUTH_PASSWORD_VALIDATORS = []
LANGUAGE_CODE = "fr"
TIME_ZONE = "Africa/Kinshasa"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")
CORS_ALLOW_CREDENTIALS = False

REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend", "rest_framework.filters.SearchFilter", "rest_framework.filters.OrderingFilter"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

# OAuth 2.0 / OpenID Connect settings for the future Carri Account integration.
# Endpoint values remain optional because OIDC discovery should be preferred.
CARRI_ACCOUNT_ISSUER = os.getenv("CARRI_ACCOUNT_ISSUER", "")
CARRI_ACCOUNT_CLIENT_ID = os.getenv("CARRI_ACCOUNT_CLIENT_ID", "")
CARRI_ACCOUNT_CLIENT_SECRET = os.getenv("CARRI_ACCOUNT_CLIENT_SECRET", "")
CARRI_ACCOUNT_REDIRECT_URI = os.getenv("CARRI_ACCOUNT_REDIRECT_URI", "")

CARRI_ACCOUNT_ANDROID_CLIENT_ID = os.getenv("CARRI_ACCOUNT_ANDROID_CLIENT_ID", "")
CARRI_ACCOUNT_ANDROID_REDIRECT_URI = os.getenv("CARRI_ACCOUNT_ANDROID_REDIRECT_URI", "")
CARRI_ACCOUNT_DISCOVERY_CACHE_SECONDS = int(os.getenv("CARRI_ACCOUNT_DISCOVERY_CACHE_SECONDS", "300"))
CARRI_ACCOUNT_JWKS_CACHE_SECONDS = int(os.getenv("CARRI_ACCOUNT_JWKS_CACHE_SECONDS", "300"))
CARRI_ACCOUNT_ID_TOKEN_CLOCK_SKEW_SECONDS = int(os.getenv("CARRI_ACCOUNT_ID_TOKEN_CLOCK_SKEW_SECONDS", "60"))
CARRI_ACCOUNT_HTTP_TIMEOUT_SECONDS = int(os.getenv("CARRI_ACCOUNT_HTTP_TIMEOUT_SECONDS", "10"))
CARRI_ACCOUNT_OAUTH_ATTEMPT_TTL_SECONDS = int(os.getenv("CARRI_ACCOUNT_OAUTH_ATTEMPT_TTL_SECONDS", "600"))
CARRI_ACCOUNT_HANDOFF_TTL_SECONDS = int(os.getenv("CARRI_ACCOUNT_HANDOFF_TTL_SECONDS", "120"))

REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"] = ["apps.accounts.authentication.EcommerceJWTAuthentication"]
ECOMMERCE_IDENTITY_CLAIM = "identity_id"

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": __import__("datetime").timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": __import__("datetime").timedelta(days=30),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": False,
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": ECOMMERCE_IDENTITY_CLAIM,
}


SPECTACULAR_SETTINGS = {
    "TITLE": "Ecommerce API",
    "DESCRIPTION": "API métier multi-tenant. Carri Account fournit l’identité ; les appels protégés utilisent les JWT émis par ecommerce.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "ENUM_NAME_OVERRIDES": {
        "BusinessCurrencyEnum": "apps.businesses.models.Business.Currency",
        "ProductStatusEnum": "apps.catalog.models.Product.Status",
    },
    "TAGS": [
        {"name": "Health", "description": "Liveness technique publique."},
        {"name": "Authentication", "description": "Intégration Carri Account et JWT ecommerce."},
        {"name": "Businesses", "description": "Commerces accessibles à l’identité authentifiée."},
        {"name": "Business Categories", "description": "Taxonomie globale des activités commerciales."},
        {"name": "Product Categories", "description": "Taxonomie globale des produits et attributs effectifs."},
        {"name": "Products", "description": "Catalogue produit isolé par commerce."},
        {"name": "Product Variants", "description": "Combinaisons de variantes d’un produit."},
        {"name": "Inventory", "description": "Quantités disponibles isolées par commerce."},
        {"name": "Stock Movements", "description": "Historique immuable des entrées, sorties et ajustements."},
        {"name": "Suppliers", "description": "Fournisseurs isolés par commerce."},
        {"name": "Purchases", "description": "Approvisionnements et réceptions atomiques."},
        {"name": "Customers", "description": "Clients internes d’un commerce."},
        {"name": "Sales", "description": "Ventes internes/POS."},
    ],
}
