from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.businesses.models import Business, BusinessMemberPermission
from apps.businesses.permissions import require_permission

from .models import Receivable
from .serializers import P, R
from .services import IdempotencyConflict, add_payment


class ReceivableBaseView(APIView):
    def get_business(self, request, business_public_id):
        return Business.objects.filter(
            public_id=business_public_id,
            members__identity=request.user,
            members__status="ACTIVE",
        ).first()

    @staticmethod
    def not_found():
        return Response({"detail": "Not found."}, status=404)

    def get_authorized_business(self, request, business_public_id, permission):
        """Resolve a tenant and require one explicit permission for a mutation."""
        business = Business.objects.filter(public_id=business_public_id).first()
        if business is None:
            return None

        require_permission(
            request.user,
            business,
            permission,
            write=True,
        )
        return business


class ReceivableListView(ReceivableBaseView):
    def get(self, request, business_public_id):
        business = self.get_business(request, business_public_id)
        if not business:
            return self.not_found()
        queryset = Receivable.objects.filter(business=business)
        if request.query_params.get("status"):
            queryset = queryset.filter(status=request.query_params["status"])
        if request.query_params.get("customer"):
            queryset = queryset.filter(customer__public_id=request.query_params["customer"])
        if request.query_params.get("overdue") == "true":
            queryset = [receivable for receivable in queryset if receivable.is_overdue]
        return Response(R(queryset, many=True).data)


class ReceivableDetailView(ReceivableListView):
    @staticmethod
    def get_receivable(business, receivable_public_id):
        return Receivable.objects.filter(business=business, public_id=receivable_public_id).first()

    def get(self, request, business_public_id, receivable_public_id):
        business = self.get_business(request, business_public_id)
        receivable = self.get_receivable(business, receivable_public_id) if business else None
        return Response(R(receivable).data) if receivable else self.not_found()

    def patch(self, request, business_public_id, receivable_public_id):
        business = self.get_authorized_business(
            request,
            business_public_id,
            BusinessMemberPermission.Permission.MANAGE_RECEIVABLES,
        )
        receivable = self.get_receivable(business, receivable_public_id) if business else None
        if not receivable:
            return self.not_found()
        for field in ("due_date", "notes"):
            if field in request.data:
                setattr(receivable, field, request.data[field])
        receivable.save(update_fields=("due_date", "notes", "updated_at"))
        return Response(R(receivable).data)


class ReceivablePaymentsView(ReceivableDetailView):
    def get(self, request, business_public_id, receivable_public_id):
        business = self.get_business(request, business_public_id)
        receivable = self.get_receivable(business, receivable_public_id) if business else None
        return Response(P(receivable.payments.all(), many=True).data) if receivable else self.not_found()

    def post(self, request, business_public_id, receivable_public_id):
        business = self.get_authorized_business(
            request,
            business_public_id,
            BusinessMemberPermission.Permission.MANAGE_RECEIVABLES,
        )
        receivable = self.get_receivable(business, receivable_public_id) if business else None
        if not receivable:
            return self.not_found()
        idempotency_key = request.headers.get("Idempotency-Key", "")
        if len(idempotency_key) > 255:
            return Response({"detail": "Invalid Idempotency-Key."}, status=400)
        try:
            payment = add_payment(
                receivable,
                request.user,
                Decimal(str(request.data.get("amount"))),
                request.data.get("payment_method"),
                request.data.get("reference", ""),
                request.data.get("notes", ""),
                idempotency_key=idempotency_key,
            )
        except IdempotencyConflict as exc:
            return Response({"detail": str(exc)}, status=409)
        except (InvalidOperation, TypeError, ValidationError):
            return Response({"detail": "Invalid payment."}, status=400)
        return Response(P(payment).data, status=201)


ReceivableDetailView.http_method_names = ["get", "patch", "head", "options"]
ReceivablePaymentsView.http_method_names = ["get", "post", "head", "options"]

ReceivableListView.get = extend_schema(
    tags=["Receivables"], operation_id="receivable_list", responses={200: R(many=True)}
)(ReceivableListView.get)
ReceivableDetailView.get = extend_schema(
    tags=["Receivables"], operation_id="receivable_retrieve", responses={200: R}
)(ReceivableDetailView.get)
ReceivableDetailView.patch = extend_schema(
    tags=["Receivables"],
    operation_id="receivable_update",
    request=R,
    responses={200: R, 403: None, 404: None},
)(ReceivableDetailView.patch)
ReceivablePaymentsView.get = extend_schema(
    tags=["Receivables"], operation_id="receivable_payment_list", responses={200: P(many=True)}
)(ReceivablePaymentsView.get)
ReceivablePaymentsView.post = extend_schema(
    tags=["Receivables"],
    operation_id="receivable_payment_create",
    parameters=[OpenApiParameter("Idempotency-Key", str, required=False, location=OpenApiParameter.HEADER)],
    request=P,
    responses={201: P, 400: None, 403: None, 404: None, 409: None},
)(ReceivablePaymentsView.post)
