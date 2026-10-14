"""Tenant-scoped inventory reads and controlled manual stock operations."""

from django.core.exceptions import ValidationError as DjangoValidationError
from datetime import datetime, time
from decimal import Decimal

from django.db import IntegrityError
from django.db.models import Max, Q
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.businesses.models import Business, BusinessMemberPermission
from apps.businesses.permissions import require_permission
from .models import InventoryItem, StockMovement
from .serializers import InventoryItemCreateSerializer, InventoryItemSerializer, StockMovementCreateSerializer, StockMovementSerializer
from .services import StockMovementIdempotencyConflict, apply_stock_movement, create_inventory_item


class BusinessInventoryMixin:
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
        business = self.get_business(
            request,
            business_public_id,
            BusinessMemberPermission.Permission.INVENTORY_VIEW,
        )
        if not business:
            return self.not_found()
        items = InventoryItem.objects.filter(business=business).select_related("product", "variant__product").annotate(last_movement_at=Max("movements__created_at"))
        if product := request.query_params.get("product"):
            items = items.filter(product__public_id=product)
        if variant := request.query_params.get("variant"):
            items = items.filter(variant__public_id=variant)
        if query := request.query_params.get("q", "").strip():
            items = items.filter(
                Q(product__name__icontains=query)
                | Q(product__internal_reference__icontains=query)
                | Q(variant__product__name__icontains=query)
                | Q(variant__internal_reference__icontains=query)
            )
        values = list(items)
        if request.query_params.get("low_stock", "").lower() == "true":
            values = [item for item in values if item.is_low_stock]
        stock_status = request.query_params.get("status")
        if stock_status:
            valid_statuses = {"AVAILABLE", "LOW_STOCK", "OUT_OF_STOCK"}
            if stock_status not in valid_statuses:
                return Response({"status": ["État de stock invalide."]}, status=400)
            values = [
                item for item in values
                if InventoryItemSerializer().get_stock_status(item) == stock_status
            ]
        ordering = request.query_params.get("ordering", "")
        if ordering:
            if ordering not in {"quantity", "-quantity"}:
                return Response({"ordering": ["Tri d’inventaire invalide."]}, status=400)
            values.sort(key=lambda item: item.available_quantity, reverse=ordering.startswith("-"))
        return Response(InventoryItemSerializer(values, many=True).data)

    def post(self, request, business_public_id):
        business = self.get_business(
            request,
            business_public_id,
            BusinessMemberPermission.Permission.INVENTORY_INITIALIZE,
            write=True,
        )
        if not business:
            return self.not_found()
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
        business = self.get_business(
            request,
            business_public_id,
            BusinessMemberPermission.Permission.INVENTORY_VIEW,
        )
        item = self.get_item(business, inventory_public_id) if business else None
        return Response(InventoryItemSerializer(item).data) if item else self.not_found()


