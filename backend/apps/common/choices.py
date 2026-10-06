"""Canonical enumerations shared across ecommerce business domains."""

from django.db import models


class PaymentMethod(models.TextChoices):
    """
    Classify the payment method declared for an internal operation.

    These values are descriptive only. They do not trigger, verify, or integrate
    with any external payment provider, gateway, or mobile-money operator.
    """

    CASH = "CASH", "Espèces"
    MOBILE_MONEY = "MOBILE_MONEY", "Mobile Money"
    BANK_TRANSFER = "BANK_TRANSFER", "Virement bancaire"
    CARD = "CARD", "Carte"
    OTHER = "OTHER", "Autre"
