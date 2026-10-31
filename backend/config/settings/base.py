"""Shared Django settings for all environments."""

import os
import sys
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


def env_bool(name: str, default: bool = False) -> bool:
    """Read an explicit boolean environment variable."""
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be an explicit boolean value.")


SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "")
DEBUG = False
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS")

INSTALLED_APPS = [
    "daphne",
    "channels",
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
    "apps.api_clients.apps.ApiClientsConfig",
    "apps.businesses.apps.BusinessesConfig",
    "apps.catalog.apps.CatalogConfig",
    "apps.carts.apps.CartsConfig",
    "apps.inventory.apps.InventoryConfig",
    "apps.purchases.apps.PurchasesConfig",
    "apps.sales.apps.SalesConfig",
    "apps.receivables.apps.ReceivablesConfig",
    "apps.expenses.apps.ExpensesConfig",
    "apps.finance.apps.FinanceConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.api_clients.middleware.EcommerceClientHMACMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "redact_carri_oauth_query": {
            "()": "apps.accounts.logging.OAuthQueryStringRedactionFilter",
        },
    },
    "loggers": {
        "django.request": {"filters": ["redact_carri_oauth_query"]},
        "django.server": {"filters": ["redact_carri_oauth_query"]},
    },
}

ROOT_URLCONF = "config.urls"
TEMPLATES = [{"BACKEND": "django.template.backends.django.DjangoTemplates", "DIRS": [], "APP_DIRS": True, "OPTIONS": {"context_processors": ["django.template.context_processors.request", "django.contrib.auth.context_processors.auth", "django.contrib.messages.context_processors.messages"]}}]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"


def redis_channel_layer(redis_url: str) -> dict[str, dict[str, object]]:
    """Construit la couche Channels sans interpréter ni journaliser l'URL Redis."""
    return {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {
                "hosts": [redis_url],
                "prefix": os.getenv("REDIS_CHANNEL_PREFIX", "ecommerce"),
            },
        }
    }


REDIS_URL = os.getenv("REDIS_URL", "").strip()
CHANNEL_LAYERS = redis_channel_layer(REDIS_URL) if REDIS_URL else {}
WEBSOCKET_ALLOWED_ORIGINS = env_list("WEBSOCKET_ALLOWED_ORIGINS")

DATABASES = {"default": {"ENGINE": "django.db.backends.postgresql", "NAME": os.getenv("POSTGRES_DB", ""), "USER": os.getenv("POSTGRES_USER", ""), "PASSWORD": os.getenv("POSTGRES_PASSWORD", ""), "HOST": os.getenv("POSTGRES_HOST", ""), "PORT": os.getenv("POSTGRES_PORT", "5432")}}
AUTH_PASSWORD_VALIDATORS = []
LANGUAGE_CODE = "fr"
TIME_ZONE = "Africa/Kinshasa"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Cloudinary is deliberately configured from the environment only.  Media
# records keep secure URLs and public ids, rather than Django FileFields, so
# database transactions remain independent from the remote storage service.
CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME", "")
CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY", "")
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET", "")
CLOUDINARY_SECURE = True
# A test process must never upload to a real tenant, even when a developer's
# shell happens to contain Cloudinary credentials.
CLOUDINARY_ENABLED = (
    "test" not in sys.argv
    and "pytest" not in sys.modules
    and all((CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET))
)
ECOMMERCE_MEDIA_IMAGE_MAX_BYTES = int(os.getenv("ECOMMERCE_MEDIA_IMAGE_MAX_BYTES", str(8 * 1024 * 1024)))
# Bounds decoded image memory independently of aspect ratio or edge length.
ECOMMERCE_MEDIA_IMAGE_MAX_PIXELS = int(os.getenv("ECOMMERCE_MEDIA_IMAGE_MAX_PIXELS", "36000000"))
ECOMMERCE_MEDIA_VIDEO_MAX_BYTES = int(os.getenv("ECOMMERCE_MEDIA_VIDEO_MAX_BYTES", str(50 * 1024 * 1024)))
ECOMMERCE_PRODUCT_IMAGE_LIMIT = int(os.getenv("ECOMMERCE_PRODUCT_IMAGE_LIMIT", "10"))
ECOMMERCE_PRODUCT_VIDEO_LIMIT = int(os.getenv("ECOMMERCE_PRODUCT_VIDEO_LIMIT", "3"))
ECOMMERCE_PRODUCT_MEDIA_LIMIT = int(os.getenv("ECOMMERCE_PRODUCT_MEDIA_LIMIT", "13"))

CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")
CORS_ALLOW_CREDENTIALS = False

REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend", "rest_framework.filters.SearchFilter", "rest_framework.filters.OrderingFilter"],
    "DEFAULT_SCHEMA_CLASS": "config.openapi.EcommerceAutoSchema",
}

# OAuth 2.0 / OpenID Connect settings for the future Carri Account integration.
# Endpoint values remain optional because OIDC discovery should be preferred.
CARRI_ACCOUNT_ISSUER = os.getenv("CARRI_ACCOUNT_ISSUER", "")
CARRI_ACCOUNT_CLIENT_ID = os.getenv("CARRI_ACCOUNT_CLIENT_ID", "")
CARRI_ACCOUNT_CLIENT_SECRET = os.getenv("CARRI_ACCOUNT_CLIENT_SECRET", "")
CARRI_ACCOUNT_REDIRECT_URI = os.getenv("CARRI_ACCOUNT_REDIRECT_URI", "")
CARRI_ACCOUNT_SCOPES = os.getenv("CARRI_ACCOUNT_SCOPES", "openid email")

CARRI_ACCOUNT_ANDROID_CLIENT_ID = os.getenv("CARRI_ACCOUNT_ANDROID_CLIENT_ID", "")
CARRI_ACCOUNT_ANDROID_REDIRECT_URI = os.getenv("CARRI_ACCOUNT_ANDROID_REDIRECT_URI", "")
CARRI_ACCOUNT_DISCOVERY_CACHE_SECONDS = int(os.getenv("CARRI_ACCOUNT_DISCOVERY_CACHE_SECONDS", "300"))
CARRI_ACCOUNT_JWKS_CACHE_SECONDS = int(os.getenv("CARRI_ACCOUNT_JWKS_CACHE_SECONDS", "300"))
CARRI_ACCOUNT_ID_TOKEN_CLOCK_SKEW_SECONDS = int(os.getenv("CARRI_ACCOUNT_ID_TOKEN_CLOCK_SKEW_SECONDS", "60"))
CARRI_ACCOUNT_HTTP_TIMEOUT_SECONDS = int(os.getenv("CARRI_ACCOUNT_HTTP_TIMEOUT_SECONDS", "10"))
CARRI_ACCOUNT_OAUTH_ATTEMPT_TTL_SECONDS = int(os.getenv("CARRI_ACCOUNT_OAUTH_ATTEMPT_TTL_SECONDS", "600"))
CARRI_ACCOUNT_HANDOFF_TTL_SECONDS = int(os.getenv("CARRI_ACCOUNT_HANDOFF_TTL_SECONDS", "120"))
CARRI_ACCOUNT_WEB_HANDOFF_DELIVERY_URL = os.getenv(
    "CARRI_ACCOUNT_WEB_HANDOFF_DELIVERY_URL", ""
)
CARRI_ACCOUNT_WEB_HANDOFF_CLIENT_ID = "ecommerce-web"
CARRI_ACCOUNT_OAUTH_BROWSER_BINDING_COOKIE_NAME = "ecommerce_oauth_attempt"
CARRI_ACCOUNT_EMAIL_PROOF_MAX_AGE_SECONDS = int(
    os.getenv("CARRI_ACCOUNT_EMAIL_PROOF_MAX_AGE_SECONDS", "600")
)

# Application-level client authentication (Ecommerce-HMAC v1).
# HMAC identifies the calling application; it never authenticates a user and
# never grants a business permission. Secrets live only in the environment.
DEFAULT_ECOMMERCE_HMAC_MODE = "DISABLED"
ECOMMERCE_HMAC_MODE = os.getenv(
    "ECOMMERCE_HMAC_MODE", DEFAULT_ECOMMERCE_HMAC_MODE
).upper()
if ECOMMERCE_HMAC_MODE not in {"DISABLED", "OBSERVATION", "ENFORCE"}:
    raise ValueError(
        "ECOMMERCE_HMAC_MODE must be DISABLED, OBSERVATION or ENFORCE."
    )
