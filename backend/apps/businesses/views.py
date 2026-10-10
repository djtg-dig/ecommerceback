from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Prefetch
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    inline_serializer,
)
from rest_framework import permissions, serializers, status
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    Business,
    BusinessCategory,
    BusinessMember,
    BusinessMemberInvitation,
    BusinessMemberPermission,
    BusinessPaymentMethod,
)
from .permissions import (
    has_permission,
    require_any_permission,
    require_permission,
    validate_permission,
)
from .serializers import (
    BusinessCreateSerializer,
    BusinessMemberPermissionGrantSerializer,
    BusinessMemberInvitationCreateSerializer,
    BusinessMemberInvitationSerializer,
    BusinessMemberPermissionSerializer,
    BusinessMemberSerializer,
    BusinessMemberTitleSerializer,
    BusinessPermissionCatalogSerializer,
    BusinessSerializer,
    BusinessUpdateSerializer,
    CategorySerializer,
    BusinessPaymentMethodSerializer,
)
from .services import (
    create_business,
    grant_permission,
    reactivate_member,
    remove_member,
    replace_categories,
    revoke_permission,
    suspend_member,
    update_member_title,
)
from .services.invitation_email import (
    InvitationDeliveryConfigurationError,
    InvitationDeliveryError,
)
from .services.invitations import (
    create_and_send_invitation,
    resend_member_invitation,
    revoke_member_invitation,
)


def accessible(identity):
    """Return Businesses visible through an active membership for an identity."""
    return Business.objects.filter(
        members__identity=identity,
        members__status="ACTIVE",
    ).distinct()


class MemberPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 50


class InvitationPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 50


class InvitationPermissionDenied(PermissionDenied):
    """Stable administrative invitation authorization error."""

    def __init__(self):
        super().__init__(
            {
                "code": "invitation_permission_denied",
                "detail": "Vous n'êtes pas autorisé à gérer les invitations de cette entreprise.",
            }
        )


def _invitation_error(code, detail, status_code, *, field=None):
    payload = {"code": code, "detail": detail}
    if field:
        payload[field] = [detail]
    return Response(payload, status=status_code)


def _invitation_service_error(error):
    messages = error.messages
    message = " ".join(messages)
    lowered = message.lower()
    if "pending invitation" in lowered:
        return _invitation_error(
            "invitation_already_pending",
            "Une invitation est déjà en attente pour cette adresse e-mail.",
            status.HTTP_409_CONFLICT,
            field="email",
        )
    if "membership" in lowered:
        return _invitation_error(
            "business_member_already_exists",
            "Cette personne est déjà membre de l'entreprise.",
            status.HTTP_409_CONFLICT,
            field="email",
        )
    if "valid invitation address" in lowered or "adresse e-mail valide" in lowered:
        return _invitation_error(
            "invalid_email",
            "Veuillez saisir une adresse e-mail valide.",
            status.HTTP_400_BAD_REQUEST,
            field="email",
        )
    if "en attente ou expirée" in lowered:
        return _invitation_error(
            "invitation_cannot_be_resent",
            "Seule une invitation en attente ou expirée peut être renvoyée.",
            status.HTTP_409_CONFLICT,
        )
    if "en attente peut être révoquée" in lowered:
        return _invitation_error(
            "invitation_cannot_be_revoked",
            "Seule une invitation en attente peut être révoquée.",
            status.HTTP_409_CONFLICT,
        )
    if "a expiré" in lowered:
        return _invitation_error(
            "invitation_expired",
            "Cette invitation a expiré. Veuillez demander un nouveau lien.",
            status.HTTP_409_CONFLICT,
        )
    if "a été révoquée" in lowered:
        return _invitation_error(
            "invitation_revoked",
            "Cette invitation a été révoquée.",
            status.HTTP_409_CONFLICT,
        )
    return _invitation_error(
        "invalid_invitation_operation",
        message,
        status.HTTP_400_BAD_REQUEST,
    )


def member_queryset(business):
    """Return non-removed memberships with explicit permissions prefetched."""
    return (
        BusinessMember.objects.filter(
            business=business,
        )
        .exclude(status=BusinessMember.Status.REMOVED)
        .select_related("business")
        .prefetch_related(
            Prefetch(
                "permissions",
                queryset=BusinessMemberPermission.objects.order_by(
                    "permission"
                ),
                to_attr="_prefetched_permissions",
            )
        )
        .order_by("-is_owner", "joined_at", "public_id")
    )


