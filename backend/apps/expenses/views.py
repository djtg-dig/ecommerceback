from datetime import date
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db.models import DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.businesses.models import Business, BusinessMemberPermission
from apps.businesses.permissions import require_permission
from apps.common.choices import PaymentMethod

from .models import Expense, ExpenseCategory
from .serializers import (
    ExpenseCancelSerializer,
    ExpenseCategoryCreateSerializer,
    ExpenseCategorySerializer,
    ExpenseCategoryUpdateSerializer,
    ExpenseCreateSerializer,
    ExpenseSerializer,
    ExpenseUpdateSerializer,
    ExpensePaymentCreateSerializer,
    ExpensePaymentReverseSerializer,
    ExpensePaymentSerializer,
)
from .services import (
    ExpensePaymentIdempotencyConflict,
    add_expense_payment,
    cancel_expense,
    reverse_expense_payment,
    update_expense,
)


def category_data(category):
    return {
        "public_id": category.public_id,
        "code": category.code,
        "name": category.name,
        "description": category.description,
        "is_system": category.is_system,
        "is_active": category.is_active,
        "sort_order": category.sort_order,
    }


def expense_data(expense):
    return {
        "public_id": expense.public_id,
        "category": expense.category.public_id,
        "amount": str(expense.amount),
        "currency": expense.currency,
        "payment_method": expense.payment_method,
        "expense_date": expense.expense_date.isoformat(),
        "description": expense.description,
        "reference": expense.reference,
        "status": expense.status,
        "created_by": str(expense.created_by_id),
        "created_at": expense.created_at.isoformat(),
        "updated_at": expense.updated_at.isoformat(),
        "cancelled_by": str(expense.cancelled_by_id) if expense.cancelled_by_id else None,
        "cancelled_at": expense.cancelled_at.isoformat() if expense.cancelled_at else None,
        "cancellation_reason": expense.cancellation_reason,
        "paid_amount": str(expense.paid_amount),
        "balance": str(expense.balance),
        "payment_status": expense.payment_status,
    }


class BusinessScopedView(APIView):
    def business_for(self, request, public_id, permission, *, write=False):
        """Resolve one tenant and enforce its server-defined permission."""
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

    @staticmethod
    def not_found():
        return Response({"detail": "Not found."}, status=404)

    @staticmethod
    def forbidden():
        return Response({"detail": "Forbidden."}, status=403)

class Categories(BusinessScopedView):
    def get(self, request, business_public_id):
        business = self.business_for(
            request,
            business_public_id,
            BusinessMemberPermission.Permission.VIEW_EXPENSES,
        )
        if not business:
            return self.not_found()
        categories = ExpenseCategory.objects.filter(business=business)

        return Response(category_data(category) for category in categories)

    def post(self, request, business_public_id):
        business = self.business_for(
            request,
            business_public_id,
            BusinessMemberPermission.Permission.MANAGE_EXPENSE_CATEGORIES,
            write=True,
        )
        if business is None:
            return self.not_found()
        name = request.data.get("name")
        if not isinstance(name, str) or not name.strip():
            return Response({"detail": "A category name is required."}, status=400)
        code = request.data.get("code") or name.upper().replace(" ", "_")
        try:
            category = ExpenseCategory.objects.create(
                business=business,
                code=code,
                name=name,
                description=request.data.get("description", ""),
                sort_order=request.data.get("sort_order", 0),
            )
        except ValidationError as error:
            detail = (
                error.message_dict
                if hasattr(error, "message_dict")
                else error.messages
            )
            return Response({"detail": detail}, status=400)
        return Response(category_data(category), status=201)


