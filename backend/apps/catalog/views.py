"""Unauthenticated read endpoints for the global product taxonomy."""

from rest_framework import generics
from rest_framework.response import Response
from rest_framework.permissions import AllowAny

from .models import ProductCategory
from .serializers import EffectiveAttributeSerializer, ProductCategorySerializer
from .services import effective_attributes


class ProductCategoryListView(generics.ListAPIView):
    """Expose active categories as a flat, deterministic hierarchy."""

    serializer_class = ProductCategorySerializer
    permission_classes = [AllowAny]
    authentication_classes = []
    pagination_class = None

    def get_queryset(self):
        return ProductCategory.objects.filter(is_active=True).select_related("parent")


class ProductCategoryAttributesView(generics.GenericAPIView):
    """Expose active attributes effective for one active category."""

    serializer_class = EffectiveAttributeSerializer
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, code: str):
        category = generics.get_object_or_404(
            ProductCategory.objects.select_related("parent__parent"), code=code, is_active=True
        )
        return self.get_response(category)

    def get_response(self, category: ProductCategory):
        return Response(self.get_serializer(effective_attributes(category), many=True).data)
