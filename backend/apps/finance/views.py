from datetime import date

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.businesses.models import Business, BusinessPaymentMethod
from apps.businesses.permissions import can_manage_business, membership_for
from apps.common.choices import PaymentMethod

from .models import FinancialMovement, PaymentTransaction
from .serializers import FinancialMovementSerializer
from .services import financial_summary


FILTER_PARAMETERS = [
    OpenApiParameter("direction", str, required=False),
    OpenApiParameter("event_type", str, required=False),
    OpenApiParameter("payment_method", str, required=False),
    OpenApiParameter("date_from", str, required=False),
    OpenApiParameter("date_to", str, required=False),
    OpenApiParameter("business_payment_method", str, required=False),
    OpenApiParameter("recording_mode", str, required=False),
]


class FinanceBusinessAPIView(APIView):
    """Restrict financial reporting to active owners and managers."""

    http_method_names = ["get", "head", "options"]

    def get_business(self, request, business_public_id):
        business = Business.objects.filter(
            public_id=business_public_id,
            members__identity=request.user,
            members__status="ACTIVE",
        ).first()
        if business and can_manage_business(membership_for(request.user, business)):
            return business
        return None

    @staticmethod
    def not_found():
        return Response({"detail": "Not found."}, status=404)

    @staticmethod
    def filtered_movements(request, business):
        queryset = FinancialMovement.objects.filter(business=business)
        allowed = {
            "direction": FinancialMovement.Direction.values,
            "event_type": FinancialMovement.EventType.values,
            "payment_method": PaymentMethod.values,
        }
        for field, choices in allowed.items():
            value = request.query_params.get(field)
            if value:
                if value not in choices:
                    raise ValidationError({field: "Invalid filter value."})
                queryset = queryset.filter(**{field: value})
        method_id = request.query_params.get("business_payment_method")
        if method_id:
            if not BusinessPaymentMethod.objects.filter(business=business, public_id=method_id).exists():
                raise ValidationError({"business_payment_method": "Invalid filter value."})
            queryset = queryset.filter(payment_transaction__business_payment_method__public_id=method_id)
        mode = request.query_params.get("recording_mode")
        if mode:
            allowed_modes = set(PaymentTransaction.RecordingMode.values) | {"UNCLASSIFIED"}
            if mode not in allowed_modes:
                raise ValidationError({"recording_mode": "Invalid filter value."})
            queryset = queryset.filter(payment_transaction__isnull=mode == "UNCLASSIFIED") if mode == "UNCLASSIFIED" else queryset.filter(payment_transaction__recording_mode=mode)

        for name, lookup in (("date_from", "occurred_at__date__gte"), ("date_to", "occurred_at__date__lte")):
            value = request.query_params.get(name)
            if value:
                try:
                    date.fromisoformat(value)
                except ValueError as exc:
                    raise ValidationError({name: "Use an ISO date (YYYY-MM-DD)."}) from exc
                queryset = queryset.filter(**{lookup: value})
        return queryset


class FinancialMovementListView(FinanceBusinessAPIView):
    @extend_schema(parameters=FILTER_PARAMETERS, responses=FinancialMovementSerializer(many=True))
    def get(self, request, business_public_id):
        business = self.get_business(request, business_public_id)
        if not business:
            return self.not_found()
        return Response(
            FinancialMovementSerializer(
                self.filtered_movements(request, business), many=True
            ).data
        )


class FinancialMovementDetailView(FinanceBusinessAPIView):
    @extend_schema(responses=FinancialMovementSerializer)
    def get(self, request, business_public_id, movement_public_id):
        business = self.get_business(request, business_public_id)
        movement = (
            FinancialMovement.objects.filter(business=business, public_id=movement_public_id).first()
            if business
            else None
        )
        if not movement:
            return self.not_found()
        return Response(FinancialMovementSerializer(movement).data)


class FinancialSummaryView(FinanceBusinessAPIView):
    @extend_schema(parameters=FILTER_PARAMETERS, responses=dict)
    def get(self, request, business_public_id):
        business = self.get_business(request, business_public_id)
        if not business:
            return self.not_found()
        return Response(self.financial_response(business, request))

    def financial_response(self, business, request):
        return {
            "currency": business.primary_currency,
            **financial_summary(self.filtered_movements(request, business)),
        }
