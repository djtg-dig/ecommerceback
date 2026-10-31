"""Références publiques opaques de la messagerie."""

from apps.businesses.identifiers import generate_public_id


def generate_conversation_reference() -> str:
    return generate_public_id("CV")


def generate_message_reference() -> str:
    return generate_public_id("MG")
