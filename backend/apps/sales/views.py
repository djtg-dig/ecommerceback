from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db.models import Q, Sum
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.views import APIView
from rest_framework.response import Response
from apps.businesses.models import Business, BusinessMemberPermission
from apps.businesses.permissions import has_permission, membership_for, require_permission
from apps.finance.models import FinancialMovement
from apps.receivables.models import Receivable, ReceivableAdjustment, ReceivablePayment
from .models import Customer, Sale, SaleLine, SaleReturn
from .serializers import *
from .services import SaleReturnIdempotencyConflict, cancel, complete, create_sale_return


class M:
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
        b = self.authorized_business(
            r,
            business_public_id,
            BusinessMemberPermission.Permission.VIEW_CUSTOMERS,
            write=False,
        )
        if not b:
            return self.nf()
        customers = Customer.objects.filter(business=b)
        paginated = any(
            parameter in r.query_params
            for parameter in ("q", "ordering", "page", "page_size")
        )
        query = r.query_params.get("q", "").strip()
        if query:
            customers = customers.filter(
                Q(name__icontains=query)
                | Q(phone__icontains=query)
                | Q(email__icontains=query)
                | Q(public_id__iexact=query)
            )
        ordering = r.query_params.get("ordering", "name")
        if ordering not in {"name", "-name", "created_at", "-created_at"}:
            return Response({"ordering": ["Tri de clients invalide."]}, status=400)
        customers = customers.order_by(ordering, "public_id")
        if not paginated:
            return Response(CustomerSerializer(customers, many=True).data)
        paginator = CommercialPartnerPagination()
        page = paginator.paginate_queryset(customers, r)
        return paginator.get_paginated_response(CustomerSerializer(page, many=True).data)

    def post(self, r, business_public_id):
        b = self.authorized_business(
            r,
            business_public_id,
            BusinessMemberPermission.Permission.MANAGE_CUSTOMERS,
        )
        if not b:
            return self.nf()
        s = CustomerSerializer(data=r.data)
        s.is_valid(raise_exception=True)
        return Response(CustomerSerializer(s.save(business=b)).data, 201)


class CommercialPartnerPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class CustomerDetail(M, APIView):
    """Read or update one customer without touching historical sales."""

    @staticmethod
    def customer(business, public_id):
        return Customer.objects.filter(business=business, public_id=public_id).first()

    def get(self, request, business_public_id, customer_public_id):
        business = self.authorized_business(
            request,
            business_public_id,
            BusinessMemberPermission.Permission.VIEW_CUSTOMERS,
            write=False,
        )
        customer = self.customer(business, customer_public_id) if business else None
        return Response(CustomerSerializer(customer).data) if customer else self.nf()

    def patch(self, request, business_public_id, customer_public_id):
        business = self.authorized_business(
            request,
            business_public_id,
            BusinessMemberPermission.Permission.MANAGE_CUSTOMERS,
        )
        customer = self.customer(business, customer_public_id) if business else None
        if not customer:
            return self.nf()
        serializer = CustomerSerializer(customer, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class CustomerCommercialProfile(CustomerDetail):
    """Expose permission-filtered sales and reliable ledger-backed totals."""

    def get(self, request, business_public_id, customer_public_id):
        business = self.authorized_business(
            request,
            business_public_id,
            BusinessMemberPermission.Permission.VIEW_CUSTOMERS,
            write=False,
        )
        customer = self.customer(business, customer_public_id) if business else None
        if not customer:
            return self.nf()

        member = membership_for(request.user, business)
        can_view_sales = has_permission(member, BusinessMemberPermission.Permission.VIEW_SALES)
        can_view_financials = has_permission(
            member, BusinessMemberPermission.Permission.VIEW_FINANCIAL_SUMMARY
        )
        can_view_receivables = has_permission(
            member, BusinessMemberPermission.Permission.VIEW_RECEIVABLES
        )
        sales_data = None
        if can_view_sales:
            sales = (
                Sale.objects.filter(business=business, customer=customer)
                .select_related("receivable")
                .prefetch_related("lines")
                .order_by("-created_at", "-public_id")
            )
            paginator = CommercialPartnerPagination()
            page = paginator.paginate_queryset(sales, request)
            sales_data = paginator.get_paginated_response(
                CustomerSaleHistorySerializer(page, many=True).data
            ).data

        financial_summary = None
        if can_view_financials:
            completed_sales = Sale.objects.filter(
                business=business,
                customer=customer,
                status=Sale.Status.COMPLETED,
            ).prefetch_related("lines")
            total_sales = sum((sale.total for sale in completed_sales), Decimal("0.00"))
            movements = FinancialMovement.objects.filter(business=business).filter(
                Q(sale__customer=customer)
                | Q(receivable_payment__receivable__customer=customer)
                | Q(sale_return__customer=customer)
            )
            inflow = movements.filter(
                direction=FinancialMovement.Direction.INFLOW
            ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
            outflow = movements.filter(
                direction=FinancialMovement.Direction.OUTFLOW
            ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
            receivables = Receivable.objects.filter(business=business, customer=customer)
            original = receivables.aggregate(total=Sum("original_amount"))["total"] or Decimal("0.00")
            paid = ReceivablePayment.objects.filter(
                business=business,
                receivable__customer=customer,
            ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
            adjusted = ReceivableAdjustment.objects.filter(
                business=business,
                receivable__customer=customer,
            ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
            financial_summary = {
                "currency": business.primary_currency,
                "total_completed_sales": total_sales,
                "net_collected": inflow - outflow,
                "outstanding_receivables": original - paid - adjusted,
                "open_receivables": receivables.exclude(status=Receivable.Status.PAID).count(),
            }

        return Response({
            "customer": CustomerSerializer(customer).data,
            "sales": sales_data,
            "financial_summary": financial_summary,
            "capabilities": {
                "view_sales": can_view_sales,
                "view_financials": can_view_financials,
                "view_receivables": can_view_receivables,
            },
        })


class PosCustomerPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 50


class PosCustomerSearch(M, APIView):
    """Return a compact active-customer projection for customer selection."""

    serializer_class = PosCustomerSerializer

    def get(self, request, business_public_id):
        business = self.authorized_business(
            request,
            business_public_id,
            BusinessMemberPermission.Permission.USE_POS,
            write=False,
        )
        if not business:
            return self.nf()

        customers = Customer.objects.filter(
            business=business,
            is_active=True,
        ).order_by("name", "public_id")
        query = request.query_params.get("q", "").strip()
        if query:
            customers = customers.filter(
                Q(public_id__iexact=query)
                | Q(name__icontains=query)
                | Q(phone__icontains=query)
            )

        paginator = PosCustomerPagination()
        page = paginator.paginate_queryset(customers, request)
        return paginator.get_paginated_response(
            PosCustomerSerializer(page, many=True).data
        )


class Sales(M, APIView):
    def get(self, r, business_public_id):
        b = self.authorized_business(
            r,
            business_public_id,
            BusinessMemberPermission.Permission.VIEW_SALES,
            write=False,
        )
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
        b = self.authorized_business(
            r,
            business_public_id,
            BusinessMemberPermission.Permission.VIEW_SALES,
            write=False,
        )
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
        b = self.authorized_business(
            r,
            business_public_id,
            BusinessMemberPermission.Permission.VIEW_SALES,
            write=False,
        )
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
PosCustomerSearch.serializer_class = PosCustomerSerializer
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
    tags=["Sales"],
    operation_id="sale_list",
    responses={200: SaleSerializer(many=True), 403: None, 404: None},
)(Sales.get)
Sales.post = extend_schema(
    tags=["Sales"],
    operation_id="sale_create",
    request=SaleWrite,
    responses={201: SaleSerializer, 403: None, 404: None},
)(Sales.post)
SD.get = extend_schema(
    tags=["Sales"],
    operation_id="sale_retrieve",
    responses={200: SaleSerializer, 403: None, 404: None},
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
    responses={200: LineSerializer(many=True), 403: None, 404: None},
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
    responses={200: CustomerSerializer(many=True), 403: None, 404: None},
)(Customers.get)
Customers.post = extend_schema(
    tags=["Customers"],
    operation_id="customer_create",
    request=CustomerSerializer,
    responses={201: CustomerSerializer, 400: None, 403: None, 404: None},
)(Customers.post)
_paginated_pos_customers = inline_serializer(
    name="PaginatedPosCustomerList",
    fields={
        "count": serializers.IntegerField(),
        "next": serializers.URLField(allow_null=True),
        "previous": serializers.URLField(allow_null=True),
        "results": PosCustomerSerializer(many=True),
    },
)
PosCustomerSearch.get = extend_schema(
    tags=["Customers"],
    operation_id="pos_customer_search",
    parameters=[
        OpenApiParameter(
            "q",
            str,
            OpenApiParameter.QUERY,
            description="Optional public ID, name or phone search.",
        ),
        OpenApiParameter("page", int, OpenApiParameter.QUERY),
        OpenApiParameter(
            "page_size",
            int,
            OpenApiParameter.QUERY,
            description="Page size, from 1 to 50 (default 20).",
        ),
    ],
    responses={200: _paginated_pos_customers, 403: None, 404: None},
)(PosCustomerSearch.get)

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
