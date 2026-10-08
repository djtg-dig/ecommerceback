from decimal import Decimal
from django.core.exceptions import ValidationError
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.views import APIView
from rest_framework.response import Response
from apps.businesses.models import Business, BusinessMemberPermission
from apps.businesses.permissions import require_permission
from .models import Customer, Sale, SaleLine, SaleReturn
from .serializers import *
from .services import SaleReturnIdempotencyConflict, cancel, complete, create_sale_return


class M:
    def b(self, r, x):
        return Business.objects.filter(
            public_id=x, members__identity=r.user, members__status="ACTIVE"
        ).first()

    def nf(self):
        return Response({"detail": "Not found."}, 404)

    def authorized_business(self, request, public_id, permission, *, write=True):
        """Resolve a tenant and enforce one server-defined Business permission."""
        business = Business.objects.filter(public_id=public_id).first()
        if business is None:
            return None

        require_permission(
            request.user,
            business,
            permission,
            write=write,
        )
        return business


class Customers(M, APIView):
    def get(self, r, business_public_id):
        b = self.b(r, business_public_id)
        return (
            Response(
                CustomerSerializer(Customer.objects.filter(business=b), many=True).data
            )
            if b
            else self.nf()
        )

    def post(self, r, business_public_id):
        b = self.b(r, business_public_id)
        if not b:
            return self.nf()
        s = CustomerSerializer(data=r.data)
        s.is_valid(raise_exception=True)
        return Response(CustomerSerializer(s.save(business=b)).data, 201)


class Sales(M, APIView):
    def get(self, r, business_public_id):
        b = self.b(r, business_public_id)
        return (
            Response(SaleSerializer(Sale.objects.filter(business=b), many=True).data)
            if b
            else self.nf()
        )

    def post(self, r, business_public_id):
        b = self.authorized_business(
            r,
            business_public_id,
            BusinessMemberPermission.Permission.USE_POS,
        )
        if not b:
            return self.nf()
        s = SaleWrite(data=r.data, context={"business": b})
        s.is_valid(raise_exception=True)
        o = s.save(business=b, created_by=r.user, currency=b.primary_currency)
        return Response(SaleSerializer(o).data, 201)


class SD(Sales):
    def o(self, b, x):
        return Sale.objects.filter(business=b, public_id=x).first()

    def get(self, r, business_public_id, sale_public_id):
        b = self.b(r, business_public_id)
        o = self.o(b, sale_public_id) if b else None
        return Response(SaleSerializer(o).data) if o else self.nf()

    def patch(self, r, business_public_id, sale_public_id):
        b = self.authorized_business(
            r,
            business_public_id,
            BusinessMemberPermission.Permission.USE_POS,
        )
        o = self.o(b, sale_public_id) if b else None
        if not o:
            return self.nf()
        if o.status != "DRAFT":
            return Response({"detail": "immutable"}, 400)
        s = SaleWrite(o, data=r.data, partial=True, context={"business": b})
        s.is_valid(raise_exception=True)
        s.save()
        return Response(SaleSerializer(o).data)


class Lines(SD):
    def get(self, r, business_public_id, sale_public_id):
        b = self.b(r, business_public_id)
        s = self.o(b, sale_public_id) if b else None
        return (
            Response(LineSerializer(s.lines.all(), many=True).data) if s else self.nf()
        )

    def post(self, r, business_public_id, sale_public_id):
        b = self.authorized_business(
            r,
            business_public_id,
            BusinessMemberPermission.Permission.USE_POS,
        )
        s = self.o(b, sale_public_id) if b else None
        if not s:
            return self.nf()
        if s.status != "DRAFT":
            return Response({"detail": "immutable"}, 400)
        x = LineWrite(data=r.data, context={"sale": s})
        x.is_valid(raise_exception=True)
        o = SaleLine.objects.create(sale=s, **x.validated_data)
        return Response(LineSerializer(o).data, 201)


