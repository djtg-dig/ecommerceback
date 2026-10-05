"""Public taxonomy reads and authenticated multi-tenant product APIs."""

from django.db import IntegrityError
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.businesses.models import Business
from apps.businesses.permissions import can_manage_business, membership_for

from .models import Product, ProductCategory, ProductVariant
from .serializers import (
    EffectiveAttributeSerializer,
    ProductCategorySerializer,
    ProductOutputSerializer,
    ProductVariantOutputSerializer,
    ProductVariantWriteSerializer,
    ProductWriteSerializer,
)
from .services import create_product, create_variant, effective_attributes


class ProductCategoryListView(generics.ListAPIView):
    """Expose active categories as a flat, deterministic hierarchy."""

    serializer_class = ProductCategorySerializer
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    pagination_class = None

    def get_queryset(self):
        return ProductCategory.objects.filter(is_active=True).select_related("parent")


class ProductCategoryAttributesView(generics.GenericAPIView):
    """Expose active attributes effective for one active category."""

    queryset = ProductCategory.objects.none()
    serializer_class = EffectiveAttributeSerializer
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request, code: str):
        category = generics.get_object_or_404(ProductCategory.objects.select_related("parent__parent"), code=code, is_active=True)
        return Response(self.get_serializer(effective_attributes(category), many=True).data)


class BusinessProductMixin:
    """Resolve a business only through the caller's active membership."""

    def get_business(self, request, business_public_id):
        return Business.objects.filter(
            public_id=business_public_id, members__identity=request.user, members__status="ACTIVE"
        ).distinct().first()

    def get_product(self, business, product_public_id):
        return Product.objects.filter(business=business, public_id=product_public_id).select_related("category", "business").first()

    @staticmethod
    def not_found():
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

    @staticmethod
    def forbidden():
        return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)


class ProductListCreateView(BusinessProductMixin, APIView):
    """List a member's products or create one as owner/manager."""

    def get(self, request, business_public_id):
        business = self.get_business(request, business_public_id)
        if not business:
            return self.not_found()
        products = Product.objects.filter(business=business).select_related("category")
        if value := request.query_params.get("status"):
            products = products.filter(status=value)
        if value := request.query_params.get("category"):
            products = products.filter(category__code=value)
        if value := request.query_params.get("search"):
            products = products.filter(name__icontains=value)
        return Response(ProductOutputSerializer(products, many=True).data)

    def post(self, request, business_public_id):
        business = self.get_business(request, business_public_id)
        if not business:
            return self.not_found()
        if not can_manage_business(membership_for(request.user, business)):
            return self.forbidden()
        serializer = ProductWriteSerializer(data=request.data, context={"business": business})
        serializer.is_valid(raise_exception=True)
        values = dict(serializer.validated_data)
        values.setdefault("currency", business.primary_currency)
        try:
            product = create_product(business=business, values=values)
        except IntegrityError:
            return Response({"detail": "Conflit de référence interne."}, status=400)
        return Response(ProductOutputSerializer(product).data, status=status.HTTP_201_CREATED)


class ProductDetailView(BusinessProductMixin, APIView):
    """Read or update one product, always scoped to its parent business."""

    def get(self, request, business_public_id, product_public_id):
        business = self.get_business(request, business_public_id)
        product = self.get_product(business, product_public_id) if business else None
        return Response(ProductOutputSerializer(product).data) if product else self.not_found()

    def patch(self, request, business_public_id, product_public_id):
        business = self.get_business(request, business_public_id)
        product = self.get_product(business, product_public_id) if business else None
        if not product:
            return self.not_found()
        if not can_manage_business(membership_for(request.user, business)):
            return self.forbidden()
        serializer = ProductWriteSerializer(product, data=request.data, partial=True, context={"business": business})
        serializer.is_valid(raise_exception=True)
        try:
            serializer.save()
        except IntegrityError:
            return Response({"detail": "Conflit de référence interne."}, status=400)
        return Response(ProductOutputSerializer(product).data)


class ProductArchiveView(BusinessProductMixin, APIView):
    """Archive instead of deleting a product, preserving future history."""

    def post(self, request, business_public_id, product_public_id):
        business = self.get_business(request, business_public_id)
        product = self.get_product(business, product_public_id) if business else None
        if not product:
            return self.not_found()
        if not can_manage_business(membership_for(request.user, business)):
            return self.forbidden()
        product.status = Product.Status.ARCHIVED
        product.save(update_fields=("status", "updated_at"))
        return Response(ProductOutputSerializer(product).data)


class ProductVariantListCreateView(BusinessProductMixin, APIView):
    """List variants to all members and create them for owners/managers."""

    def get_product_or_404(self, request, business_public_id, product_public_id):
        business = self.get_business(request, business_public_id)
        return business, self.get_product(business, product_public_id) if business else None

    def get(self, request, business_public_id, product_public_id):
        _, product = self.get_product_or_404(request, business_public_id, product_public_id)
        return Response(ProductVariantOutputSerializer(product.variants.all(), many=True).data) if product else self.not_found()

    def post(self, request, business_public_id, product_public_id):
        business, product = self.get_product_or_404(request, business_public_id, product_public_id)
        if not product:
            return self.not_found()
        if not can_manage_business(membership_for(request.user, business)):
            return self.forbidden()
        serializer = ProductVariantWriteSerializer(data=request.data, context={"product": product})
        serializer.is_valid(raise_exception=True)
        try:
            variant = create_variant(product=product, values=dict(serializer.validated_data))
        except IntegrityError:
            return Response({"detail": "Combinaison de variante ou référence interne déjà utilisée."}, status=400)
        return Response(ProductVariantOutputSerializer(variant).data, status=status.HTTP_201_CREATED)