class CategoryDetail(BusinessScopedView):
    def get_object(
        self,
        request,
        business_public_id,
        category_public_id,
        permission,
        *,
        write=False,
    ):
        business = self.business_for(
            request,
            business_public_id,
            permission,
            write=write,
        )
        if not business:
            return None, None
        category = ExpenseCategory.objects.filter(
            business=business,
            public_id=category_public_id,
        ).first()

        return business, category

    def get(self, request, business_public_id, category_public_id):
        business, category = self.get_object(
            request,
            business_public_id,
            category_public_id,
            BusinessMemberPermission.Permission.VIEW_EXPENSES,
        )
        if not business or not category:
            return self.not_found()
        return Response(category_data(category))

    def patch(self, request, business_public_id, category_public_id):
        business, category = self.get_object(
            request,
            business_public_id,
            category_public_id,
            BusinessMemberPermission.Permission.MANAGE_EXPENSE_CATEGORIES,
            write=True,
        )
        if not business or not category:
            return self.not_found()
        immutable_fields = {"public_id", "business", "is_system"}
        if category.is_system:
            immutable_fields.update({"code", "name", "description", "sort_order"})
        if any(field in request.data for field in immutable_fields):
            return Response({"detail": "This category field is immutable."}, status=400)
        allowed_fields = {"code", "name", "description", "is_active", "sort_order"}
        for field in allowed_fields.intersection(request.data):
            setattr(category, field, request.data[field])
        try:
            category.save()
        except ValidationError as error:
            detail = (
                error.message_dict
                if hasattr(error, "message_dict")
                else error.messages
            )
            return Response({"detail": detail}, status=400)
        return Response(category_data(category))


class Expenses(BusinessScopedView):
    def get(self, request, business_public_id):
        business = self.business_for(
            request,
            business_public_id,
            BusinessMemberPermission.Permission.VIEW_EXPENSES,
        )
        if not business:
            return self.not_found()
        queryset = Expense.objects.select_related("category").filter(business=business).annotate(
            computed_paid_amount=Coalesce(
                Sum("payments__amount", filter=Q(payments__reversed_at__isnull=True)),
                Value(Decimal("0")),
                output_field=DecimalField(max_digits=16, decimal_places=2),
            )
        )
        validators = {
            "status": {choice for choice, _ in Expense.Status.choices},
            "currency": {choice for choice, _ in Expense.Currency.choices},
            "payment_method": set(PaymentMethod.values),
        }
        for parameter, permitted in validators.items():
            value = request.query_params.get(parameter)
            if value:
                if value not in permitted:
                    return Response({"detail": f"Invalid {parameter}."}, status=400)
                queryset = queryset.filter(**{parameter: value})
        category = request.query_params.get("category")
        if category:
            if not ExpenseCategory.objects.filter(business=business, public_id=category).exists():
                return Response({"detail": "Invalid category."}, status=400)
            queryset = queryset.filter(category__public_id=category)
        date_filters = (
            ("date_from", "expense_date__gte"),
            ("date_to", "expense_date__lte"),
        )
        for parameter, lookup in date_filters:
            value = request.query_params.get(parameter)
            if value:
                try:
                    parsed_date = date.fromisoformat(value)
                except ValueError:
                    return Response({"detail": f"Invalid {parameter}."}, status=400)
                queryset = queryset.filter(**{lookup: parsed_date})
        return Response([expense_data(expense) for expense in queryset])

    def post(self, request, business_public_id):
        business = self.business_for(
            request,
            business_public_id,
            BusinessMemberPermission.Permission.CREATE_EXPENSES,
            write=True,
        )
        if business is None:
            return self.not_found()
        category = ExpenseCategory.objects.filter(
            business=business, public_id=request.data.get("category"), is_active=True
        ).first()
        try:
            amount = Decimal(str(request.data.get("amount")))
        except (InvalidOperation, TypeError, ValueError):
            amount = Decimal(0)
        requested_currency = request.data.get("currency")
        if requested_currency and requested_currency != business.primary_currency:
            return Response(
                {"detail": "Currency must match the Business primary currency."},
                status=400,
            )

        currency = business.primary_currency
        payment_method = request.data.get("payment_method", "CASH")
        if (
            not category
            or amount <= 0
            or currency not in Expense.Currency.values
            or payment_method not in PaymentMethod.values
        ):
            return Response({"detail": "Invalid expense."}, status=400)
        try:
            expense_date = date.fromisoformat(
                request.data.get("expense_date", date.today().isoformat())
            )
        except (TypeError, ValueError):
            return Response({"detail": "Invalid expense date."}, status=400)
        expense = Expense.objects.create(
            business=business,
            category=category,
            amount=amount,
            currency=currency,
            payment_method=payment_method,
            expense_date=expense_date,
            description=request.data.get("description", ""),
            reference=request.data.get("reference", ""),
            created_by=request.user,
        )
        return Response(expense_data(expense), status=201)


