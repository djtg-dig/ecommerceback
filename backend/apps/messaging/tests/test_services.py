from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, connections, transaction
from rest_framework.exceptions import NotFound, PermissionDenied

from apps.businesses.models import Business, BusinessMember, BusinessMemberPermission
from apps.carts.models import Cart
from apps.messaging.models import Conversation, Message
from apps.messaging.identifiers import generate_conversation_reference, generate_message_reference
from apps.messaging.services import (
    ConversationStateError,
    accessible_conversations,
    close_conversation,
    confirm_delivery,
    confirm_read,
    eligible_sellers,
    get_or_create_conversation,
    reopen_conversation,
    require_conversation_access,
    send_message,
)

from .conftest import grant_messaging, make_identity, make_member


def test_eligible_sellers_require_both_permissions_and_active_membership(messaging_context):
    context = messaging_context
    view_only = make_member(
        business=context["business"],
        identity=make_identity("view-only"),
        title="Vue seule",
    )
    grant_messaging(view_only, reply=False)
    suspended = make_member(
        business=context["business"],
        identity=make_identity("suspended"),
        title="Suspendu",
        status=BusinessMember.Status.SUSPENDED,
    )

    sellers = eligible_sellers(business=context["business"], buyer=context["buyer"])

    assert {member.public_id for member in sellers} == {
        context["seller"].public_id,
        context["owner"].public_id,
    }
    assert view_only not in sellers
    assert suspended not in sellers


def test_buyer_is_never_returned_as_an_eligible_seller(messaging_context):
    context = messaging_context
    buyer_member = make_member(
        business=context["business"],
        identity=context["buyer"],
        title="Acheteur membre",
    )
    grant_messaging(buyer_member)

    sellers = eligible_sellers(business=context["business"], buyer=context["buyer"])

    assert buyer_member not in sellers


def test_conversation_creation_is_idempotent_and_unique(messaging_context):
    context = messaging_context

    second, created = get_or_create_conversation(
        buyer=context["buyer"],
        business=context["business"],
        seller_reference=context["seller"].public_id,
    )

    assert created is False
    assert second.pk == context["conversation"].pk
    assert Conversation.objects.count() == 1


def test_model_rejects_new_conversation_with_unpermitted_seller(messaging_context):
    context = messaging_context
    unpermitted_identity = make_identity("model-unpermitted")
    make_member(
        business=context["business"],
        identity=unpermitted_identity,
        title="Sans permissions",
    )

    with pytest.raises(ValidationError):
        Conversation(
            business=context["business"],
            buyer=context["buyer"],
            seller=unpermitted_identity,
        ).save()


def test_database_rejects_duplicate_and_same_participant(messaging_context):
    context = messaging_context
    conversation = context["conversation"]
    with pytest.raises(ValidationError):
        Conversation(
            business=context["business"],
            buyer=context["buyer"],
            seller=context["buyer"],
        ).save()
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Conversation.objects.bulk_create([
                Conversation(
                    reference=generate_conversation_reference(),
                    business=conversation.business,
                    buyer=conversation.buyer,
                    seller=conversation.seller,
                )
            ])


def test_database_rejects_message_without_text_or_file(messaging_context):
    context = messaging_context
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Message.objects.bulk_create([
                Message(
                    reference=generate_message_reference(),
                    conversation=context["conversation"],
                    sender=context["buyer"],
                    recipient=context["seller_identity"],
                    content="",
                    file=None,
                )
            ])


def test_only_designated_seller_can_access_private_conversation(messaging_context):
    context = messaging_context
    assert require_conversation_access(context["buyer"], context["conversation"]) == "BUYER"
    assert require_conversation_access(context["seller_identity"], context["conversation"]) == "SELLER"
    with pytest.raises(NotFound):
        require_conversation_access(context["owner_identity"], context["conversation"])
    with pytest.raises(NotFound):
        require_conversation_access(context["outsider"], context["conversation"])


