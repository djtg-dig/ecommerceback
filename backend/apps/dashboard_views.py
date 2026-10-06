from datetime import date, timedelta
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.businesses.models import Business
from apps.businesses.permissions import can_manage_business, membership_for
from apps.dashboard import build_dashboard

class DashboardView(APIView):
    http_method_names = ['get','head','options']
    def get(self, request, business_public_id):
        business=Business.objects.filter(public_id=business_public_id,members__identity=request.user,members__status='ACTIVE').first()
        if not business or not can_manage_business(membership_for(request.user,business)):
            return Response({'detail':'Not found.'},status=404)
        today=timezone.localdate(); period=request.query_params.get('period','today'); start=end=None
        left=request.query_params.get('date_from'); right=request.query_params.get('date_to')
        if bool(left)!=bool(right) or ((left or right) and 'period' in request.query_params): raise ValidationError('Use either period or date_from/date_to.')
        if left:
            try:start=date.fromisoformat(left);end=date.fromisoformat(right)
            except ValueError:raise ValidationError('Dates must use YYYY-MM-DD.')
            if start>end:raise ValidationError('date_from must not exceed date_to.')
        elif period=='today':start=end=today
        elif period=='last_7_days':start=today-timedelta(days=6);end=today
        elif period=='last_30_days':start=today-timedelta(days=29);end=today
        else:raise ValidationError({'period':'Invalid period.'})
        return Response(build_dashboard(business,start,end))

from drf_spectacular.utils import OpenApiParameter, extend_schema

DashboardView.get = extend_schema(
    tags=["Dashboard"],
    operation_id="business_dashboard",
    parameters=[
        OpenApiParameter("period", str, required=False, enum=["today", "last_7_days", "last_30_days"]),
        OpenApiParameter("date_from", str, required=False),
        OpenApiParameter("date_to", str, required=False),
    ],
    responses={200: dict, 400: None, 404: None},
)(DashboardView.get)