ECOMMERCE_HMAC_SIGNATURE_VERSION = "v1"
ECOMMERCE_HMAC_MAX_CLOCK_SKEW_SECONDS = int(
    os.getenv("ECOMMERCE_HMAC_MAX_CLOCK_SKEW_SECONDS", "120")
)
ECOMMERCE_HMAC_NONCE_TTL_SECONDS = int(
    os.getenv("ECOMMERCE_HMAC_NONCE_TTL_SECONDS", "900")
)
ECOMMERCE_HMAC_MAX_BODY_BYTES = int(
    os.getenv("ECOMMERCE_HMAC_MAX_BODY_BYTES", "1000000")
)
ECOMMERCE_HMAC_REQUIRE_BODY_HASH = (
    os.getenv("ECOMMERCE_HMAC_REQUIRE_BODY_HASH", "true").lower() == "true"
)
ECOMMERCE_HMAC_LAST_SEEN_THROTTLE_SECONDS = int(
    os.getenv("ECOMMERCE_HMAC_LAST_SEEN_THROTTLE_SECONDS", "300")
)
# Route policy is decided from the method and path only. A client must never be
# able to opt out of HMAC by declaring its platform in a header. This is a
# server-side allow-list: adding a BFF operation requires a code review, not
# merely an environment change that could accidentally capture a mobile route.
ECOMMERCE_HMAC_BFF_ONLY_PREFIXES = (
    "/api/v1/auth/carri/handoff/consume/",
)
ECOMMERCE_HMAC_PROTECTED_PREFIXES = env_list(
    "ECOMMERCE_HMAC_PROTECTED_PREFIXES",
    list(ECOMMERCE_HMAC_BFF_ONLY_PREFIXES),
)
invalid_hmac_prefixes = set(ECOMMERCE_HMAC_PROTECTED_PREFIXES).difference(
    ECOMMERCE_HMAC_BFF_ONLY_PREFIXES
)
if invalid_hmac_prefixes:
    raise ValueError(
        "ECOMMERCE_HMAC_PROTECTED_PREFIXES may only contain BFF-only routes."
    )
ECOMMERCE_HMAC_EXEMPT_METHODS = tuple(
    method.upper()
    for method in env_list("ECOMMERCE_HMAC_EXEMPT_METHODS", ["OPTIONS"])
)

def _hmac_client_secrets():
    """Parse the client secret mapping without ever logging its content."""
    import json

    raw = os.getenv("ECOMMERCE_HMAC_CLIENT_SECRETS", "")
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "ECOMMERCE_HMAC_CLIENT_SECRETS must be a valid JSON object."
        ) from exc
    if not isinstance(parsed, dict):
        raise ValueError("ECOMMERCE_HMAC_CLIENT_SECRETS must be a JSON object.")
    # Fail closed during startup for an invalid rotation; do not wait until the
    # first BFF request to discover that its previous key has no expiry.
    from apps.api_clients.services.secrets import parse_client_secrets

    parse_client_secrets(parsed)
    return parsed


ECOMMERCE_HMAC_CLIENT_SECRETS = _hmac_client_secrets()

EMAIL_BACKEND = os.getenv(
    "EMAIL_BACKEND",
    "django.core.mail.backends.smtp.EmailBackend",
)
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)
EMAIL_TIMEOUT = int(os.getenv("EMAIL_TIMEOUT", "10"))
if EMAIL_USE_TLS and EMAIL_USE_SSL:
    raise ValueError("EMAIL_USE_TLS and EMAIL_USE_SSL cannot both be enabled.")
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "")
BUSINESS_MEMBER_INVITATION_URL = os.getenv(
    "BUSINESS_MEMBER_INVITATION_URL",
    "",
)
BUSINESS_MEMBER_INVITATION_EXPIRY_HOURS = int(
    os.getenv("BUSINESS_MEMBER_INVITATION_EXPIRY_HOURS", "168")
)

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
    "APPEND_COMPONENTS": {
        "securitySchemes": {
            "EcommerceClientHMAC": {
                "type": "apiKey",
                "in": "header",
                "name": "X-Ecommerce-Signature",
                "description": (
                    "Signature HMAC-SHA256 du client applicatif, contrat Ecommerce-HMAC v1. "
                    "En-têtes obligatoires : X-Ecommerce-Client-Id, X-Ecommerce-Timestamp, "
                    "X-Ecommerce-Nonce, X-Ecommerce-Content-SHA256, X-Ecommerce-Signature-Version "
                    "et X-Ecommerce-Signature. La signature identifie l'application appelante ; "
                    "elle ne remplace jamais le JWT ecommerce ni les permissions métier."
                ),
            }
        }
    },
    "ENUM_NAME_OVERRIDES": {
        "BusinessCurrencyEnum": "apps.businesses.models.Business.Currency",
        "BusinessMemberInvitationStatusEnum": "apps.businesses.models.BusinessMemberInvitation.Status",
        "ProductStatusEnum": "apps.catalog.models.Product.Status",
        "BusinessAtomicPermissionEnum": "apps.businesses.permissions.ATOMIC_PERMISSION_VALUES",
        "BusinessPermissionCatalogEnum": "apps.businesses.models.BusinessMemberPermission.Permission",
        "PaymentMethodEnum": "apps.common.choices.PaymentMethod",
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
        {"name": "Receivables", "description": "Créances clients et paiements internes."},
        {"name": "Expense Categories", "description": "Catégories de dépenses par commerce."},
        {"name": "Expenses", "description": "Dépenses internes du commerce."},
    ],
}
