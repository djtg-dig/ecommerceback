from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.businesses.models import Business
from apps.businesses.permissions import can_manage_business, membership_for
from apps.reporting import resolve_reporting_period
from apps.sales_report_serializers import ProductReportSerializer, SalesReportSerializer
from apps.sales_reports import build_product_top, build_sales_series


class ReportBase(APIView):
    http_method_names = ["get", "head", "options"]
    def business(self, request, business_public_id):
        business = Business.objects.filter(public_id=business_public_id, members__identity=request.user, members__status="ACTIVE").first()
        if not business or not can_manage_business(membership_for(request.user, business)):
            return None
        return business


class SalesReportView(ReportBase):
    def get(self, request, business_public_id):
        business = self.business(request, business_public_id)
        if not business: return Response({"detail": "Not found."}, status=404)
        group_by = request.query_params.get("group_by", "day")
        if group_by not in {"day", "week", "month"}: raise ValidationError({"group_by": "Invalid group_by."})
        start, end = resolve_reporting_period(request.query_params)
        return Response(build_sales_series(business, start, end, group_by))


class ProductReportView(ReportBase):
    def get(self, request, business_public_id):
        business = self.business(request, business_public_id)
        if not business: return Response({"detail": "Not found."}, status=404)
        try: limit = int(request.query_params.get("limit", 10))
        except ValueError: raise ValidationError({"limit": "Invalid limit."})
        if not 1 <= limit <= 50: raise ValidationError({"limit": "Must be between 1 and 50."})
        start, end = resolve_reporting_period(request.query_params)
        return Response(build_product_top(business, start, end, limit))


period_params = [OpenApiParameter("period", str, enum=["today", "last_7_days", "last_30_days"]), OpenApiParameter("date_from", str), OpenApiParameter("date_to", str)]
SalesReportView.get = extend_schema(tags=["Reporting"], operation_id="business_sales_report", parameters=period_params + [OpenApiParameter("group_by", str, enum=["day", "week", "month"])], responses={200: SalesReportSerializer, 400: None, 404: None})(SalesReportView.get)
ProductReportView.get = extend_schema(tags=["Reporting"], operation_id="business_products_report", parameters=period_params + [OpenApiParameter("limit", int)], responses={200: ProductReportSerializer, 400: None, 404: None})(ProductReportView.get)