class ProductVariantDetailView(BusinessProductMixin, APIView):
    """Read or update a variant after both product and business scoping."""

    def get_product_or_404(self, request, business_public_id, product_public_id):
        business = self.get_business(request, business_public_id)
        return business, self.get_product(business, product_public_id) if business else None

    def get_variant(self, product, variant_public_id):
        return ProductVariant.objects.filter(product=product, public_id=variant_public_id).select_related("product__category", "product__business").first()

    def get(self, request, business_public_id, product_public_id, variant_public_id):
        _, product = self.get_product_or_404(request, business_public_id, product_public_id)
        variant = self.get_variant(product, variant_public_id) if product else None
        return Response(ProductVariantOutputSerializer(variant).data) if variant else self.not_found()

    def patch(self, request, business_public_id, product_public_id, variant_public_id):
        business, product = self.get_product_or_404(request, business_public_id, product_public_id)
        variant = self.get_variant(product, variant_public_id) if product else None
        if not variant:
            return self.not_found()
        if not can_manage_business(membership_for(request.user, business)):
            return self.forbidden()
        serializer = ProductVariantWriteSerializer(variant, data=request.data, partial=True, context={"product": product})
        serializer.is_valid(raise_exception=True)
        try:
            serializer.save()
        except IntegrityError:
            return Response({"detail": "Combinaison de variante ou référence interne déjà utilisée."}, status=400)
        return Response(ProductVariantOutputSerializer(variant).data)

from drf_spectacular.utils import OpenApiParameter, extend_schema

_business_public_id = OpenApiParameter("business_public_id", str, OpenApiParameter.PATH, description="Identifiant public Business, format SH + 10 caractères.")
_product_public_id = OpenApiParameter("product_public_id", str, OpenApiParameter.PATH, description="Identifiant public Product, format PR + 10 caractères.")
_variant_public_id = OpenApiParameter("variant_public_id", str, OpenApiParameter.PATH, description="Identifiant public ProductVariant, format PV + 10 caractères.")
_category_code = OpenApiParameter("code", str, OpenApiParameter.PATH, description="Code de ProductCategory.")

ProductCategoryListView.get = extend_schema(tags=["Product Categories"], operation_id="product_category_list", auth=[], responses={200: ProductCategorySerializer(many=True)})(ProductCategoryListView.get)
ProductCategoryAttributesView.get = extend_schema(tags=["Product Categories"], operation_id="product_category_effective_attributes", auth=[], parameters=[_category_code], responses={200: EffectiveAttributeSerializer(many=True), 404: None})(ProductCategoryAttributesView.get)
ProductListCreateView.get = extend_schema(tags=["Products"], operation_id="product_list", parameters=[_business_public_id, OpenApiParameter("status", str, OpenApiParameter.QUERY), OpenApiParameter("category", str, OpenApiParameter.QUERY), OpenApiParameter("search", str, OpenApiParameter.QUERY)], responses={200: ProductOutputSerializer(many=True), 404: None})(ProductListCreateView.get)
ProductListCreateView.post = extend_schema(tags=["Products"], operation_id="product_create", parameters=[_business_public_id], request=ProductWriteSerializer, responses={201: ProductOutputSerializer, 400: None, 403: None, 404: None})(ProductListCreateView.post)
ProductDetailView.get = extend_schema(tags=["Products"], operation_id="product_retrieve", parameters=[_business_public_id, _product_public_id], responses={200: ProductOutputSerializer, 404: None})(ProductDetailView.get)
ProductDetailView.patch = extend_schema(tags=["Products"], operation_id="product_update", parameters=[_business_public_id, _product_public_id], request=ProductWriteSerializer, responses={200: ProductOutputSerializer, 400: None, 403: None, 404: None})(ProductDetailView.patch)
ProductArchiveView.post = extend_schema(tags=["Products"], operation_id="product_archive", parameters=[_business_public_id, _product_public_id], request=None, responses={200: ProductOutputSerializer, 403: None, 404: None})(ProductArchiveView.post)
ProductVariantListCreateView.get = extend_schema(tags=["Product Variants"], operation_id="product_variant_list", parameters=[_business_public_id, _product_public_id], responses={200: ProductVariantOutputSerializer(many=True), 404: None})(ProductVariantListCreateView.get)
ProductVariantListCreateView.post = extend_schema(tags=["Product Variants"], operation_id="product_variant_create", parameters=[_business_public_id, _product_public_id], request=ProductVariantWriteSerializer, responses={201: ProductVariantOutputSerializer, 400: None, 403: None, 404: None})(ProductVariantListCreateView.post)
ProductVariantDetailView.get = extend_schema(tags=["Product Variants"], operation_id="product_variant_retrieve", parameters=[_business_public_id, _product_public_id, _variant_public_id], responses={200: ProductVariantOutputSerializer, 404: None})(ProductVariantDetailView.get)
ProductVariantDetailView.patch = extend_schema(tags=["Product Variants"], operation_id="product_variant_update", parameters=[_business_public_id, _product_public_id, _variant_public_id], request=ProductVariantWriteSerializer, responses={200: ProductVariantOutputSerializer, 400: None, 403: None, 404: None})(ProductVariantDetailView.patch)