class ExpenseDetail(BusinessScopedView):
    def get_object(
        self,
        request,
        business_public_id,
        expense_public_id,
        permission,
        *,
        write=False,
    ):
        business = self.business_for(
            request,
            business_public_id,
            permission,
            write=write,
        )
        if not business:
            return None, None
        expense = Expense.objects.select_related("category").annotate(
            computed_paid_amount=Coalesce(
                Sum("payments__amount", filter=Q(payments__reversed_at__isnull=True)),
                Value(Decimal("0")),
                output_field=DecimalField(max_digits=16, decimal_places=2),
            )
        ).filter(business=business, public_id=expense_public_id).first()

        return business, expense

    def get(self, request, business_public_id, expense_public_id):
        business, expense = self.get_object(
            request,
            business_public_id,
            expense_public_id,
            BusinessMemberPermission.Permission.VIEW_EXPENSES,
        )
        if not business or not expense:
            return self.not_found()
        return Response(expense_data(expense))

    def patch(self, request, business_public_id, expense_public_id):
        business, expense = self.get_object(
            request,
            business_public_id,
            expense_public_id,
            BusinessMemberPermission.Permission.MANAGE_EXPENSES,
            write=True,
        )
        if not business or not expense:
            return self.not_found()
        allowed_fields = {
            "category",
            "amount",
            "currency",
            "payment_method",
            "expense_date",
            "description",
            "reference",
        }
        unknown_fields = set(request.data).difference(allowed_fields)
        if unknown_fields:
            return Response({"detail": "One or more fields cannot be changed."}, status=400)
        changes = {}
        if "category" in request.data:
            category = ExpenseCategory.objects.filter(
                business=business, public_id=request.data["category"], is_active=True
            ).first()
            if not category:
                return Response({"detail": "Invalid category."}, status=400)
            changes["category"] = category
        if "amount" in request.data:
            try:
                amount = Decimal(str(request.data["amount"]))
            except (InvalidOperation, TypeError, ValueError):
                amount = Decimal(0)
            if amount <= 0:
                return Response({"detail": "Amount must be positive."}, status=400)
            changes["amount"] = amount
        if "currency" in request.data:
            if request.data["currency"] != business.primary_currency:
                return Response(
                    {"detail": "Currency must match the Business primary currency."},
                    status=400,
                )
            changes["currency"] = business.primary_currency
        if "payment_method" in request.data:
            if request.data["payment_method"] not in PaymentMethod.values:
                return Response({"detail": "Invalid payment method."}, status=400)
            changes["payment_method"] = request.data["payment_method"]
        if "expense_date" in request.data:
            try:
                changes["expense_date"] = date.fromisoformat(
                    request.data["expense_date"]
                )
            except (TypeError, ValueError):
                return Response({"detail": "Invalid expense date."}, status=400)
        for field in ("description", "reference"):
            if field in request.data:
                changes[field] = request.data[field]
        try:
            expense = update_expense(expense, changes)
        except ValidationError as error:
            detail = (
                error.message_dict
                if hasattr(error, "message_dict")
                else error.messages
            )
            return Response({"detail": detail}, status=400)
        return Response(expense_data(expense))


class ExpenseCancel(BusinessScopedView):
    def post(self, request, business_public_id, expense_public_id):
        business, expense = ExpenseDetail().get_object(
            request,
            business_public_id,
            expense_public_id,
            BusinessMemberPermission.Permission.MANAGE_EXPENSES,
            write=True,
        )
        if not business or not expense:
            return self.not_found()
        reason = request.data.get("cancellation_reason", "")
        if not isinstance(reason, str) or not reason.strip():
            return Response({"detail": "A cancellation reason is required."}, status=400)
        try:
            expense = cancel_expense(expense, request.user, reason)
        except ValidationError:
            return Response({"detail": "This expense cannot be cancelled."}, status=400)
        return Response(expense_data(expense))


def expense_payment_data(payment):
    return {
        "public_id": payment.public_id,
        "amount": str(payment.amount),
        "payment_method": payment.payment_method,
        "paid_at": payment.paid_at.isoformat(),
        "created_by": str(payment.created_by_id),
        "created_at": payment.created_at.isoformat(),
        "is_reversed": payment.is_reversed,
        "reversed_at": payment.reversed_at.isoformat() if payment.reversed_at else None,
        "reversed_by": str(payment.reversed_by_id) if payment.reversed_by_id else None,
        "reversal_reason": payment.reversal_reason,
    }