class BusinessesView(APIView):
    def get(self, request):
        businesses = accessible(request.user)

        return Response(BusinessSerializer(businesses, many=True).data)

    def post(self, request):
        serializer = BusinessCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            business = create_business(request.user, dict(serializer.validated_data))
        except ValueError as error:
            return Response({"detail": str(error)}, status=400)

        return Response(BusinessSerializer(business).data, status=201)


class BusinessDetailView(APIView):
    def get_object(self, request, public_id):
        return accessible(request.user).filter(public_id=public_id).first()

    def get(self, request, public_id):
        business = self.get_object(request, public_id)
        if not business:
            return Response({"detail": "Not found."}, status=404)

        return Response(BusinessSerializer(business).data)

    def patch(self, request, public_id):
        business = Business.objects.filter(public_id=public_id).first()
        if business is None:
            return Response({"detail": "Not found."}, status=404)
        require_permission(
            request.user,
            business,
            BusinessMemberPermission.Permission.UPDATE_BUSINESS,
            write=True,
        )

        serializer = BusinessUpdateSerializer(
            business,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)

        data = dict(serializer.validated_data)
        categories = data.pop("categories", None)
        primary_category = data.pop("primary_category", None)

        serializer = BusinessUpdateSerializer(
            business,
            data=data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        if categories is not None:
            try:
                replace_categories(business, categories, primary_category)
            except ValueError as error:
                return Response({"detail": str(error)}, status=400)

        return Response(BusinessSerializer(business).data)


class BusinessMembersView(APIView):
    def get(self, request, public_id):
        business = Business.objects.filter(public_id=public_id).first()
        if business is None:
            return Response({"detail": "Not found."}, status=404)
        require_permission(
            request.user,
            business,
            BusinessMemberPermission.Permission.VIEW_MEMBERS,
        )

        paginator = MemberPagination()
        page = paginator.paginate_queryset(
            member_queryset(business), request
        )

        return paginator.get_paginated_response(
            BusinessMemberSerializer(page, many=True).data
        )


class BusinessMemberDetailView(APIView):
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def get_business(self, public_id):
        return Business.objects.filter(public_id=public_id).first()

    def get(self, request, public_id, member_public_id):
        business = self.get_business(public_id)
        if business is None:
            return Response({"detail": "Not found."}, status=404)
        require_permission(
            request.user,
            business,
            BusinessMemberPermission.Permission.VIEW_MEMBERS,
        )
        member = (
            member_queryset(business)
            .filter(public_id=member_public_id)
            .first()
        )
        if member is None:
            return Response({"detail": "Not found."}, status=404)

        return Response(BusinessMemberSerializer(member).data)

    def patch(self, request, public_id, member_public_id):
        business = self.get_business(public_id)
        if business is None:
            return Response({"detail": "Not found."}, status=404)

        try:
            actor = require_permission(
                request.user,
                business,
                BusinessMemberPermission.Permission.MANAGE_MEMBERS,
                write=True,
            )
            member = (
                BusinessMember.objects.filter(
                    business=business,
                )
                .exclude(status=BusinessMember.Status.REMOVED)
                .filter(public_id=member_public_id)
                .first()
            )
            if member is None:
                return Response({"detail": "Not found."}, status=404)
            serializer = BusinessMemberTitleSerializer(
                member,
                data=request.data,
            )
            serializer.is_valid(raise_exception=True)
            updated = update_member_title(
                actor,
                member,
                serializer.validated_data["title"],
            )
        except DjangoValidationError as error:
            return Response({"detail": str(error)}, status=400)

        return Response(BusinessMemberSerializer(updated).data)

    def delete(self, request, public_id, member_public_id):
        business = self.get_business(public_id)
        if business is None:
            return Response({"detail": "Not found."}, status=404)

        try:
            actor = require_permission(
                request.user,
                business,
                BusinessMemberPermission.Permission.MANAGE_MEMBERS,
                write=True,
            )
            member = (
                BusinessMember.objects.filter(
                    business=business,
                )
                .filter(public_id=member_public_id)
                .first()
            )
            if member is None:
                return Response({"detail": "Not found."}, status=404)
            remove_member(actor, member)
        except DjangoValidationError as error:
            return Response({"detail": str(error)}, status=400)

        return Response(status=204)


class BusinessMemberSuspendView(APIView):
    def get_member(self, request, public_id, member_public_id):
        """Resolve the Business, enforce MANAGE_MEMBERS, then resolve the member."""
        business = Business.objects.filter(public_id=public_id).first()
        if business is None:
            return None, None, None
        actor = require_permission(
            request.user,
            business,
            BusinessMemberPermission.Permission.MANAGE_MEMBERS,
            write=True,
        )
        member = (
            BusinessMember.objects.filter(
                business=business,
            )
            .exclude(status=BusinessMember.Status.REMOVED)
            .filter(public_id=member_public_id)
            .first()
        )
        return business, actor, member

    def post(self, request, public_id, member_public_id):
        business, actor, member = self.get_member(
            request,
            public_id,
            member_public_id,
        )
        if member is None:
            return Response({"detail": "Not found."}, status=404)

        try:
            suspended = suspend_member(actor, member)
        except DjangoValidationError as error:
            return Response({"detail": str(error)}, status=400)

        return Response(BusinessMemberSerializer(suspended).data)


class BusinessMemberReactivateView(APIView):
    def get_member(self, request, public_id, member_public_id):
        """Resolve the Business, enforce MANAGE_MEMBERS, then resolve the member."""
        business = Business.objects.filter(public_id=public_id).first()
        if business is None:
            return None, None, None
        actor = require_permission(
            request.user,
            business,
            BusinessMemberPermission.Permission.MANAGE_MEMBERS,
            write=True,
        )
        member = (
            BusinessMember.objects.filter(
                business=business,
            )
            .exclude(status=BusinessMember.Status.REMOVED)
            .filter(public_id=member_public_id)
            .first()
        )
        return business, actor, member

    def post(self, request, public_id, member_public_id):
        business, actor, member = self.get_member(
            request,
            public_id,
            member_public_id,
        )
        if member is None:
            return Response({"detail": "Not found."}, status=404)

        try:
            reactivated = reactivate_member(actor, member)
        except DjangoValidationError as error:
            return Response({"detail": str(error)}, status=400)

        return Response(BusinessMemberSerializer(reactivated).data)


class BusinessPermissionCatalogView(APIView):
    """List every registered permission the owner may grant."""

    def get(self, request, public_id):
        business = Business.objects.filter(public_id=public_id).first()
        if business is None:
            return Response({"detail": "Not found."}, status=404)
        require_permission(
            request.user,
            business,
            BusinessMemberPermission.Permission.VIEW_MEMBERS,
        )

        catalog = [
            {"permission": value, "label": label}
            for value, label in BusinessMemberPermission.Permission.choices
        ]

        return Response(
            BusinessPermissionCatalogSerializer(catalog, many=True).data
        )


class BusinessMemberPermissionGrantView(APIView):
    """Grant one explicit permission (active OWNER only)."""

    http_method_names = ["get", "post", "head", "options"]

    def get_actor_and_member(self, request, public_id, member_public_id):
        """Resolve the Business, enforce active OWNER, then resolve the member."""
        business = Business.objects.filter(public_id=public_id).first()
        if business is None:
            return None, None, None
        actor = require_permission(
            request.user,
            business,
            BusinessMemberPermission.Permission.MANAGE_MEMBERS,
            write=True,
        )
        if not actor.is_owner:
            raise PermissionDenied("Forbidden.")
        member = (
            BusinessMember.objects.filter(
                business=business,
            )
            .exclude(status=BusinessMember.Status.REMOVED)
            .filter(public_id=member_public_id)
            .first()
        )
        return business, actor, member

    def get(self, request, public_id, member_public_id):
        """List a member's explicit permissions (VIEW_MEMBERS)."""
        business = Business.objects.filter(public_id=public_id).first()
        if business is None:
            return Response({"detail": "Not found."}, status=404)
        require_permission(
            request.user,
            business,
            BusinessMemberPermission.Permission.VIEW_MEMBERS,
        )
        member = (
            member_queryset(business)
            .filter(public_id=member_public_id)
            .first()
        )
        if member is None:
            return Response({"detail": "Not found."}, status=404)

        if member.is_owner:
            permissions = list(BusinessMemberPermission.Permission.values)
        else:
            prefetched = getattr(member, "_prefetched_permissions", None)
            if prefetched is not None:
                permissions = [row.permission for row in prefetched]
            else:
                permissions = list(
                    member.permissions.order_by("permission").values_list(
                        "permission",
                        flat=True,
                    )
                )

        return Response(
            BusinessMemberPermissionSerializer(
                [{"permission": value} for value in permissions],
                many=True,
            ).data
        )

    def post(self, request, public_id, member_public_id):
        business, actor, member = self.get_actor_and_member(
            request,
            public_id,
            member_public_id,
        )
        if member is None:
            return Response({"detail": "Not found."}, status=404)

        serializer = BusinessMemberPermissionGrantSerializer(
            data=request.data,
        )
        serializer.is_valid(raise_exception=True)

        try:
            grant_permission(
                actor,
                member,
                serializer.validated_data["permission"],
            )
        except DjangoValidationError as error:
            return Response({"detail": str(error)}, status=400)

        return Response(
            BusinessMemberPermissionSerializer(
                {"permission": serializer.validated_data["permission"]},
            ).data,
            status=201,
        )


class BusinessMemberPermissionDetailView(APIView):
    """Revoke one explicit permission (active OWNER only)."""

    http_method_names = ["delete", "head", "options"]

    def get_actor_and_member(self, request, public_id, member_public_id):
        """Resolve the Business, enforce active OWNER, then resolve the member."""
        business = Business.objects.filter(public_id=public_id).first()
        if business is None:
            return None, None, None
        actor = require_permission(
            request.user,
            business,
            BusinessMemberPermission.Permission.MANAGE_MEMBERS,
            write=True,
        )
        if not actor.is_owner:
            raise PermissionDenied("Forbidden.")
        member = (
            BusinessMember.objects.filter(
                business=business,
            )
            .exclude(status=BusinessMember.Status.REMOVED)
            .filter(public_id=member_public_id)
            .first()
        )
        return business, actor, member

    def delete(self, request, public_id, member_public_id, permission):
        business, actor, member = self.get_actor_and_member(
            request,
            public_id,
            member_public_id,
        )
        if member is None:
            return Response({"detail": "Not found."}, status=404)

        try:
            validate_permission(permission)
            revoke_permission(actor, member, permission)
        except DjangoValidationError as error:
            return Response({"detail": str(error)}, status=400)

        return Response(status=204)


class BusinessInvitationAdminMixin:
    """Resolve one tenant and its explicit invitation administrator."""

    def get_context(self, request, public_id, *, write=False):
        business = Business.objects.filter(public_id=public_id).first()
        if business is None:
            raise NotFound("Not found.")
        try:
            actor = require_permission(
                request.user,
                business,
                BusinessMemberPermission.Permission.MANAGE_MEMBERS,
            )
        except PermissionDenied as exc:
            raise InvitationPermissionDenied from exc
        if write and business.status != Business.Status.ACTIVE:
            state = (
                "suspendue"
                if business.status == Business.Status.SUSPENDED
                else "archivée"
            )
            return business, actor, _invitation_error(
                "business_inactive",
                f"Impossible d'envoyer une invitation lorsque l'entreprise est {state}.",
                status.HTTP_409_CONFLICT,
            )
        return business, actor, None

    def get_invitation(self, business, invitation_public_id):
        invitation = BusinessMemberInvitation.objects.filter(
            business=business,
            public_id=invitation_public_id,
        ).first()
        if invitation is None:
            raise NotFound("Invitation introuvable.")
        return invitation

    def delivery_error(self):
        return _invitation_error(
            "invitation_delivery_unavailable",
            "L'envoi de l'invitation est temporairement indisponible. Veuillez réessayer.",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )


class BusinessInvitationsView(BusinessInvitationAdminMixin, APIView):
    """List or create administrative Business member invitations."""

    def get(self, request, public_id):
        business, actor, error = self.get_context(
            request,
            public_id,
        )
        invitations = BusinessMemberInvitation.objects.filter(
            business=business,
        ).order_by("-created_at", "-id")
        paginator = InvitationPagination()
        page = paginator.paginate_queryset(invitations, request)
        return paginator.get_paginated_response(
            BusinessMemberInvitationSerializer(page, many=True).data
        )

    def post(self, request, public_id):
        business, actor, error = self.get_context(
            request,
            public_id,
            write=True,
        )
        if error:
            return error
        serializer = BusinessMemberInvitationCreateSerializer(
            data=request.data,
        )
        if not serializer.is_valid():
            email_errors = serializer.errors.get("email")
            if email_errors:
                return _invitation_error(
                    "invalid_email",
                    str(email_errors[0]),
                    status.HTTP_400_BAD_REQUEST,
                    field="email",
                )
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            invitation = create_and_send_invitation(
                actor,
                business,
                serializer.validated_data["email"],
                title=serializer.validated_data["title"],
            )
        except (
            InvitationDeliveryConfigurationError,
            InvitationDeliveryError,
        ):
            return self.delivery_error()
        except DjangoValidationError as exc:
            return _invitation_service_error(exc)

        return Response(
            BusinessMemberInvitationSerializer(invitation).data,
            status=status.HTTP_201_CREATED,
        )


class BusinessInvitationResendView(BusinessInvitationAdminMixin, APIView):
    """Rotate and redeliver one pending or expired invitation."""

    def post(self, request, public_id, invitation_public_id):
        business, actor, error = self.get_context(
            request,
            public_id,
            write=True,
        )
        if error:
            return error
        invitation = self.get_invitation(business, invitation_public_id)
        try:
            invitation = resend_member_invitation(actor, invitation)
        except (
            InvitationDeliveryConfigurationError,
            InvitationDeliveryError,
        ):
            return self.delivery_error()
        except DjangoValidationError as exc:
            return _invitation_service_error(exc)
        return Response(BusinessMemberInvitationSerializer(invitation).data)


class BusinessInvitationRevokeView(BusinessInvitationAdminMixin, APIView):
    """Revoke one pending invitation without creating a membership."""

    def post(self, request, public_id, invitation_public_id):
        business, actor, error = self.get_context(
            request,
            public_id,
            write=True,
        )
        if error:
            return error
        invitation = self.get_invitation(business, invitation_public_id)
        try:
            invitation = revoke_member_invitation(actor, invitation)
        except DjangoValidationError as exc:
            return _invitation_service_error(exc)
        return Response(BusinessMemberInvitationSerializer(invitation).data)


class BusinessPaymentMethodsView(APIView):
    serializer_class = BusinessPaymentMethodSerializer

    def get_readable_business(self, request, public_id):
        business = Business.objects.filter(public_id=public_id).first()
        if business is None:
            return None, None
        member = require_any_permission(
            request.user,
            business,
            (
                BusinessMemberPermission.Permission.VIEW_PAYMENT_METHODS,
                BusinessMemberPermission.Permission.USE_POS,
            ),
        )
        return business, member

    def get_authorized_business(self, request, public_id):
        business = Business.objects.filter(public_id=public_id).first()
        if business is None:
            return None
        require_permission(
            request.user,
            business,
            BusinessMemberPermission.Permission.MANAGE_PAYMENT_METHODS,
            write=True,
        )
        return business

    def get(self, request, public_id):
        business, member = self.get_readable_business(request, public_id)
        if not business:
            return Response({"detail": "Not found."}, status=404)
        methods = business.payment_methods.all()
        if not has_permission(
            member,
            BusinessMemberPermission.Permission.VIEW_PAYMENT_METHODS,
        ):
            methods = methods.filter(is_active=True)
        return Response(BusinessPaymentMethodSerializer(methods, many=True).data)

    def post(self, request, public_id):
        business = self.get_authorized_business(request, public_id)
        if business is None:
            return Response({"detail": "Not found."}, status=404)
        serializer = BusinessPaymentMethodSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(BusinessPaymentMethodSerializer(serializer.save(business=business)).data, status=201)


class BusinessPaymentMethodDetailView(BusinessPaymentMethodsView):
    serializer_class = BusinessPaymentMethodSerializer
    http_method_names = ["get", "patch", "head", "options"]

    def get_object(self, request, public_id, method_public_id):
        business, member = self.get_readable_business(request, public_id)
        if not business:
            return None, None, None
        method = business.payment_methods.filter(public_id=method_public_id).first()
        return business, member, method

    def get(self, request, public_id, method_public_id):
        _business, member, method = self.get_object(
            request,
            public_id,
            method_public_id,
        )
        if not method:
            return Response({"detail": "Not found."}, status=404)
        if not method.is_active and not has_permission(
            member,
            BusinessMemberPermission.Permission.VIEW_PAYMENT_METHODS,
        ):
            return Response({"detail": "Not found."}, status=404)
        return Response(BusinessPaymentMethodSerializer(method).data)

    def patch(self, request, public_id, method_public_id):
        business = self.get_authorized_business(request, public_id)
        method = (
            business.payment_methods.filter(public_id=method_public_id).first()
            if business
            else None
        )
        if not method:
            return Response({"detail": "Not found."}, status=404)
        serializer = BusinessPaymentMethodSerializer(method, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        return Response(BusinessPaymentMethodSerializer(serializer.save()).data)


class BusinessCategoriesView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        categories = BusinessCategory.objects.filter(is_active=True)

        return Response(CategorySerializer(categories, many=True).data)


# APIViews use explicit schemas because their serializer direction depends on the method.
_business_id = OpenApiParameter(
    "public_id",
    str,
    OpenApiParameter.PATH,
    description="Identifiant public Business, format SH + 10 caractères.",
)
_member_id = OpenApiParameter(
    "member_public_id",
    str,
    OpenApiParameter.PATH,
    description="Identifiant public BusinessMember, format BM + 10 caractères.",
)
_paginated_business_members = inline_serializer(
    name="PaginatedBusinessMemberList",
    fields={
        "count": serializers.IntegerField(),
        "next": serializers.URLField(allow_null=True),
        "previous": serializers.URLField(allow_null=True),
        "results": BusinessMemberSerializer(many=True),
    },
)
_invitation_id = OpenApiParameter(
    "invitation_public_id",
    str,
    OpenApiParameter.PATH,
    description="Identifiant public de l'invitation, format MI + 10 caractères.",
)
_paginated_business_invitations = inline_serializer(
    name="PaginatedBusinessMemberInvitationList",
    fields={
        "count": serializers.IntegerField(),
        "next": serializers.URLField(allow_null=True),
        "previous": serializers.URLField(allow_null=True),
        "results": BusinessMemberInvitationSerializer(many=True),
    },
)
_invitation_error_schema = inline_serializer(
    name="BusinessMemberInvitationError",
    fields={
        "code": serializers.CharField(),
        "detail": serializers.CharField(),
        "email": serializers.ListField(
            child=serializers.CharField(),
            required=False,
        ),
    },
)
_payment_method_id = OpenApiParameter(
    "method_public_id",
    str,
    OpenApiParameter.PATH,
    description="Identifiant public BusinessPaymentMethod, format PM + 10 caractères.",
)

BusinessesView.get = extend_schema(
    tags=["Businesses"],
    operation_id="business_list",
    responses={200: BusinessSerializer(many=True)},
)(BusinessesView.get)
BusinessesView.post = extend_schema(
    tags=["Businesses"],
    operation_id="business_create",
    request=BusinessCreateSerializer,
    responses={201: BusinessSerializer, 400: None},
)(BusinessesView.post)
BusinessDetailView.get = extend_schema(
    tags=["Businesses"],
    operation_id="business_retrieve",
    parameters=[_business_id],
    responses={200: BusinessSerializer, 404: None},
)(BusinessDetailView.get)
BusinessDetailView.patch = extend_schema(
    tags=["Businesses"],
    operation_id="business_update",
    parameters=[_business_id],
    request=BusinessUpdateSerializer,
    responses={200: BusinessSerializer, 403: None, 404: None},
)(BusinessDetailView.patch)
BusinessMembersView.get = extend_schema(
    tags=["Businesses"],
    operation_id="business_member_list",
    parameters=[
        _business_id,
        OpenApiParameter("page", int, OpenApiParameter.QUERY),
        OpenApiParameter(
            "page_size",
            int,
            OpenApiParameter.QUERY,
            description="Taille de page, de 1 à 50 (défaut 20).",
        ),
    ],
    responses={
        200: _paginated_business_members,
        403: None,
        404: None,
    },
)(BusinessMembersView.get)
BusinessMemberDetailView.get = extend_schema(
    tags=["Businesses"],
    operation_id="business_member_retrieve",
    parameters=[_business_id, _member_id],
    responses={200: BusinessMemberSerializer, 403: None, 404: None},
)(BusinessMemberDetailView.get)
BusinessMemberDetailView.patch = extend_schema(
    tags=["Businesses"],
    operation_id="business_member_update",
    parameters=[_business_id, _member_id],
    request=BusinessMemberTitleSerializer,
    responses={200: BusinessMemberSerializer, 400: None, 403: None, 404: None},
)(BusinessMemberDetailView.patch)
BusinessMemberDetailView.delete = extend_schema(
    tags=["Businesses"],
    operation_id="business_member_remove",
    parameters=[_business_id, _member_id],
    request=None,
    responses={204: None, 400: None, 403: None, 404: None},
)(BusinessMemberDetailView.delete)
BusinessMemberSuspendView.post = extend_schema(
    tags=["Businesses"],
    operation_id="business_member_suspend",
    parameters=[_business_id, _member_id],
    request=None,
    responses={200: BusinessMemberSerializer, 400: None, 403: None, 404: None},
)(BusinessMemberSuspendView.post)
BusinessMemberReactivateView.post = extend_schema(
    tags=["Businesses"],
    operation_id="business_member_reactivate",
    parameters=[_business_id, _member_id],
    request=None,
    responses={200: BusinessMemberSerializer, 400: None, 403: None, 404: None},
)(BusinessMemberReactivateView.post)
BusinessMemberPermissionGrantView.get = extend_schema(
    tags=["Businesses"],
    operation_id="business_member_permission_list",
    parameters=[_business_id, _member_id],
    responses={200: BusinessMemberPermissionSerializer(many=True), 403: None, 404: None},
)(BusinessMemberPermissionGrantView.get)
BusinessMemberPermissionGrantView.post = extend_schema(
    tags=["Businesses"],
    operation_id="business_member_permission_grant",
    parameters=[_business_id, _member_id],
    request=BusinessMemberPermissionGrantSerializer,
    responses={
        201: BusinessMemberPermissionSerializer,
        400: None,
        403: None,
        404: None,
    },
)(BusinessMemberPermissionGrantView.post)
BusinessMemberPermissionDetailView.delete = extend_schema(
    tags=["Businesses"],
    operation_id="business_member_permission_revoke",
    parameters=[
        _business_id,
        _member_id,
        OpenApiParameter(
            "permission",
            str,
            OpenApiParameter.PATH,
            description="Permission serveur enregistrée, par exemple VIEW_MEMBERS.",
        ),
    ],
    request=None,
    responses={204: None, 400: None, 403: None, 404: None},
)(BusinessMemberPermissionDetailView.delete)
BusinessPermissionCatalogView.get = extend_schema(
    tags=["Businesses"],
    operation_id="business_permission_catalog",
    parameters=[_business_id],
    responses={200: BusinessPermissionCatalogSerializer(many=True), 403: None, 404: None},
)(BusinessPermissionCatalogView.get)
BusinessInvitationsView.get = extend_schema(
    tags=["Business Invitations"],
    operation_id="business_invitation_list",
    summary="Lister les invitations d'une entreprise",
    description=(
        "Retourne une liste paginée des invitations administratives, y compris "
        "les états terminaux, sans jamais exposer le jeton ni son hash. Requiert "
        "MANAGE_MEMBERS ; OWNER actif dispose implicitement de cette permission. "
        "Paramètres de requête : page et page_size (20 par défaut, 50 maximum)."
    ),
    parameters=[_business_id],
    responses={
        200: _paginated_business_invitations,
        403: OpenApiResponse(
            response=_invitation_error_schema,
            description="Membre connu sans MANAGE_MEMBERS.",
        ),
        404: OpenApiResponse(description="Business inaccessible ou inexistant."),
    },
    examples=[
        OpenApiExample(
            "Liste paginée",
            value={
                "count": 1,
                "next": None,
                "previous": None,
                "results": [
                    {
                        "public_id": "MI23456789AB",
                        "email": "membre@example.com",
                        "title": "Caissier",
                        "status": "PENDING",
                        "expires_at": "2026-10-17T10:00:00+01:00",
                        "last_sent_at": "2026-10-10T10:00:01+01:00",
                        "resend_count": 0,
                        "created_at": "2026-10-10T10:00:00+01:00",
                        "updated_at": "2026-10-10T10:00:01+01:00",
                    }
                ],
            },
            response_only=True,
            status_codes=["200"],
        ),
    ],
)(BusinessInvitationsView.get)
BusinessInvitationsView.post = extend_schema(
    tags=["Business Invitations"],
    operation_id="business_invitation_create",
    summary="Inviter une personne à rejoindre une entreprise",
    description=(
        "Crée une invitation sans créer de BusinessMember ni attribuer de "
        "permission. Requiert MANAGE_MEMBERS et un Business ACTIVE. L'e-mail "
        "texte/HTML est envoyé après le commit ; l'URL publique et l'expéditeur "
        "doivent être configurés. Une adresse déjà membre ou déjà invitée est "
        "refusée. Le jeton brut n'est jamais retourné."
    ),
    parameters=[_business_id],
    request=BusinessMemberInvitationCreateSerializer,
    responses={
        201: BusinessMemberInvitationSerializer,
        400: OpenApiResponse(
            response=_invitation_error_schema,
            description="Adresse ou payload invalide.",
        ),
        403: OpenApiResponse(description="Permission MANAGE_MEMBERS absente."),
        404: OpenApiResponse(description="Business inaccessible ou inexistant."),
        409: OpenApiResponse(
            response=_invitation_error_schema,
            description="Invitation en attente, membre existant ou Business inactif.",
        ),
        503: OpenApiResponse(
            response=_invitation_error_schema,
            description="Configuration ou fournisseur d'e-mail indisponible.",
        ),
    },
    examples=[
        OpenApiExample(
            "Créer une invitation",
            value={"email": "membre@example.com", "title": "Caissier"},
            request_only=True,
        ),
        OpenApiExample(
            "Invitation déjà en attente",
            value={
                "code": "invitation_already_pending",
                "detail": "Une invitation est déjà en attente pour cette adresse e-mail.",
                "email": ["Une invitation est déjà en attente pour cette adresse e-mail."],
            },
            response_only=True,
            status_codes=["409"],
        ),
    ],
)(BusinessInvitationsView.post)
BusinessInvitationResendView.post = extend_schema(
    tags=["Business Invitations"],
    operation_id="business_invitation_resend",
    summary="Renvoyer une invitation",
    description=(
        "Requiert MANAGE_MEMBERS et un Business ACTIVE. Accepte une invitation "
        "PENDING ou EXPIRED, invalide son ancien jeton, renouvelle son expiration "
        "et programme un nouvel e-mail après commit. Aucun corps JSON n'est requis."
    ),
    parameters=[_business_id, _invitation_id],
    request=None,
    responses={
        200: BusinessMemberInvitationSerializer,
        403: OpenApiResponse(description="Permission MANAGE_MEMBERS absente."),
        404: OpenApiResponse(description="Business ou invitation inaccessible."),
        409: OpenApiResponse(
            response=_invitation_error_schema,
            description="État de l'invitation incompatible ou Business inactif.",
        ),
        503: OpenApiResponse(
            response=_invitation_error_schema,
            description="Envoi d'e-mail indisponible.",
        ),
    },
)(BusinessInvitationResendView.post)
BusinessInvitationRevokeView.post = extend_schema(
    tags=["Business Invitations"],
    operation_id="business_invitation_revoke",
    summary="Révoquer une invitation",
    description=(
        "Révoque sous verrou une invitation PENDING. Requiert MANAGE_MEMBERS "
        "et un Business ACTIVE. Aucun BusinessMember n'est créé et le jeton "
        "devient inutilisable. Aucun corps JSON n'est requis."
    ),
    parameters=[_business_id, _invitation_id],
    request=None,
    responses={
        200: BusinessMemberInvitationSerializer,
        403: OpenApiResponse(description="Permission MANAGE_MEMBERS absente."),
        404: OpenApiResponse(description="Business ou invitation inaccessible."),
        409: OpenApiResponse(
            response=_invitation_error_schema,
            description="Invitation non révoquable ou Business inactif.",
        ),
    },
)(BusinessInvitationRevokeView.post)
BusinessPaymentMethodsView.get = extend_schema(
    tags=["Business Payment Methods"],
    operation_id="business_payment_method_list",
    parameters=[_business_id],
    responses={
        200: BusinessPaymentMethodSerializer(many=True),
        403: None,
        404: None,
    },
)(BusinessPaymentMethodsView.get)
BusinessPaymentMethodsView.post = extend_schema(
    tags=["Business Payment Methods"],
    operation_id="business_payment_method_create",
    parameters=[_business_id],
    request=BusinessPaymentMethodSerializer,
    responses={
        201: BusinessPaymentMethodSerializer,
        400: None,
        403: None,
        404: None,
    },
)(BusinessPaymentMethodsView.post)
BusinessPaymentMethodDetailView.get = extend_schema(
    tags=["Business Payment Methods"],
    operation_id="business_payment_method_retrieve",
    parameters=[_business_id, _payment_method_id],
    responses={200: BusinessPaymentMethodSerializer, 403: None, 404: None},
)(BusinessPaymentMethodDetailView.get)
BusinessPaymentMethodDetailView.patch = extend_schema(
    tags=["Business Payment Methods"],
    operation_id="business_payment_method_update",
    parameters=[_business_id, _payment_method_id],
    request=BusinessPaymentMethodSerializer,
    responses={
        200: BusinessPaymentMethodSerializer,
        400: None,
        403: None,
        404: None,
    },
)(BusinessPaymentMethodDetailView.patch)
BusinessCategoriesView.get = extend_schema(
    tags=["Business Categories"],
    operation_id="business_category_list",
    auth=[],
    responses={200: CategorySerializer(many=True)},
)(BusinessCategoriesView.get)
