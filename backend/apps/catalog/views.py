"""Public taxonomy reads and authenticated multi-tenant product APIs."""

from django.core.exceptions import ValidationError as DjangoValidationError
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.db.models import DecimalField, Exists, F, OuterRef, Prefetch, Q, Subquery, Value
from django.db.models.functions import Coalesce, Trim, Upper
from rest_framework import generics, permissions, serializers, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.businesses.models import Business, BusinessMemberPermission
from apps.businesses.permissions import require_permission
from apps.common.media import MediaStorageError

from .models import Product, ProductCategory, ProductVariant, ProductMedia, UnitOfMeasure
from .media import ProductMediaSerializer, create_product_media, delete_product_media, update_product_media
from .registry import get_category as get_registry_category
from .registry import list_categories as list_registry_categories
from .serializers import (
    EffectiveAttributeSerializer,
    ProductCategorySerializer,
    ProductPageSerializer,
    ProductOutputSerializer,
    ProductVariantOutputSerializer,
    ProductVariantWriteSerializer,
    ProductWriteSerializer,
    PosSearchResultSerializer,
    UnitOfMeasureSerializer,
)
from .services import create_product, create_variant, effective_attributes


class PosPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 50


class ProductPagination(PageNumberPagination):
    """Paginer le catalogue à dix produits, sans laisser le client élargir la page."""

    page_size = 10
    page_size_query_param = None


def _variant_label(attributes):
    """Render variant axes as a stable, small label without exposing raw JSON."""
    if not attributes:
        return None
    return " · ".join(f"{key}: {value}" for key, value in sorted(attributes.items()))


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


class ProductCategoryRegistryListView(APIView):
    """Expose code-defined categories without reading or populating taxonomy tables."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response(
            [category.public(include_attributes=False) for category in list_registry_categories()]
        )


class ProductCategoryRegistryDetailView(APIView):
    """Expose attributes, options and constraints for one code-defined category."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request, code: str):
        category = get_registry_category(code)
        if category is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(category.public(include_attributes=True))


class UnitOfMeasureListView(generics.ListAPIView):
    """Expose the shared read-only unit reference data to product forms."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    pagination_class = None

    def get_queryset(self):
        return UnitOfMeasure.objects.all()

    def get(self, request, *args, **kwargs):
        """Liste les unités partagées sans hériter du contrat des catégories."""
        return super().get(request, *args, **kwargs)

    def get_serializer_class(self):
        return UnitOfMeasureSerializer


class BusinessProductMixin:
    """Resolve one tenant and enforce its server-defined permission."""

    def get_business(
        self,
        request,
        business_public_id,
        permission,
        *,
        write=False,
    ):
        business = Business.objects.filter(public_id=business_public_id).first()
        if business is None:
            return None

        require_permission(
            request.user,
            business,
            permission,
            write=write,
        )
        return business

    def get_product(self, business, product_public_id):
        return Product.objects.filter(business=business, public_id=product_public_id).select_related("category", "business").first()

    @staticmethod
    def not_found():
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

    @staticmethod
    def forbidden():
        return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)


def media_error_response(error):
    """Translate storage failures without exposing the provider's internals."""
    return Response(
        {"code": error.code, "detail": error.detail, "message": error.detail},
        status=error.status_code,
    )


class ProductListCreateView(BusinessProductMixin, APIView):
    """List or create products under granular catalog permissions."""

    def get(self, request, business_public_id):
        business = self.get_business(
            request,
            business_public_id,
            BusinessMemberPermission.Permission.PRODUCT_VIEW,
        )
        if not business:
            return self.not_found()
        products = Product.objects.filter(business=business).select_related(
            "category",
            "unit_of_measure",
        ).prefetch_related(
            Prefetch(
                "media",
                queryset=ProductMedia.objects.filter(media_type=ProductMedia.MediaType.IMAGE)
                .only("id", "product_id", "secure_url", "is_primary", "position", "created_at")
                .order_by("position", "created_at", "id"),
            ),
        )
        if value := request.query_params.get("status"):
            products = products.filter(status=value)
        if value := request.query_params.get("category"):
            products = products.filter(Q(category__code=value) | Q(category_code=value))
        if value := request.query_params.get("search"):
            products = products.filter(name__icontains=value)
        products = products.order_by("name", "public_id")
        paginator = ProductPagination()
        page = paginator.paginate_queryset(products, request)
        return paginator.get_paginated_response(ProductOutputSerializer(page, many=True).data)

    def post(self, request, business_public_id):
        business = self.get_business(
            request,
            business_public_id,
            BusinessMemberPermission.Permission.PRODUCT_CREATE,
            write=True,
        )
        if not business:
            return self.not_found()
        serializer = ProductWriteSerializer(data=request.data, context={"business": business})
        serializer.is_valid(raise_exception=True)
        values = dict(serializer.validated_data)
        values["currency"] = business.primary_currency
        try:
            product = create_product(business=business, values=values)
        except IntegrityError:
            return Response({"detail": "Conflit de référence interne."}, status=400)
        return Response(ProductOutputSerializer(product).data, status=status.HTTP_201_CREATED)


