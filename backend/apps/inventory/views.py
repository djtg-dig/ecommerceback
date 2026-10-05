"""Tenant-scoped inventory reads and controlled manual stock operations."""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.businesses.models import Business
from apps.businesses.permissions import can_manage_business, membership_for
from .models import InventoryItem, StockMovement
from .serializers import InventoryItemCreateSerializer, InventoryItemSerializer, StockMovementCreateSerializer, StockMovementSerializer
from .services import apply_stock_movement, create_inventory_item


class BusinessInventoryMixin:
    """Scope every inventory access through an active business membership."""

    def get_business(self, request, business_public_id):
        return Business.objects.filter(public_id=business_public_id, members__identity=request.user, members__status="ACTIVE").distinct().first()

    def get_item(self, business, item_public_id):
        return InventoryItem.objects.filter(business=business, public_id=item_public_id).select_related("product", "variant__product").first()

    @staticmethod
    def not_found():
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

    @staticmethod
    def forbidden():
        return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)


class InventoryListCreateView(BusinessInventoryMixin, APIView):
    """List active-member inventory or create a zero-balance item."""

    def get(self, request, business_public_id):
        business = self.get_business(request, business_public_id)
        if not business:
            return self.not_found()
        items = InventoryItem.objects.filter(business=business).select_related("product", "variant__product")
        if product := request.query_params.get("product"):
            items = items.filter(product__public_id=product)
        if variant := request.query_params.get("variant"):
            items = items.filter(variant__public_id=variant)
        if request.query_params.get("low_stock", "").lower() == "true":
            items = [item for item in items if item.is_low_stock]
        return Response(InventoryItemSerializer(items, many=True).data)

    def post(self, request, business_public_id):
        business = self.get_business(request, business_public_id)
        if not business:
            return self.not_found()
        if not can_manage_business(membership_for(request.user, business)):
            return self.forbidden()
        serializer = InventoryItemCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            item = create_inventory_item(business=business, **serializer.validated_data)
        except DjangoValidationError as exc:
            return Response(exc.message_dict if hasattr(exc, "message_dict") else {"detail": exc.messages}, status=400)
        except IntegrityError:
            return Response({"detail": "Un inventaire existe déjà pour cet article."}, status=400)
        return Response(InventoryItemSerializer(item).data, status=status.HTTP_201_CREATED)


class InventoryDetailView(BusinessInventoryMixin, APIView):
    """Return one balance without exposing internal UUIDs."""

    def get(self, request, business_public_id, inventory_public_id):
        business = self.get_business(request, business_public_id)
        item = self.get_item(business, inventory_public_id) if business else None
        return Response(InventoryItemSerializer(item).data) if item else self.not_found()


class StockMovementListCreateView(BusinessInventoryMixin, APIView):
    """Read immutable history or create a permitted manual movement."""

    def get(self, request, business_public_id, inventory_public_id):
        business = self.get_business(request, business_public_id)
        item = self.get_item(business, inventory_public_id) if business else None
        if not item:
            return self.not_found()
        return Response(StockMovementSerializer(item.movements.all(), many=True).data)

    def post(self, request, business_public_id, inventory_public_id):
        business = self.get_business(request, business_public_id)
        item = self.get_item(business, inventory_public_id) if business else None
        if not item:
            return self.not_found()
        if not can_manage_business(membership_for(request.user, business)):
            return self.forbidden()
        serializer = StockMovementCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            movement = apply_stock_movement(
                inventory_item=item, movement_type=serializer.validated_data["type"], performed_by=request.user,
                quantity=serializer.validated_data.get("quantity"), target_quantity=serializer.validated_data.get("target_quantity"),
                reason=serializer.validated_data.get("reason", ""),
            )
        except DjangoValidationError as exc:
            return Response(exc.message_dict if hasattr(exc, "message_dict") else {"detail": exc.messages}, status=400)
        return Response(StockMovementSerializer(movement).data, status=status.HTTP_201_CREATED)

from drf_spectacular.utils import OpenApiParameter, extend_schema

_inventory_business_id = OpenApiParameter("business_public_id", str, OpenApiParameter.PATH, description="Identifiant Business, format SH + 10 caractères.")
_inventory_item_id = OpenApiParameter("inventory_public_id", str, OpenApiParameter.PATH, description="Identifiant InventoryItem, format IV + 10 caractères.")
InventoryListCreateView.get = extend_schema(
    tags=["Inventory"], operation_id="inventory_list", parameters=[_inventory_business_id, OpenApiParameter("product", str, OpenApiParameter.QUERY), OpenApiParameter("variant", str, OpenApiParameter.QUERY), OpenApiParameter("low_stock", bool, OpenApiParameter.QUERY)],
    responses={200: InventoryItemSerializer(many=True), 404: None},
)(InventoryListCreateView.get)
InventoryListCreateView.post = extend_schema(
    tags=["Inventory"], operation_id="inventory_item_create", parameters=[_inventory_business_id], request=InventoryItemCreateSerializer,
    responses={201: InventoryItemSerializer, 400: None, 403: None, 404: None},
)(InventoryListCreateView.post)
InventoryDetailView.get = extend_schema(
    tags=["Inventory"], operation_id="inventory_item_retrieve", parameters=[_inventory_business_id, _inventory_item_id], responses={200: InventoryItemSerializer, 404: None},
)(InventoryDetailView.get)
StockMovementListCreateView.get = extend_schema(
    tags=["Stock Movements"], operation_id="stock_movement_list", parameters=[_inventory_business_id, _inventory_item_id], responses={200: StockMovementSerializer(many=True), 404: None},
)(StockMovementListCreateView.get)
StockMovementListCreateView.post = extend_schema(
    tags=["Stock Movements"], operation_id="stock_movement_create", parameters=[_inventory_business_id, _inventory_item_id], request=StockMovementCreateSerializer,
    responses={201: StockMovementSerializer, 400: None, 403: None, 404: None},
    description="IN et OUT utilisent quantity positive. ADJUSTMENT utilise target_quantity absolue.",
)(StockMovementListCreateView.post)
