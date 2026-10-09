from django.db.models import Prefetch
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import permissions, serializers
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    Business,
    BusinessCategory,
    BusinessMember,
    BusinessMemberPermission,
    BusinessPaymentMethod,
)
from .permissions import has_permission, require_any_permission, require_permission
from .serializers import (
    BusinessCreateSerializer,
    BusinessMemberSerializer,
    BusinessSerializer,
    BusinessUpdateSerializer,
    CategorySerializer,
    BusinessPaymentMethodSerializer,
)
from .services import create_business, replace_categories


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
    def get(self, request, public_id, member_public_id):
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

        return Response(BusinessMemberSerializer(member).data)


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