def test_seller_loses_access_after_suspension_or_permission_revocation(messaging_context):
    context = messaging_context
    context["seller"].status = BusinessMember.Status.SUSPENDED
    context["seller"].save()
    with pytest.raises(PermissionDenied):
        require_conversation_access(context["seller_identity"], context["conversation"])

    context["seller"].status = BusinessMember.Status.ACTIVE
    context["seller"].save()
    BusinessMemberPermission.objects.filter(
        member=context["seller"],
        permission=BusinessMemberPermission.Permission.MESSAGING_VIEW,
    ).delete()
    with pytest.raises(PermissionDenied):
        require_conversation_access(context["seller_identity"], context["conversation"])


def test_removed_seller_loses_access(messaging_context):
    context = messaging_context
    context["seller"].status = BusinessMember.Status.REMOVED
    context["seller"].save()

    with pytest.raises(PermissionDenied):
        require_conversation_access(context["seller_identity"], context["conversation"])


def test_buyer_cannot_send_to_suspended_or_unpermitted_seller(messaging_context):
    context = messaging_context
    context["seller"].status = BusinessMember.Status.SUSPENDED
    context["seller"].save()
    with pytest.raises(PermissionDenied):
        send_message(
            identity=context["buyer"],
            conversation=context["conversation"],
            content="Le vendeur est suspendu",
        )

    context["seller"].status = BusinessMember.Status.ACTIVE
    context["seller"].save()
    BusinessMemberPermission.objects.filter(
        member=context["seller"],
        permission=BusinessMemberPermission.Permission.MESSAGING_REPLY,
    ).delete()
    with pytest.raises(PermissionDenied):
        send_message(
            identity=context["buyer"],
            conversation=context["conversation"],
            content="Le vendeur ne peut plus répondre",
        )


def test_accessible_queryset_never_grants_owner_global_visibility(messaging_context):
    context = messaging_context
    assert list(accessible_conversations(context["buyer"])) == [context["conversation"]]
    assert list(accessible_conversations(context["seller_identity"])) == [context["conversation"]]
    assert list(accessible_conversations(context["owner_identity"])) == []


def test_sender_and_recipient_are_derived_from_authenticated_identity(messaging_context):
    context = messaging_context
    buyer_message = send_message(
        identity=context["buyer"],
        conversation=context["conversation"],
        content="Le produit est-il disponible ?",
    )
    seller_message = send_message(
        identity=context["seller_identity"],
        conversation=context["conversation"],
        content="Oui.",
        reply_reference=buyer_message.reference,
    )

    assert buyer_message.sender == context["buyer"]
    assert buyer_message.recipient == context["seller_identity"]
    assert seller_message.sender == context["seller_identity"]
    assert seller_message.recipient == context["buyer"]
    assert seller_message.reply_to == buyer_message
    context["conversation"].refresh_from_db()
    assert context["conversation"].last_message_at == seller_message.sent_at


def test_message_rejects_third_participant_and_cross_conversation_reply(messaging_context):
    context = messaging_context
    first = send_message(
        identity=context["buyer"],
        conversation=context["conversation"],
        content="Premier",
    )
    other_seller_identity = make_identity("other-seller")
    other_seller = make_member(
        business=context["business"],
        identity=other_seller_identity,
        title="Autre vendeur",
    )
    grant_messaging(other_seller)
    other_conversation, _ = get_or_create_conversation(
        buyer=context["buyer"],
        business=context["business"],
        seller_reference=other_seller.public_id,
    )
    with pytest.raises(ValidationError):
        send_message(
            identity=context["buyer"],
            conversation=other_conversation,
            content="Mauvaise citation",
            reply_reference=first.reference,
        )
    with pytest.raises(ValidationError):
        Message(
            conversation=context["conversation"],
            sender=context["buyer"],
            recipient=context["outsider"],
            content="Usurpation",
        ).save()


