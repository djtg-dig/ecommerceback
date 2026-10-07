from drf_spectacular.utils import OpenApiParameter, extend_schema
from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.businesses.models import Business
from apps.businesses.permissions import can_manage_business, membership_for
from apps.expense_receivable_reports import build_expenses_report, receivable_queryset, receivables_summary
from apps.reporting import resolve_reporting_period


class ReportBase(APIView):
    def business(self, request, business_public_id):
        business = Business.objects.filter(public_id=business_public_id, members__identity=request.user, members__status="ACTIVE").first()
        return business if business and can_manage_business(membership_for(request.user, business)) else None


class ExpensesReportView(ReportBase):
    def get(self, request, business_public_id):
        business = self.business(request, business_public_id)
        if not business: return Response({"detail": "Not found."}, status=404)
        group_by = request.query_params.get("group_by", "day")
        if group_by not in {"day", "week", "month"}: raise ValidationError({"group_by": "Invalid group_by."})
        start, end = resolve_reporting_period(request.query_params)
        return Response(build_expenses_report(business, start, end, group_by))


class ReceivablesPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 50


class ReceivablesReportView(ReportBase):
    def get(self, request, business_public_id):
        business = self.business(request, business_public_id)
        if not business: return Response({"detail": "Not found."}, status=404)
        queryset = receivable_queryset(business)
        summary = receivables_summary(queryset)
        customers = queryset.values("customer__public_id", "customer__name").annotate(
            outstanding_amount=Coalesce(Sum("balance"), __import__("decimal").Decimal("0"), output_field=__import__("django.db.models", fromlist=["DecimalField"]).DecimalField(max_digits=16, decimal_places=2)),
            open_receivables_count=Count("pk"),
            overdue_receivables_count=Count("pk", filter=Q(due_date__lt=timezone.localdate())),
        ).order_by("-outstanding_amount", "customer__name")
        paginator = ReceivablesPagination()
        page = paginator.paginate_queryset(customers, request)
        data = [{"customer_public_id": row["customer__public_id"], "name": row["customer__name"], **{key: row[key] for key in ("outstanding_amount", "open_receivables_count", "overdue_receivables_count")}} for row in page]
        response = paginator.get_paginated_response(data)
        response.data.update(summary)
        return response


period_params = [OpenApiParameter("period", str, enum=["today", "last_7_days", "last_30_days"]), OpenApiParameter("date_from", str), OpenApiParameter("date_to", str)]
ExpensesReportView.get = extend_schema(tags=["Reporting"], operation_id="business_expenses_report", parameters=period_params + [OpenApiParameter("group_by", str, enum=["day", "week", "month"])], responses={200: dict, 400: None, 404: None})(ExpensesReportView.get)
ReceivablesReportView.get = extend_schema(tags=["Reporting"], operation_id="business_receivables_report", parameters=[OpenApiParameter("page", int), OpenApiParameter("page_size", int)], responses={200: dict, 404: None})(ReceivablesReportView.get)