class PosSearchView(BusinessProductMixin, APIView):
    """Search currently sellable catalog targets in one compact POS projection."""

    serializer_class = PosSearchResultSerializer

    def _products(self, business):
        from apps.inventory.models import InventoryItem

        active_variants = ProductVariant.objects.filter(
            product_id=OuterRef("pk"),
            status=ProductVariant.Status.ACTIVE,
        )
        available_stock = InventoryItem.objects.filter(product_id=OuterRef("pk")).annotate(
            available=F("quantity") - F("reserved_quantity")
        ).values("available")[:1]
        return Product.objects.filter(business=business, status=Product.Status.ACTIVE).select_related("unit_of_measure").annotate(
            has_active_variant=Exists(active_variants),
            pos_available_quantity=Coalesce(
                Subquery(available_stock, output_field=DecimalField(max_digits=14, decimal_places=3)),
                Value(Decimal("0.000")),
                output_field=DecimalField(max_digits=14, decimal_places=3),
            ),
        ).filter(has_active_variant=False)

    def _variants(self, business):
        from apps.inventory.models import InventoryItem

        available_stock = InventoryItem.objects.filter(variant_id=OuterRef("pk")).annotate(
            available=F("quantity") - F("reserved_quantity")
        ).values("available")[:1]
        return ProductVariant.objects.filter(
            product__business=business,
            product__status=Product.Status.ACTIVE,
            status=ProductVariant.Status.ACTIVE,
        ).select_related("product__unit_of_measure").annotate(
            pos_available_quantity=Coalesce(
                Subquery(available_stock, output_field=DecimalField(max_digits=14, decimal_places=3)),
                Value(Decimal("0.000")),
                output_field=DecimalField(max_digits=14, decimal_places=3),
            )
        )

    @staticmethod
    def _serialize(items):
        rows = []
        for item in items:
            if isinstance(item, Product):
                rows.append(
                    {
                        "type": "PRODUCT",
                        "public_id": item.public_id,
                        "product_public_id": item.public_id,
                        "name": item.name,
                        "variant_label": None,
                        "internal_reference": item.internal_reference,
                        "barcode": item.barcode,
                        "effective_price": item.selling_price,
                        "currency": item.currency,
                        "available_quantity": item.pos_available_quantity,
                        "unit_code": item.unit_of_measure.code,
                        "unit_symbol": item.unit_of_measure.symbol,
                        "allows_decimal_quantity": item.unit_of_measure.allows_decimal_quantity,
                    }
                )
            else:
                rows.append(
                    {
                        "type": "VARIANT",
                        "public_id": item.public_id,
                        "product_public_id": item.product.public_id,
                        "name": item.product.name,
                        "variant_label": _variant_label(item.attributes),
                        "internal_reference": item.internal_reference,
                        "barcode": item.barcode,
                        "effective_price": item.effective_selling_price,
                        "currency": item.product.currency,
                        "available_quantity": item.pos_available_quantity,
                        "unit_code": item.product.unit_of_measure.code,
                        "unit_symbol": item.product.unit_of_measure.symbol,
                        "allows_decimal_quantity": item.product.unit_of_measure.allows_decimal_quantity,
                    }
                )
        return rows

    def _result_data(self, items):
        return self.serializer_class(self._serialize(items), many=True).data

    @staticmethod
    def _exact(products, variants, field, value):
        if field == "public_id":
            return list(products.filter(public_id=value)) + list(variants.filter(public_id=value))
        expression = Trim(field) if field == "barcode" else Upper(Trim("internal_reference"))
        normalized = value if field == "barcode" else value.upper()
        return (
            list(products.annotate(pos_exact=expression).filter(pos_exact=normalized))
            + list(variants.annotate(pos_exact=expression).filter(pos_exact=normalized))
        )

    def get(self, request, business_public_id):
        business = self.get_business(
            request,
            business_public_id,
            BusinessMemberPermission.Permission.SALE_CREATE,
        )
        if not business:
            return self.not_found()
        raw_query = request.query_params.get("q")
        if raw_query is None or not raw_query.strip():
            return Response({"q": ["This query parameter is required."]}, status=status.HTTP_400_BAD_REQUEST)
        query = raw_query.strip()
        products, variants = self._products(business), self._variants(business)
        for field, code, detail in (
            ("public_id", None, None),
            ("barcode", "pos_barcode_conflict", "Multiple sellable items use this barcode."),
            ("sku", "pos_sku_conflict", "Multiple sellable items use this SKU."),
        ):
            matches = self._exact(products, variants, field, query)
            if len(matches) > 1:
                return Response({"code": code, "detail": detail}, status=status.HTTP_409_CONFLICT)
            if matches:
                return Response(
                    {"count": 1, "next": None, "previous": None, "results": self._result_data(matches)}
                )
        results = self._result_data(
            list(products.filter(name__icontains=query))
            + list(variants.filter(product__name__icontains=query))
        )
        results.sort(key=lambda row: (row["name"].casefold(), row["type"], row["public_id"]))
        paginator = PosPagination()
        page = paginator.paginate_queryset(results, request)
        return paginator.get_paginated_response(page)