class ExpensePayments(BusinessScopedView):
    def get_expense(
        self,
        request,
        business_public_id,
        expense_public_id,
        permission,
        *,
        write=False,
    ):
        business = self.business_for(
            request,
            business_public_id,
            permission,
            write=write,
        )
        if not business:
            return None, None
        expense = Expense.objects.filter(
            business=business,
            public_id=expense_public_id,
        ).first()
        return business, expense

    def get(self, request, business_public_id, expense_public_id):
        business, expense = self.get_expense(
            request,
            business_public_id,
            expense_public_id,
            BusinessMemberPermission.Permission.VIEW_EXPENSES,
        )
        if not business or not expense:
            return self.not_found()
        payments = expense.payments.select_related("created_by", "reversed_by")
        return Response([expense_payment_data(payment) for payment in payments])

    def post(self, request, business_public_id, expense_public_id):
        business, expense = self.get_expense(
            request,
            business_public_id,
            expense_public_id,
            BusinessMemberPermission.Permission.MANAGE_EXPENSES,
            write=True,
        )
        if not business or not expense:
            return self.not_found()
        serializer = ExpensePaymentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        key = request.headers.get("Idempotency-Key", "")
        if len(key) > 255:
            return Response({"detail": "Invalid Idempotency-Key."}, status=400)
        try:
            payment = add_expense_payment(
                expense,
                request.user,
                idempotency_key=key,
                **serializer.validated_data,
            )
        except ExpensePaymentIdempotencyConflict as error:
            return Response({"detail": str(error)}, status=409)
        except ValidationError as error:
            return Response({"detail": str(error)}, status=400)
        return Response(expense_payment_data(payment), status=201)


class ExpensePaymentReverse(ExpensePayments):
    def post(
        self,
        request,
        business_public_id,
        expense_public_id,
        payment_public_id,
    ):
        business, expense = self.get_expense(
            request,
            business_public_id,
            expense_public_id,
            BusinessMemberPermission.Permission.MANAGE_EXPENSES,
            write=True,
        )
        payment = (
            expense.payments.filter(public_id=payment_public_id).first()
            if expense
            else None
        )
        if not business or not expense or not payment:
            return self.not_found()
        serializer = ExpensePaymentReverseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            payment = reverse_expense_payment(
                payment,
                request.user,
                serializer.validated_data["reason"],
            )
        except ValidationError as error:
            return Response({"detail": str(error)}, status=400)
        return Response(expense_payment_data(payment))


# APIViews use explicit schemas because the implementation returns plain dictionaries.
_business_id = OpenApiParameter(
    "business_public_id",
    OpenApiTypes.STR,
    OpenApiParameter.PATH,
    description="Identifiant public du Business, préfixé par SH.",
)
_category_id = OpenApiParameter(
    "category_public_id",
    OpenApiTypes.STR,
    OpenApiParameter.PATH,
    description="Identifiant public de catégorie, préfixé par EC.",
)
_expense_id = OpenApiParameter(
    "expense_public_id",
    OpenApiTypes.STR,
    OpenApiParameter.PATH,
    description="Identifiant public de dépense, préfixé par EX.",
)
_expense_filters = [
    OpenApiParameter("category", OpenApiTypes.STR, OpenApiParameter.QUERY),
    OpenApiParameter("status", OpenApiTypes.STR, OpenApiParameter.QUERY),
    OpenApiParameter("payment_method", OpenApiTypes.STR, OpenApiParameter.QUERY),
    OpenApiParameter("currency", OpenApiTypes.STR, OpenApiParameter.QUERY),
    OpenApiParameter(
        "date_from",
        OpenApiTypes.DATE,
        OpenApiParameter.QUERY,
        description="Date minimale au format YYYY-MM-DD.",
    ),
    OpenApiParameter(
        "date_to",
        OpenApiTypes.DATE,
        OpenApiParameter.QUERY,
        description="Date maximale au format YYYY-MM-DD.",
    ),
]

