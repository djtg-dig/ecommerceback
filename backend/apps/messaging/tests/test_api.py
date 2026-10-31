import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.businesses.models import BusinessMember, BusinessMemberPermission
from apps.carts.models import Cart
from apps.messaging.models import Conversation, Message

from .conftest import grant_messaging, make_identity, make_member


def authenticate(client, identity):
    client.force_authenticate(user=identity)
    return client


def conversation_path(conversation, suffix=""):
    return f"/api/v1/messaging/conversations/{conversation.reference}/{suffix}"


def message_path(conversation, message, suffix=""):
    return f"{conversation_path(conversation, 'messages/')}{message.reference}/{suffix}"


def image_upload(name="photo.png"):
    stream = io.BytesIO()
    Image.new("RGB", (12, 12), color="blue").save(stream, format="PNG")
    return SimpleUploadedFile(name, stream.getvalue(), content_type="application/octet-stream")


def test_seller_list_requires_authentication_and_exposes_minimum_fields(api_client, messaging_context):
    context = messaging_context
    path = f"/api/v1/public/businesses/{context['business'].public_id}/messaging-sellers/"
    assert api_client.get(path).status_code in {401, 403}

    response = authenticate(api_client, context["buyer"]).get(path)

    assert response.status_code == 200
    sellers = {item["reference"]: item for item in response.json()}
    assert sellers[context["seller"].public_id] == {
        "reference": context["seller"].public_id,
        "display_name": "Conseillère ventes",
        "avatar": None,
    }
    assert context["owner"].public_id in sellers
    payload = response.content.decode()
    assert "@example.com" not in payload
    assert "MESSAGING_VIEW" not in payload
    assert "online" not in payload.lower()


def test_create_or_find_and_list_conversation(api_client, messaging_context):
    context = messaging_context
    client = authenticate(api_client, context["buyer"])
    payload = {
        "business": context["business"].public_id,
        "seller": context["seller"].public_id,
    }

    first = client.post("/api/v1/messaging/conversations/", payload, format="json")
    second = client.post("/api/v1/messaging/conversations/", payload, format="json")
    listing = client.get("/api/v1/messaging/conversations/")

    assert first.status_code == 200  # La fixture a déjà créé ce triplet.
    assert second.status_code == 200
    assert first.json()["reference"] == context["conversation"].reference
    assert first.json()["participant_role"] == "BUYER"
    assert listing.status_code == 200
    assert [item["reference"] for item in listing.json()["results"]] == [
        context["conversation"].reference
    ]


def test_non_participants_including_owner_cannot_read_conversation(api_client, messaging_context):
    context = messaging_context
    path = conversation_path(context["conversation"])

    assert authenticate(api_client, context["owner_identity"]).get(path).status_code == 404
    assert authenticate(api_client, context["outsider"]).get(path).status_code == 404
    assert authenticate(api_client, context["seller_identity"]).get(path).status_code == 200


def test_other_authorized_seller_cannot_read_designated_seller_conversation(api_client, messaging_context):
    context = messaging_context
    other_identity = make_identity("api-other-seller")
    other = make_member(business=context["business"], identity=other_identity, title="Autre")
    grant_messaging(other)

    response = authenticate(api_client, other_identity).get(conversation_path(context["conversation"]))

    assert response.status_code == 404


def test_message_api_ignores_spoofed_participants_and_returns_reply_preview(api_client, messaging_context):
    context = messaging_context
    client = authenticate(api_client, context["buyer"])
    path = conversation_path(context["conversation"], "messages/")
    first = client.post(
        path,
        {
            "content": "Le produit est-il disponible ?",
            "sender": str(context["outsider"].pk),
            "recipient": str(context["outsider"].pk),
        },
        format="json",
    )
    assert first.status_code == 201
    first_message = Message.objects.get(reference=first.json()["reference"])
    assert first_message.sender == context["buyer"]
    assert first_message.recipient == context["seller_identity"]

    reply = authenticate(api_client, context["seller_identity"]).post(
        path,
        {"content": "Oui, il est disponible.", "reply_to": first_message.reference},
        format="json",
    )

    assert reply.status_code == 201
    assert reply.json()["sender_role"] == "SELLER"
    assert reply.json()["recipient_role"] == "BUYER"
    assert reply.json()["reply_to"]["reference"] == first_message.reference


def test_message_history_is_paginated_and_private(api_client, messaging_context):
    context = messaging_context
    path = conversation_path(context["conversation"], "messages/")
    client = authenticate(api_client, context["buyer"])
    for index in range(3):
        assert client.post(path, {"content": f"Message {index}"}, format="json").status_code == 201

    response = client.get(path, {"page_size": 2})
    outsider = authenticate(api_client, context["outsider"]).get(path)

    assert response.status_code == 200
    assert response.json()["count"] == 3
    assert len(response.json()["results"]) == 2
    assert outsider.status_code == 404


def test_cart_projection_is_minimal_and_foreign_cart_is_rejected(api_client, messaging_context):
    context = messaging_context
    cart = Cart.objects.create(
        buyer=context["buyer"],
        business=context["business"],
        name="Panier à discuter",
    )
    path = conversation_path(context["conversation"], "messages/")
    client = authenticate(api_client, context["buyer"])

    response = client.post(path, {"content": "Mon panier", "cart": cart.reference}, format="json")

    assert response.status_code == 201
    assert response.json()["cart"] == {
        "reference": cart.reference,
        "name": "Panier à discuter",
        "status": "DRAFT",
    }
    assert "items" not in response.json()["cart"]

    foreign = Cart.objects.create(
        buyer=context["outsider"],
        business=context["business"],
        name="Panier privé",
    )
    rejected = client.post(path, {"content": "Interdit", "cart": foreign.reference}, format="json")
    assert rejected.status_code == 400


