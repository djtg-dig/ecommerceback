from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Business, BusinessCategory, BusinessPaymentMethod
from .permissions import can_manage_business, can_view_members, membership_for
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
        business = self.get_object(request, public_id)
        if not business:
            return Response({"detail": "Not found."}, status=404)

        if not can_manage_business(membership_for(request.user, business)):
            return Response({"detail": "Forbidden."}, status=403)

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
        business = accessible(request.user).filter(public_id=public_id).first()
        if not business:
            return Response({"detail": "Not found."}, status=404)

        if not can_view_members(membership_for(request.user, business)):
            return Response({"detail": "Forbidden."}, status=403)

        serializer = BusinessMemberSerializer(
            business.members.all(),
            many=True,
        )

        return Response(serializer.data)


class BusinessPaymentMethodsView(APIView):
    serializer_class = BusinessPaymentMethodSerializer
    def get_business(self, request, public_id):
        return accessible(request.user).filter(public_id=public_id).first()

    def get(self, request, public_id):
        business = self.get_business(request, public_id)
        if not business:
            return Response({"detail": "Not found."}, status=404)
        methods = business.payment_methods.all()
        if not can_manage_business(membership_for(request.user, business)):
            methods = methods.filter(is_active=True)
        return Response(BusinessPaymentMethodSerializer(methods, many=True).data)

    def post(self, request, public_id):
        business = self.get_business(request, public_id)
        if not business:
            return Response({"detail": "Not found."}, status=404)
        if not can_manage_business(membership_for(request.user, business)):
            return Response({"detail": "Forbidden."}, status=403)
        serializer = BusinessPaymentMethodSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(BusinessPaymentMethodSerializer(serializer.save(business=business)).data, status=201)


class BusinessPaymentMethodDetailView(BusinessPaymentMethodsView):
    serializer_class = BusinessPaymentMethodSerializer
    http_method_names = ["get", "patch", "head", "options"]
    def get_object(self, request, public_id, method_public_id):
        business = self.get_business(request, public_id)
        if not business:
            return None, None
        return business, business.payment_methods.filter(public_id=method_public_id).first()

    def get(self, request, public_id, method_public_id):
        business, method = self.get_object(request, public_id, method_public_id)
        if not method:
            return Response({"detail": "Not found."}, status=404)
        if not method.is_active and not can_manage_business(membership_for(request.user, business)):
            return Response({"detail": "Not found."}, status=404)
        return Response(BusinessPaymentMethodSerializer(method).data)

    def patch(self, request, public_id, method_public_id):
        business, method = self.get_object(request, public_id, method_public_id)
        if not method:
            return Response({"detail": "Not found."}, status=404)
        if not can_manage_business(membership_for(request.user, business)):
            return Response({"detail": "Forbidden."}, status=403)
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
    parameters=[_business_id],
    responses={200: BusinessMemberSerializer(many=True), 403: None, 404: None},
)(BusinessMembersView.get)
BusinessCategoriesView.get = extend_schema(
    tags=["Business Categories"],
    operation_id="business_category_list",
    auth=[],
    responses={200: CategorySerializer(many=True)},
)(BusinessCategoriesView.get)