class StockMovementListCreateView(BusinessInventoryMixin, APIView):
    """Read immutable history or create a permitted manual movement."""

    def get(self, request, business_public_id, inventory_public_id):
        business = self.get_business(
            request,
            business_public_id,
            BusinessMemberPermission.Permission.INVENTORY_MOVEMENT_VIEW,
        )
        item = self.get_item(business, inventory_public_id) if business else None
        if not item:
            return self.not_found()
        return Response(StockMovementSerializer(item.movements.all(), many=True).data)

    def post(self, request, business_public_id, inventory_public_id):
        serializer = StockMovementCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        movement_permission = {
            StockMovement.Type.IN: BusinessMemberPermission.Permission.INVENTORY_IN,
            StockMovement.Type.OUT: BusinessMemberPermission.Permission.INVENTORY_OUT,
            StockMovement.Type.ADJUSTMENT: BusinessMemberPermission.Permission.INVENTORY_ADJUST,
        }[serializer.validated_data["type"]]
        business = self.get_business(
            request,
            business_public_id,
            movement_permission,
            write=True,
        )
        item = self.get_item(business, inventory_public_id) if business else None
        if not item:
            return self.not_found()
        idempotency_key = request.headers.get("Idempotency-Key", "").strip()
        if not idempotency_key:
            return Response(
                {"idempotency_key": ["Cet en-tête est obligatoire."]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            movement = apply_stock_movement(
                inventory_item=item, movement_type=serializer.validated_data["type"], performed_by=request.user,
                quantity=serializer.validated_data.get("quantity"), target_quantity=serializer.validated_data.get("target_quantity"),
                reason=serializer.validated_data.get("reason", ""),
                idempotency_key=idempotency_key,
            )
        except StockMovementIdempotencyConflict as exc:
            return Response({"detail": exc.messages[0]}, status=status.HTTP_409_CONFLICT)
        except DjangoValidationError as exc:
            return Response(exc.message_dict if hasattr(exc, "message_dict") else {"detail": exc.messages}, status=400)
        response_status = status.HTTP_200_OK if getattr(movement, "_idempotent_replay", False) else status.HTTP_201_CREATED
        return Response(StockMovementSerializer(movement).data, status=response_status)


class InventorySummaryView(BusinessInventoryMixin, APIView):
    """Return tenant-scoped stock indicators and recent immutable events."""

    def get(self, request, business_public_id):
        business = self.get_business(
            request,
            business_public_id,
            BusinessMemberPermission.Permission.INVENTORY_VIEW,
        )
        if not business:
            return self.not_found()
        items = list(
            InventoryItem.objects.filter(business=business)
            .select_related("product", "variant__product")
        )
        recent = (
            StockMovement.objects.filter(business=business)
            .select_related("inventory_item__product", "inventory_item__variant__product")[:10]
        )
        return Response({
            "tracked_products": len(items),
            "in_stock": sum(item.available_quantity > 0 for item in items),
            "out_of_stock": sum(item.available_quantity == 0 for item in items),
            "low_stock": sum(item.available_quantity > 0 and item.is_low_stock for item in items),
            "total_available_quantity": str(sum((item.available_quantity for item in items), Decimal("0.000"))),
            "recent_movements": StockMovementSerializer(recent, many=True).data,
        })


class MovementPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class BusinessStockMovementHistoryView(BusinessInventoryMixin, APIView):
    """Return paginated movement history across one Business inventory."""

    def get(self, request, business_public_id):
        business = self.get_business(
            request,
            business_public_id,
            BusinessMemberPermission.Permission.INVENTORY_MOVEMENT_VIEW,
        )
        if not business:
            return self.not_found()
        movements = StockMovement.objects.filter(business=business).select_related(
            "inventory_item__product",
            "inventory_item__variant__product",
        )
        if product := request.query_params.get("product"):
            movements = movements.filter(
                Q(inventory_item__product__public_id=product)
                | Q(inventory_item__variant__product__public_id=product)
            )
        if movement_type := request.query_params.get("type"):
            if movement_type not in StockMovement.Type.values:
                return Response({"type": ["Type de mouvement invalide."]}, status=400)
            movements = movements.filter(movement_type=movement_type)
        if origin := request.query_params.get("origin"):
            movements = movements.filter(reference_type=origin)
        for parameter, lookup, boundary in (
            ("date_from", "created_at__gte", time.min),
            ("date_to", "created_at__lte", time.max),
        ):
            raw = request.query_params.get(parameter)
            if raw:
                value = parse_date(raw)
                if value is None:
                    return Response({parameter: ["Date invalide."]}, status=400)
                moment = timezone.make_aware(datetime.combine(value, boundary))
                movements = movements.filter(**{lookup: moment})
        paginator = MovementPagination()
        page = paginator.paginate_queryset(movements, request)
        return paginator.get_paginated_response(
            StockMovementSerializer(page, many=True).data
        )

from drf_spectacular.utils import OpenApiParameter, extend_schema

_inventory_business_id = OpenApiParameter("business_public_id", str, OpenApiParameter.PATH, description="Identifiant Business, format SH + 10 caractères.")
_inventory_item_id = OpenApiParameter("inventory_public_id", str, OpenApiParameter.PATH, description="Identifiant InventoryItem, format IV + 10 caractères.")
InventoryListCreateView.get = extend_schema(
    tags=["Inventory"], operation_id="inventory_list", parameters=[_inventory_business_id, OpenApiParameter("product", str, OpenApiParameter.QUERY), OpenApiParameter("variant", str, OpenApiParameter.QUERY), OpenApiParameter("low_stock", bool, OpenApiParameter.QUERY)],
    responses={200: InventoryItemSerializer(many=True), 403: None, 404: None},
)(InventoryListCreateView.get)
InventoryListCreateView.post = extend_schema(
    tags=["Inventory"], operation_id="inventory_item_create", parameters=[_inventory_business_id], request=InventoryItemCreateSerializer,
    responses={201: InventoryItemSerializer, 400: None, 403: None, 404: None},
)(InventoryListCreateView.post)
InventoryDetailView.get = extend_schema(
    tags=["Inventory"], operation_id="inventory_item_retrieve", parameters=[_inventory_business_id, _inventory_item_id], responses={200: InventoryItemSerializer, 403: None, 404: None},
)(InventoryDetailView.get)
StockMovementListCreateView.get = extend_schema(
    tags=["Stock Movements"], operation_id="stock_movement_list", parameters=[_inventory_business_id, _inventory_item_id], responses={200: StockMovementSerializer(many=True), 403: None, 404: None},
)(StockMovementListCreateView.get)
StockMovementListCreateView.post = extend_schema(
    tags=["Stock Movements"], operation_id="stock_movement_create", parameters=[_inventory_business_id, _inventory_item_id], request=StockMovementCreateSerializer,
    responses={201: StockMovementSerializer, 400: None, 403: None, 404: None},
    description="IN et OUT utilisent quantity positive. ADJUSTMENT utilise target_quantity absolue.",
)(StockMovementListCreateView.post)
