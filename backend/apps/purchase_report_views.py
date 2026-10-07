from decimal import Decimal
from django.db.models import Count, DecimalField, Sum
from django.db.models.functions import Coalesce
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.businesses.models import Business
from apps.businesses.permissions import can_manage_business, membership_for
from apps.purchase_reports import build_purchases_report, debt_queryset
from apps.reporting import resolve_reporting_period

MONEY = DecimalField(max_digits=16, decimal_places=2)
class Base(APIView):
    def business(self, request, business_public_id):
        value = Business.objects.filter(public_id=business_public_id, members__identity=request.user, members__status="ACTIVE").first()
        return value if value and can_manage_business(membership_for(request.user, value)) else None
class PurchasesReportView(Base):
    def get(self, request, business_public_id):
        business = self.business(request, business_public_id)
        if not business: return Response({"detail":"Not found."}, status=404)
        group_by = request.query_params.get("group_by", "day")
        if group_by not in {"day","week","month"}: raise ValidationError({"group_by":"Invalid group_by."})
        start, end = resolve_reporting_period(request.query_params)
        return Response(build_purchases_report(business, start, end, group_by))
class Pagination(PageNumberPagination): page_size=20; page_size_query_param="page_size"; max_page_size=50
class SupplierDebtsReportView(Base):
    def get(self, request, business_public_id):
        business=self.business(request,business_public_id)
        if not business: return Response({"detail":"Not found."},status=404)
        debts=debt_queryset(business)
        summary={"total_outstanding":debts.aggregate(value=Coalesce(Sum("balance"),Decimal("0"),output_field=MONEY))["value"],"open_purchases_count":debts.count()}
        suppliers=debts.values("supplier__public_id","supplier__name").annotate(outstanding_amount=Coalesce(Sum("balance"),Decimal("0"),output_field=MONEY),open_purchases_count=Count("pk")).order_by("-outstanding_amount","supplier__name")
        pager=Pagination(); page=pager.paginate_queryset(suppliers,request)
        rows=[{"supplier_public_id":x["supplier__public_id"],"name":x["supplier__name"],"outstanding_amount":x["outstanding_amount"],"open_purchases_count":x["open_purchases_count"]} for x in page]
        response=pager.get_paginated_response(rows);response.data.update(summary);return response
period=[OpenApiParameter("period",str,enum=["today","last_7_days","last_30_days"]),OpenApiParameter("date_from",str),OpenApiParameter("date_to",str)]
PurchasesReportView.get=extend_schema(tags=["Reporting"],operation_id="business_purchases_report",parameters=period+[OpenApiParameter("group_by",str,enum=["day","week","month"])],responses={200:dict,400:None,404:None})(PurchasesReportView.get)
SupplierDebtsReportView.get=extend_schema(tags=["Reporting"],operation_id="business_supplier_debts_report",parameters=[OpenApiParameter("page",int),OpenApiParameter("page_size",int)],responses={200:dict,404:None})(SupplierDebtsReportView.get)