def test_cart_must_match_buyer_and_business(messaging_context):
    context = messaging_context
    valid = Cart.objects.create(
        buyer=context["buyer"],
        business=context["business"],
        name="Panier valide",
    )
    message = send_message(
        identity=context["buyer"],
        conversation=context["conversation"],
        content="Ce panier",
        cart_reference=valid.reference,
    )
    assert message.cart == valid

    foreign_buyer = Cart.objects.create(
        buyer=context["outsider"],
        business=context["business"],
        name="Panier étranger",
    )
    with pytest.raises(ValidationError):
        send_message(
            identity=context["buyer"],
            conversation=context["conversation"],
            content="Interdit",
            cart_reference=foreign_buyer.reference,
        )

    other_business = Business.objects.create(name="Autre boutique")
    other_cart = Cart.objects.create(
        buyer=context["buyer"],
        business=other_business,
        name="Autre entreprise",
    )
    with pytest.raises(ValidationError):
        send_message(
            identity=context["buyer"],
            conversation=context["conversation"],
            content="Interdit",
            cart_reference=other_cart.reference,
        )


def test_only_recipient_can_confirm_delivery_and_read(messaging_context):
    context = messaging_context
    message = send_message(
        identity=context["buyer"],
        conversation=context["conversation"],
        content="Accusés",
    )
    with pytest.raises(PermissionDenied):
        confirm_read(identity=context["buyer"], message=message)

    read_message = confirm_read(identity=context["seller_identity"], message=message)
    assert read_message.read_at is not None
    assert read_message.received_at is None
    delivered = confirm_delivery(identity=context["seller_identity"], message=message)
    assert delivered.received_at is not None
    assert confirm_read(identity=context["seller_identity"], message=message).read_at == read_message.read_at


def test_temporal_database_constraints_reject_falsified_dates(messaging_context):
    context = messaging_context
    message = send_message(
        identity=context["buyer"],
        conversation=context["conversation"],
        content="Temps",
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Message.objects.filter(pk=message.pk).update(
                read_at=message.sent_at - timedelta(seconds=1)
            )


def test_closed_conversation_blocks_messages_and_archived_cannot_reopen(messaging_context):
    context = messaging_context
    closed = close_conversation(identity=context["buyer"], conversation=context["conversation"])
    assert closed.status == Conversation.Status.CLOSED
    with pytest.raises(ConversationStateError):
        send_message(identity=context["buyer"], conversation=closed, content="Bloqué")
    reopened = reopen_conversation(identity=context["buyer"], conversation=closed)
    assert reopened.status == Conversation.Status.OPEN

    Conversation.objects.filter(pk=reopened.pk).update(status=Conversation.Status.ARCHIVED)
    reopened.refresh_from_db()
    with pytest.raises(ConversationStateError):
        reopen_conversation(identity=context["buyer"], conversation=reopened)


@pytest.mark.django_db(transaction=True)
def test_concurrent_creation_returns_one_conversation():
    business = Business.objects.create(name="Boutique concurrence")
    buyer = make_identity("concurrent-buyer")
    seller_identity = make_identity("concurrent-seller")
    make_member(
        business=business,
        identity=make_identity("concurrent-owner"),
        title="Gérant",
        owner=True,
    )
    seller = make_member(business=business, identity=seller_identity)
    grant_messaging(seller)

    def create():
        close_old_connections()
        try:
            local_buyer = type(buyer).objects.get(pk=buyer.pk)
            local_business = Business.objects.get(pk=business.pk)
            conversation, _ = get_or_create_conversation(
                buyer=local_buyer,
                business=local_business,
                seller_reference=seller.public_id,
            )
            return conversation.reference
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        references = list(executor.map(lambda _: create(), range(2)))

    assert len(set(references)) == 1
    assert Conversation.objects.filter(business=business, buyer=buyer, seller=seller_identity).count() == 1