class ProductDetailView(BusinessProductMixin, APIView):
    """Read or update one product, always scoped to its parent business."""

    def get(self, request, business_public_id, product_public_id):
        business = self.get_business(
            request,
            business_public_id,
            BusinessMemberPermission.Permission.PRODUCT_VIEW,
        )
        product = self.get_product(business, product_public_id) if business else None
        return Response(ProductOutputSerializer(product).data) if product else self.not_found()

    def patch(self, request, business_public_id, product_public_id):
        business = self.get_business(
            request,
            business_public_id,
            BusinessMemberPermission.Permission.PRODUCT_UPDATE,
            write=True,
        )
        product = self.get_product(business, product_public_id) if business else None
        if not product:
            return self.not_found()
        serializer = ProductWriteSerializer(product, data=request.data, partial=True, context={"business": business})
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                serializer.save()
        except IntegrityError:
            return Response({"detail": "Conflit de référence interne."}, status=400)
        return Response(ProductOutputSerializer(product).data)

    def delete(self, request, business_public_id, product_public_id):
        business = self.get_business(
            request,
            business_public_id,
            BusinessMemberPermission.Permission.PRODUCT_DELETE,
            write=True,
        )
        product = self.get_product(business, product_public_id) if business else None
        if not product:
            return self.not_found()
        try:
            product.delete()
        except ProtectedError:
            return Response(
                {"detail": "Ce produit est référencé et ne peut pas être supprimé."},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProductMediaListCreateView(BusinessProductMixin, APIView):
    """Tenant-scoped product gallery; files are validated by the media service."""

    def _product(self, request, business_public_id, product_public_id, permission, *, write=False):
        business = self.get_business(request, business_public_id, permission, write=write)
        product = self.get_product(business, product_public_id) if business else None
        return business, product

    def get(self, request, business_public_id, product_public_id):
        _, product = self._product(request, business_public_id, product_public_id, BusinessMemberPermission.Permission.PRODUCT_VIEW)
        if not product:
            return self.not_found()
        return Response(ProductMediaSerializer(product.media.all(), many=True).data)

    def post(self, request, business_public_id, product_public_id):
        _, product = self._product(request, business_public_id, product_public_id, BusinessMemberPermission.Permission.PRODUCT_UPDATE, write=True)
        if not product:
            return self.not_found()
        media_type = str(request.data.get("media_type", "")).upper()
        if media_type not in ProductMedia.MediaType.values:
            return Response({"media_type": "Choisissez IMAGE ou VIDEO."}, status=status.HTTP_400_BAD_REQUEST)
        upload = request.FILES.get("file")
        if upload is None:
            return Response({"file": "Un fichier est requis."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            item = create_product_media(product=product, upload=upload, media_type=media_type)
        except DjangoValidationError as exc:
            return Response(
                exc.message_dict if hasattr(exc, "message_dict") else {"detail": exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except MediaStorageError as exc:
            return media_error_response(exc)
        return Response(ProductMediaSerializer(item).data, status=status.HTTP_201_CREATED)


class ProductMediaDetailView(ProductMediaListCreateView):
    def item(self, product, media_id):
        return ProductMedia.objects.filter(product=product, id=media_id).first()

    def patch(self, request, business_public_id, product_public_id, media_id):
        _, product = self._product(request, business_public_id, product_public_id, BusinessMemberPermission.Permission.PRODUCT_UPDATE, write=True)
        media = self.item(product, media_id) if product else None
        if not media:
            return self.not_found()
        is_primary = request.data.get("is_primary") if "is_primary" in request.data else None
        position = request.data.get("position") if "position" in request.data else None
        if is_primary is not None and not isinstance(is_primary, bool):
            return Response({"is_primary": "Boolean attendu."}, status=status.HTTP_400_BAD_REQUEST)
        if position is not None and (not isinstance(position, int) or position < 0):
            return Response({"position": "Entier positif attendu."}, status=status.HTTP_400_BAD_REQUEST)
        item = update_product_media(product=product, media=media, is_primary=is_primary, position=position)
        return Response(ProductMediaSerializer(item).data)

    def delete(self, request, business_public_id, product_public_id, media_id):
        _, product = self._product(request, business_public_id, product_public_id, BusinessMemberPermission.Permission.PRODUCT_UPDATE, write=True)
        media = self.item(product, media_id) if product else None
        if not media:
            return self.not_found()
        delete_product_media(product=product, media=media)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProductArchiveView(BusinessProductMixin, APIView):
    """Archive instead of deleting a product, preserving future history."""

    def post(self, request, business_public_id, product_public_id):
        business = self.get_business(
            request,
            business_public_id,
            BusinessMemberPermission.Permission.PRODUCT_DEACTIVATE,
            write=True,
        )
        product = self.get_product(business, product_public_id) if business else None
        if not product:
            return self.not_found()
        product.status = Product.Status.ARCHIVED
        product.save(update_fields=("status", "updated_at"))
        return Response(ProductOutputSerializer(product).data)


class ProductVariantListCreateView(BusinessProductMixin, APIView):
    """List or create variants under granular catalog permissions."""

    def get_product_or_404(
        self,
        request,
        business_public_id,
        product_public_id,
        permission,
        *,
        write=False,
    ):
        business = self.get_business(
            request,
            business_public_id,
            permission,
            write=write,
        )
        return business, self.get_product(business, product_public_id) if business else None

    def get(self, request, business_public_id, product_public_id):
        _, product = self.get_product_or_404(
            request,
            business_public_id,
            product_public_id,
            BusinessMemberPermission.Permission.PRODUCT_VARIANT_VIEW,
        )
        return Response(ProductVariantOutputSerializer(product.variants.all(), many=True).data) if product else self.not_found()

    def post(self, request, business_public_id, product_public_id):
        business, product = self.get_product_or_404(
            request,
            business_public_id,
            product_public_id,
            BusinessMemberPermission.Permission.PRODUCT_VARIANT_CREATE,
            write=True,
        )
        if not product:
            return self.not_found()
        serializer = ProductVariantWriteSerializer(data=request.data, context={"product": product})
        serializer.is_valid(raise_exception=True)
        try:
            from apps.inventory.services import ensure_can_create_variant
            ensure_can_create_variant(product)
            variant = create_variant(product=product, values=dict(serializer.validated_data))
        except DjangoValidationError as exc:
            return Response(exc.message_dict if hasattr(exc, "message_dict") else {"detail": exc.messages}, status=400)
        except IntegrityError:
            return Response({"detail": "Combinaison de variante ou référence interne déjà utilisée."}, status=400)
        return Response(ProductVariantOutputSerializer(variant).data, status=status.HTTP_201_CREATED)


class ProductVariantDetailView(BusinessProductMixin, APIView):
    """Read or update a variant after both product and business scoping."""

    def get_product_or_404(
        self,
        request,
        business_public_id,
        product_public_id,
        permission,
        *,
        write=False,
    ):
        business = self.get_business(
            request,
            business_public_id,
            permission,
            write=write,
        )
        return business, self.get_product(business, product_public_id) if business else None

    def get_variant(self, product, variant_public_id):
        return ProductVariant.objects.filter(product=product, public_id=variant_public_id).select_related("product__category", "product__business").first()

    def get(self, request, business_public_id, product_public_id, variant_public_id):
        _, product = self.get_product_or_404(
            request,
            business_public_id,
            product_public_id,
            BusinessMemberPermission.Permission.PRODUCT_VARIANT_VIEW,
        )
        variant = self.get_variant(product, variant_public_id) if product else None
        return Response(ProductVariantOutputSerializer(variant).data) if variant else self.not_found()

    def patch(self, request, business_public_id, product_public_id, variant_public_id):
        business, product = self.get_product_or_404(
            request,
            business_public_id,
            product_public_id,
            BusinessMemberPermission.Permission.PRODUCT_VARIANT_UPDATE,
            write=True,
        )
        variant = self.get_variant(product, variant_public_id) if product else None
        if not variant:
            return self.not_found()
        serializer = ProductVariantWriteSerializer(variant, data=request.data, partial=True, context={"product": product})
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                serializer.save()
        except IntegrityError:
            return Response({"detail": "Combinaison de variante ou référence interne déjà utilisée."}, status=400)
        return Response(ProductVariantOutputSerializer(variant).data)

from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer

_business_public_id = OpenApiParameter("business_public_id", str, OpenApiParameter.PATH, description="Identifiant public Business, format SH + 10 caractères.")
_product_public_id = OpenApiParameter("product_public_id", str, OpenApiParameter.PATH, description="Identifiant public Product, format PR + 10 caractères.")
_variant_public_id = OpenApiParameter("variant_public_id", str, OpenApiParameter.PATH, description="Identifiant public ProductVariant, format PV + 10 caractères.")
_category_code = OpenApiParameter("code", str, OpenApiParameter.PATH, description="Code de ProductCategory.")

ProductCategoryListView.get = extend_schema(tags=["Product Categories"], operation_id="product_category_list", auth=[], responses={200: ProductCategorySerializer(many=True)})(ProductCategoryListView.get)
ProductCategoryAttributesView.get = extend_schema(tags=["Product Categories"], operation_id="product_category_effective_attributes", auth=[], parameters=[_category_code], responses={200: EffectiveAttributeSerializer(many=True), 404: None})(ProductCategoryAttributesView.get)
ProductCategoryRegistryListView.get = extend_schema(tags=["Product Categories"], operation_id="product_category_registry_list", auth=[], responses={200: dict})(ProductCategoryRegistryListView.get)
ProductCategoryRegistryDetailView.get = extend_schema(tags=["Product Categories"], operation_id="product_category_registry_retrieve", auth=[], parameters=[_category_code], responses={200: dict, 404: None})(ProductCategoryRegistryDetailView.get)
ProductListCreateView.get = extend_schema(tags=["Products"], operation_id="product_list", parameters=[_business_public_id, OpenApiParameter("status", str, OpenApiParameter.QUERY), OpenApiParameter("category", str, OpenApiParameter.QUERY), OpenApiParameter("search", str, OpenApiParameter.QUERY), OpenApiParameter("page", int, OpenApiParameter.QUERY, description="Page positive, 10 produits par page.")], responses={200: ProductPageSerializer, 403: None, 404: None})(ProductListCreateView.get)
ProductListCreateView.post = extend_schema(tags=["Products"], operation_id="product_create", parameters=[_business_public_id], request=ProductWriteSerializer, responses={201: ProductOutputSerializer, 400: None, 403: None, 404: None})(ProductListCreateView.post)
PosSearchView.get = extend_schema(
    tags=["Products"],
    operation_id="pos_product_search",
    parameters=[
        _business_public_id,
        OpenApiParameter("q", str, OpenApiParameter.QUERY, required=True),
        OpenApiParameter("page", int, OpenApiParameter.QUERY),
        OpenApiParameter("page_size", int, OpenApiParameter.QUERY),
    ],
    responses={200: PosSearchResultSerializer(many=True), 400: None, 403: None, 404: None, 409: None},
    description="Compact POS search: public ID, trimmed barcode, normalized SKU, then name search.",
)(PosSearchView.get)
ProductDetailView.get = extend_schema(tags=["Products"], operation_id="product_retrieve", parameters=[_business_public_id, _product_public_id], responses={200: ProductOutputSerializer, 403: None, 404: None})(ProductDetailView.get)
ProductDetailView.patch = extend_schema(tags=["Products"], operation_id="product_update", parameters=[_business_public_id, _product_public_id], request=ProductWriteSerializer, responses={200: ProductOutputSerializer, 400: None, 403: None, 404: None})(ProductDetailView.patch)
ProductDetailView.delete = extend_schema(tags=["Products"], operation_id="product_delete", parameters=[_business_public_id, _product_public_id], responses={204: None, 403: None, 404: None, 409: None})(ProductDetailView.delete)
ProductArchiveView.post = extend_schema(tags=["Products"], operation_id="product_archive", parameters=[_business_public_id, _product_public_id], request=None, responses={200: ProductOutputSerializer, 403: None, 404: None})(ProductArchiveView.post)
ProductVariantListCreateView.get = extend_schema(tags=["Product Variants"], operation_id="product_variant_list", parameters=[_business_public_id, _product_public_id], responses={200: ProductVariantOutputSerializer(many=True), 403: None, 404: None})(ProductVariantListCreateView.get)
ProductVariantListCreateView.post = extend_schema(tags=["Product Variants"], operation_id="product_variant_create", parameters=[_business_public_id, _product_public_id], request=ProductVariantWriteSerializer, responses={201: ProductVariantOutputSerializer, 400: None, 403: None, 404: None})(ProductVariantListCreateView.post)
ProductVariantDetailView.get = extend_schema(tags=["Product Variants"], operation_id="product_variant_retrieve", parameters=[_business_public_id, _product_public_id, _variant_public_id], responses={200: ProductVariantOutputSerializer, 403: None, 404: None})(ProductVariantDetailView.get)
ProductVariantDetailView.patch = extend_schema(tags=["Product Variants"], operation_id="product_variant_update", parameters=[_business_public_id, _product_public_id, _variant_public_id], request=ProductVariantWriteSerializer, responses={200: ProductVariantOutputSerializer, 400: None, 403: None, 404: None})(ProductVariantDetailView.patch)
_product_media_upload = inline_serializer("ProductMediaUpload", {
    "media_type": serializers.ChoiceField(choices=("IMAGE", "VIDEO")),
    "file": serializers.FileField(),
})
_product_media_update = inline_serializer("ProductMediaUpdate", {
    "is_primary": serializers.BooleanField(required=False),
    "position": serializers.IntegerField(required=False, min_value=0),
})
ProductMediaListCreateView.get = extend_schema(tags=["Products"], operation_id="product_media_list", parameters=[_business_public_id, _product_public_id], responses={200: ProductMediaSerializer(many=True), 403: None, 404: None})(ProductMediaListCreateView.get)
ProductMediaListCreateView.post = extend_schema(tags=["Products"], operation_id="product_media_create", parameters=[_business_public_id, _product_public_id], request=_product_media_upload, responses={201: ProductMediaSerializer, 400: None, 403: None, 404: None, 502: None, 503: None})(ProductMediaListCreateView.post)
ProductMediaDetailView.patch = extend_schema(tags=["Products"], operation_id="product_media_update", parameters=[_business_public_id, _product_public_id, OpenApiParameter("media_id", str, OpenApiParameter.PATH)], request=_product_media_update, responses={200: ProductMediaSerializer, 400: None, 403: None, 404: None})(ProductMediaDetailView.patch)
ProductMediaDetailView.delete = extend_schema(tags=["Products"], operation_id="product_media_delete", parameters=[_business_public_id, _product_public_id, OpenApiParameter("media_id", str, OpenApiParameter.PATH)], request=None, responses={204: None, 403: None, 404: None})(ProductMediaDetailView.delete)
ProductMediaDetailView.get = extend_schema(exclude=True)(ProductMediaDetailView.get)
ProductMediaDetailView.post = extend_schema(exclude=True)(ProductMediaDetailView.post)
UnitOfMeasureListView.get = extend_schema(tags=["Product Categories"], auth=[], responses={200: UnitOfMeasureSerializer(many=True)})(UnitOfMeasureListView.get)
