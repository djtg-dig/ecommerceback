import pytest
from apps.businesses.models import BusinessMember
from apps.messaging.models import Inquiry
from apps.messaging.services import (
    effective_agent,
    get_or_create_conversation,
    send_message,
    set_designated_agent,
)



@pytest.mark.django_db
def test_owner_is_effective_agent_by_default(messaging_context):
    context = messaging_context
    assert effective_agent(business=context["business"]).id == context["owner"].id


@pytest.mark.django_db
def test_designation_is_transactional_and_owner_can_reset(messaging_context):
    context = messaging_context
    employee = context["seller"]
    settings_row = set_designated_agent(
        actor=context["owner_identity"],
        business=context["business"],
        member_reference=employee.public_id,
    )
    assert settings_row.designated_agent_id == employee.id
    assert effective_agent(business=context["business"]).id == employee.id
    set_designated_agent(actor=context["owner_identity"], business=context["business"])
    assert effective_agent(business=context["business"]).id == context["owner"].id


@pytest.mark.django_db
def test_suspended_designated_agent_falls_back_to_owner(messaging_context):
    context = messaging_context
    set_designated_agent(
        actor=context["owner_identity"],
        business=context["business"],
        member_reference=context["seller"].public_id,
    )
    context["seller"].status = BusinessMember.Status.SUSPENDED
    context["seller"].save(update_fields=("status",))
    assert effective_agent(business=context["business"]).id == context["owner"].id


@pytest.mark.django_db
def test_non_effective_member_cannot_reply_after_replacement(messaging_context):
    context = messaging_context
    conversation = context["conversation"]
    set_designated_agent(
        actor=context["owner_identity"],
        business=context["business"],
        member_reference=context["seller"].public_id,
    )
    with pytest.raises(Exception):
        send_message(identity=context["owner_identity"], conversation=conversation, content="old agent")


@pytest.mark.django_db
def test_inquiry_keeps_product_snapshot(messaging_context):
    context = messaging_context
    inquiry = Inquiry.objects.create(
        business=context["business"],
        buyer=context["buyer"],
        conversation=context["conversation"],
        product_reference="PRD-OLD",
        product_name="Produit historique",
        quantity="3",
        description="Besoin commercial",
    )
    assert inquiry.product_reference == "PRD-OLD"
    assert inquiry.product_name == "Produit historique"