class Action(SD):
    fn = None

    def post(self, r, business_public_id, sale_public_id):
        permission = (
            BusinessMemberPermission.Permission.USE_POS
            if self.fn == "complete"
            else BusinessMemberPermission.Permission.MANAGE_SALES
        )
        b = self.authorized_business(
            r,
            business_public_id,
            permission,
        )
        s = self.o(b, sale_public_id) if b else None
        if not s:
            return self.nf()
        try:
            if self.fn == "complete":
                serializer = SaleCompleteSerializer(data=r.data)
                serializer.is_valid(raise_exception=True)
                o = complete(s, r.user, **serializer.validated_data)
            else:
                o = cancel(s, r.user)
        except ValidationError as e:
            return Response({"detail": str(e)}, 400)
        return Response(SaleSerializer(o).data)


class Complete(Action):
    fn = "complete"

    def post(self, request, business_public_id, sale_public_id):
        return super().post(request, business_public_id, sale_public_id)


class Cancel(Action):
    fn = "cancel"

    def post(self, request, business_public_id, sale_public_id):
        return super().post(request, business_public_id, sale_public_id)


class SaleReturnPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 50


class SaleReturns(M, APIView):
    """Create an atomic sale return or list compact returns for one sale."""

    serializer_class = SaleReturnSerializer

    def _scope(self, request, business_public_id, sale_public_id):
        business = self.authorized_business(
            request,
            business_public_id,
            BusinessMemberPermission.Permission.MANAGE_SALE_RETURNS,
            write=request.method != "GET",
        )
        if not business:
            return None, None
        sale = Sale.objects.filter(
            business=business,
            public_id=sale_public_id,
        ).first()
        return business, sale

    def get(self, request, business_public_id, sale_public_id):
        business, sale = self._scope(
            request,
            business_public_id,
            sale_public_id,
        )
        if not business or not sale:
            return self.nf()
        queryset = (
            SaleReturn.objects.filter(business=business, sale=sale)
            .select_related("refund_payment_method")
            .prefetch_related("lines__sale_line")
        )
        paginator = SaleReturnPagination()
        page = paginator.paginate_queryset(queryset, request)
        return paginator.get_paginated_response(
            SaleReturnSerializer(page, many=True).data
        )

    def post(self, request, business_public_id, sale_public_id):
        business, sale = self._scope(
            request,
            business_public_id,
            sale_public_id,
        )
        if not business or not sale:
            return self.nf()
        idempotency_key = request.headers.get("Idempotency-Key", "").strip()
        if not idempotency_key:
            return Response(
                {"idempotency_key": ["This header is required."]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = SaleReturnRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        try:
            sale_return = create_sale_return(
                sale=sale,
                actor=request.user,
                reason=values.get("reason", ""),
                returned_at=values["returned_at"],
                refund_payment_method=values.get("refund_payment_method"),
                lines=[
                    {
                        "sale_line_public_id": line["sale_line"],
                        "quantity": line["quantity"],
                    }
                    for line in values["lines"]
                ],
                idempotency_key=idempotency_key,
            )
        except SaleReturnIdempotencyConflict as exc:
            return Response(
                {"detail": exc.messages[0]},
                status=status.HTTP_409_CONFLICT,
            )
        except ValidationError as exc:
            detail = (
                exc.message_dict
                if hasattr(exc, "message_dict")
                else {"detail": exc.messages}
            )
            return Response(detail, status=status.HTTP_400_BAD_REQUEST)
        sale_return = (
            SaleReturn.objects.select_related("refund_payment_method")
            .prefetch_related("lines__sale_line")
            .get(pk=sale_return.pk)
        )
        return Response(
            SaleReturnSerializer(sale_return).data,
            status=status.HTTP_201_CREATED,
        )


# Schema introspection metadata for the real APIView operations.
Customers.serializer_class = CustomerSerializer
Sales.serializer_class = SaleSerializer
SD.serializer_class = SaleSerializer
Lines.serializer_class = LineSerializer
Complete.serializer_class = SaleCompleteSerializer
Cancel.serializer_class = SaleSerializer
SaleReturns.serializer_class = SaleReturnSerializer
SD.http_method_names = ["get", "patch", "head", "options"]
Lines.http_method_names = ["get", "post", "head", "options"]
Complete.http_method_names = ["post", "options"]
Cancel.http_method_names = ["post", "options"]

Sales.get = extend_schema(
    tags=["Sales"], operation_id="sale_list", responses={200: SaleSerializer(many=True)}
)(Sales.get)
Sales.post = extend_schema(
    tags=["Sales"],
    operation_id="sale_create",
    request=SaleWrite,
    responses={201: SaleSerializer, 403: None, 404: None},
)(Sales.post)
SD.get = extend_schema(
    tags=["Sales"], operation_id="sale_retrieve", responses={200: SaleSerializer}
)(SD.get)
SD.patch = extend_schema(
    tags=["Sales"],
    operation_id="sale_update",
    request=SaleWrite,
    responses={200: SaleSerializer, 400: None, 403: None, 404: None},
)(SD.patch)
Lines.get = extend_schema(
    tags=["Sales"],
    operation_id="sale_line_list",
    responses={200: LineSerializer(many=True)},
)(Lines.get)
Lines.post = extend_schema(
    tags=["Sales"],
    operation_id="sale_line_create",
    request=LineWrite,
    responses={201: LineSerializer, 400: None, 403: None, 404: None},
)(Lines.post)
Customers.get = extend_schema(
    tags=["Customers"],
    operation_id="customer_list",
    responses={200: CustomerSerializer(many=True)},
)(Customers.get)
Customers.post = extend_schema(
    tags=["Customers"],
    operation_id="customer_create",
    request=CustomerSerializer,
    responses={201: CustomerSerializer},
)(Customers.post)

Complete.post = extend_schema(
    tags=["Sales"],
    operation_id="sale_complete",
    request=SaleCompleteSerializer,
    responses={200: SaleSerializer, 400: None, 403: None, 404: None},
)(Complete.post)
Cancel.post = extend_schema(
    tags=["Sales"],
    operation_id="sale_cancel",
    request=None,
    responses={200: SaleSerializer, 400: None, 403: None, 404: None},
)(Cancel.post)

_idempotency_key = OpenApiParameter(
    name="Idempotency-Key",
    type=str,
    location=OpenApiParameter.HEADER,
    required=True,
    description="Required retry key. Reuse is safe only with the identical payload.",
)
_page = OpenApiParameter("page", int, OpenApiParameter.QUERY)
_page_size = OpenApiParameter(
    "page_size",
    int,
    OpenApiParameter.QUERY,
    description="Page size, from 1 to 50 (default 20).",
)
_error_response = inline_serializer(
    name="SaleReturnError",
    fields={"detail": serializers.JSONField()},
)
_paginated_sale_returns = inline_serializer(
    name="PaginatedSaleReturnList",
    fields={
        "count": serializers.IntegerField(),
        "next": serializers.URLField(allow_null=True),
        "previous": serializers.URLField(allow_null=True),
        "results": SaleReturnSerializer(many=True),
    },
)

SaleReturns.get = extend_schema(
    tags=["Sales"],
    operation_id="sale_return_list",
    parameters=[_page, _page_size],
    responses={
        200: _paginated_sale_returns,
        403: _error_response,
        404: _error_response,
    },
)(SaleReturns.get)
SaleReturns.post = extend_schema(
    tags=["Sales"],
    operation_id="sale_return_create",
    parameters=[_idempotency_key],
    request=SaleReturnRequestSerializer,
    responses={
        201: SaleReturnSerializer,
        400: _error_response,
        403: _error_response,
        404: _error_response,
        409: _error_response,
    },
)(SaleReturns.post)