Categories.get = extend_schema(
    tags=["Expense Categories"],
    operation_id="expense_category_list",
    parameters=[_business_id],
    responses={200: ExpenseCategorySerializer(many=True), 403: None, 404: None},
)(Categories.get)
Categories.post = extend_schema(
    tags=["Expense Categories"],
    operation_id="expense_category_create",
    parameters=[_business_id],
    request=ExpenseCategoryCreateSerializer,
    responses={201: ExpenseCategorySerializer, 400: None, 403: None, 404: None},
    description=(
        "Le propriétaire ou un membre ayant MANAGE_EXPENSE_CATEGORIES crée "
        "les catégories personnalisées d'un Business."
    ),
)(Categories.post)
CategoryDetail.get = extend_schema(
    tags=["Expense Categories"],
    operation_id="expense_category_retrieve",
    parameters=[_business_id, _category_id],
    responses={200: ExpenseCategorySerializer, 403: None, 404: None},
)(CategoryDetail.get)
CategoryDetail.patch = extend_schema(
    tags=["Expense Categories"],
    operation_id="expense_category_update",
    parameters=[_business_id, _category_id],
    request=ExpenseCategoryUpdateSerializer,
    responses={200: ExpenseCategorySerializer, 400: None, 403: None, 404: None},
    description="Les catégories système protègent leurs champs métier.",
)(CategoryDetail.patch)
Expenses.get = extend_schema(
    tags=["Expenses"],
    operation_id="expense_list",
    parameters=[_business_id, *_expense_filters],
    responses={200: ExpenseSerializer(many=True), 400: None, 403: None, 404: None},
)(Expenses.get)
Expenses.post = extend_schema(
    tags=["Expenses"],
    operation_id="expense_create",
    parameters=[_business_id],
    request=ExpenseCreateSerializer,
    responses={201: ExpenseSerializer, 400: None, 403: None, 404: None},
    description=(
        "Le propriétaire ou un membre ayant CREATE_EXPENSES crée une dépense "
        "ACTIVE avec une catégorie active."
    ),
)(Expenses.post)
ExpenseDetail.get = extend_schema(
    tags=["Expenses"],
    operation_id="expense_retrieve",
    parameters=[_business_id, _expense_id],
    responses={200: ExpenseSerializer, 403: None, 404: None},
)(ExpenseDetail.get)
ExpenseDetail.patch = extend_schema(
    tags=["Expenses"],
    operation_id="expense_update",
    parameters=[_business_id, _expense_id],
    request=ExpenseUpdateSerializer,
    responses={200: ExpenseSerializer, 400: None, 403: None, 404: None},
    description=(
        "Une dépense CANCELLED est terminale ; status ne se modifie pas par "
        "PATCH. Le montant ne peut pas devenir inférieur au total déjà payé."
    ),
)(ExpenseDetail.patch)
ExpenseCancel.post = extend_schema(
    tags=["Expenses"],
    operation_id="expense_cancel",
    parameters=[_business_id, _expense_id],
    request=ExpenseCancelSerializer,
    responses={200: ExpenseSerializer, 400: None, 403: None, 404: None},
    description=(
        "Transition terminale ACTIVE vers CANCELLED pour le propriétaire ou "
        "un membre ayant MANAGE_EXPENSES."
    ),
)(ExpenseCancel.post)

ExpensePayments.get = extend_schema(
    tags=["Expense Payments"],
    operation_id="expense_payment_list",
    parameters=[_business_id, _expense_id],
    responses={
        200: ExpensePaymentSerializer(many=True),
        403: None,
        404: None,
    },
)(ExpensePayments.get)
ExpensePayments.post = extend_schema(
    tags=["Expense Payments"],
    operation_id="expense_payment_create",
    request=ExpensePaymentCreateSerializer,
    parameters=[
        _business_id,
        _expense_id,
        OpenApiParameter(
            "Idempotency-Key",
            OpenApiTypes.STR,
            OpenApiParameter.HEADER,
            required=False,
        ),
    ],
    responses={
        201: ExpensePaymentSerializer,
        400: None,
        403: None,
        404: None,
        409: None,
    },
)(ExpensePayments.post)
ExpensePaymentReverse.post = extend_schema(
    tags=["Expense Payments"],
    operation_id="expense_payment_reverse",
    request=ExpensePaymentReverseSerializer,
    parameters=[
        _business_id,
        _expense_id,
        OpenApiParameter(
            "payment_public_id",
            OpenApiTypes.STR,
            OpenApiParameter.PATH,
        ),
    ],
    responses={
        200: ExpensePaymentSerializer,
        400: None,
        403: None,
        404: None,
    },
)(ExpensePaymentReverse.post)

ExpensePayments.http_method_names = ["get", "post", "head", "options"]
ExpensePaymentReverse.http_method_names = ["post", "options"]