def test_only_recipient_can_mark_message_received_and_read(api_client, messaging_context):
    context = messaging_context
    path = conversation_path(context["conversation"], "messages/")
    created = authenticate(api_client, context["buyer"]).post(path, {"content": "Bonjour"}, format="json")
    message = Message.objects.get(reference=created.json()["reference"])

    sender_read = api_client.post(message_path(context["conversation"], message, "read/"))
    assert sender_read.status_code == 403

    seller = authenticate(api_client, context["seller_identity"])
    received = seller.post(message_path(context["conversation"], message, "received/"))
    read = seller.post(message_path(context["conversation"], message, "read/"))
    assert received.status_code == 200
    assert received.json()["received_at"] is not None
    assert read.status_code == 200
    assert read.json()["read_at"] is not None


def test_closed_conversation_rejects_messages_then_can_reopen(api_client, messaging_context):
    context = messaging_context
    client = authenticate(api_client, context["buyer"])
    closed = client.post(conversation_path(context["conversation"], "close/"))
    rejected = client.post(
        conversation_path(context["conversation"], "messages/"),
        {"content": "Bloqué"},
        format="json",
    )
    reopened = client.post(conversation_path(context["conversation"], "reopen/"))

    assert closed.status_code == 200
    assert closed.json()["status"] == Conversation.Status.CLOSED
    assert rejected.status_code == 409
    assert reopened.status_code == 200
    assert reopened.json()["status"] == Conversation.Status.OPEN


def test_suspended_or_unpermitted_seller_loses_api_access(api_client, messaging_context):
    context = messaging_context
    context["seller"].status = BusinessMember.Status.SUSPENDED
    context["seller"].save()
    response = authenticate(api_client, context["seller_identity"]).get(
        conversation_path(context["conversation"])
    )
    assert response.status_code == 403

    context["seller"].status = BusinessMember.Status.ACTIVE
    context["seller"].save()
    BusinessMemberPermission.objects.filter(member=context["seller"]).delete()
    response = api_client.get(conversation_path(context["conversation"]))
    assert response.status_code == 403


def test_private_attachment_upload_and_authorized_download(api_client, messaging_context):
    context = messaging_context
    path = conversation_path(context["conversation"], "messages/")
    created = authenticate(api_client, context["buyer"]).post(
        path,
        {"content": "Image", "file": image_upload("../../photo.fake")},
        format="multipart",
    )

    assert created.status_code == 201
    assert created.json()["attachment"]["content_type"] == "image/png"
    assert created.json()["attachment"]["name"].endswith(".png")
    message = Message.objects.get(reference=created.json()["reference"])
    assert ".." not in message.file.name
    with pytest.raises(ValueError):
        message.file.storage.url(message.file.name)

    download_path = created.json()["attachment"]["download_path"]
    authorized = api_client.get(download_path)
    assert authorized.status_code == 200
    assert authorized["Cache-Control"] == "private, no-store"
    assert authorized["Content-Disposition"].startswith("attachment;")
    assert b"".join(authorized.streaming_content).startswith(b"\x89PNG")

    forbidden = authenticate(api_client, context["owner_identity"]).get(download_path)
    assert forbidden.status_code == 404


@pytest.mark.parametrize(
    "upload",
    [
        SimpleUploadedFile("malware.jpg", b"not-an-image", content_type="image/jpeg"),
        SimpleUploadedFile("broken.pdf", b"%PDF-1.4\nmissing eof", content_type="application/pdf"),
        SimpleUploadedFile("script.html", b"<script>alert(1)</script>", content_type="text/html"),
    ],
)
def test_invalid_or_unsupported_attachments_are_rejected(api_client, messaging_context, upload):
    context = messaging_context
    response = authenticate(api_client, context["buyer"]).post(
        conversation_path(context["conversation"], "messages/"),
        {"file": upload},
        format="multipart",
    )

    assert response.status_code == 400


def test_pdf_attachment_is_detected_from_signature(api_client, messaging_context):
    context = messaging_context
    upload = SimpleUploadedFile(
        "document.bin",
        b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n",
        content_type="application/octet-stream",
    )
    response = authenticate(api_client, context["buyer"]).post(
        conversation_path(context["conversation"], "messages/"),
        {"file": upload},
        format="multipart",
    )

    assert response.status_code == 201
    assert response.json()["attachment"]["content_type"] == "application/pdf"
    assert response.json()["attachment"]["name"].endswith(".pdf")


def test_attachment_is_deleted_only_after_message_deletion_commits(
    api_client,
    messaging_context,
    django_capture_on_commit_callbacks,
):
    context = messaging_context
    response = authenticate(api_client, context["buyer"]).post(
        conversation_path(context["conversation"], "messages/"),
        {"file": image_upload()},
        format="multipart",
    )
    message = Message.objects.get(reference=response.json()["reference"])
    storage = message.file.storage
    stored_name = message.file.name
    assert storage.exists(stored_name)

    with django_capture_on_commit_callbacks(execute=True):
        message.delete()

    assert not storage.exists(stored_name)
