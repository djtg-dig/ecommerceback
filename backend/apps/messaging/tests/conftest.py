import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CarriIdentity
from apps.businesses.models import Business, BusinessMember, BusinessMemberPermission
from apps.messaging.services import get_or_create_conversation


def make_identity(label):
    return CarriIdentity.objects.create(
        carri_subject=f"subject-{label}",
        verified_email=f"{label}@example.com",
        email_verified=True,
    )


def make_member(*, business, identity, title="Vendeur", owner=False, status=BusinessMember.Status.ACTIVE):
    return BusinessMember.objects.create(
        business=business,
        identity=identity,
        role=BusinessMember.Role.OWNER if owner else BusinessMember.Role.EMPLOYEE,
        is_owner=owner,
        title=title,
        status=status,
    )


def grant_messaging(member, *, view=True, reply=True):
    if member.is_owner:
        return
    if view:
        BusinessMemberPermission.objects.create(
            member=member,
            permission=BusinessMemberPermission.Permission.MESSAGING_VIEW,
        )
    if reply:
        BusinessMemberPermission.objects.create(
            member=member,
            permission=BusinessMemberPermission.Permission.MESSAGING_REPLY,
        )


@pytest.fixture
def messaging_context(db, tmp_path, settings):
    settings.MESSAGING_PRIVATE_MEDIA_ROOT = tmp_path / "private-messaging"
    business = Business.objects.create(name="Boutique principale")
    buyer = make_identity("buyer")
    seller_identity = make_identity("seller")
    owner_identity = make_identity("owner")
    outsider = make_identity("outsider")
    owner = make_member(
        business=business,
        identity=owner_identity,
        title="Gérant",
        owner=True,
    )
    seller = make_member(
        business=business,
        identity=seller_identity,
        title="Conseillère ventes",
    )
    grant_messaging(seller)
    conversation, _ = get_or_create_conversation(
        buyer=buyer,
        business=business,
        seller_reference=seller.public_id,
    )
    return {
        "business": business,
        "buyer": buyer,
        "seller_identity": seller_identity,
        "seller": seller,
        "owner_identity": owner_identity,
        "owner": owner,
        "outsider": outsider,
        "conversation": conversation,
    }


@pytest.fixture
def api_client():
    return APIClient()
