from datetime import date
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.businesses.models import Business
from apps.businesses.permissions import can_manage_business, membership_for
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
)
from .services import cancel_expense

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
    }


class BusinessScopedView(APIView):
    def business_for(self, request, public_id):
        return Business.objects.filter(
            public_id=public_id,
            members__identity=request.user,
            members__status="ACTIVE",
        ).first()

    @staticmethod
    def not_found():
        return Response({"detail": "Not found."}, status=404)

    @staticmethod
    def forbidden():
        return Response({"detail": "Forbidden."}, status=403)

    def manageable_business(self, request, public_id):
        business = self.business_for(request, public_id)
        if not business:
            return None
        return business if can_manage_business(membership_for(request.user, business)) else False


class Categories(BusinessScopedView):
    def get(self, request, business_public_id):
        business = self.business_for(request, business_public_id)
        if not business:
            return self.not_found()
        categories = ExpenseCategory.objects.filter(business=business)

        return Response(category_data(category) for category in categories)

    def post(self, request, business_public_id):
        business = self.manageable_business(request, business_public_id)
        if business is None:
            return self.not_found()
        if business is False:
            return self.forbidden()
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
    def get_object(self, request, business_public_id, category_public_id):
        business = self.business_for(request, business_public_id)
        if not business:
            return None, None
        category = ExpenseCategory.objects.filter(
            business=business,
            public_id=category_public_id,
        ).first()

        return business, category

    def get(self, request, business_public_id, category_public_id):
        business, category = self.get_object(request, business_public_id, category_public_id)
        if not business or not category:
            return self.not_found()
        return Response(category_data(category))

    def patch(self, request, business_public_id, category_public_id):
        business, category = self.get_object(request, business_public_id, category_public_id)
        if not business or not category:
            return self.not_found()
        if not can_manage_business(membership_for(request.user, business)):
            return self.forbidden()
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
        business = self.business_for(request, business_public_id)
        if not business:
            return self.not_found()
        queryset = Expense.objects.select_related("category").filter(business=business)
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
        business = self.manageable_business(request, business_public_id)
        if business is None:
            return self.not_found()
        if business is False:
            return self.forbidden()
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
    def get_object(self, request, business_public_id, expense_public_id):
        business = self.business_for(request, business_public_id)
        if not business:
            return None, None
        expense = Expense.objects.select_related("category").filter(
            business=business,
            public_id=expense_public_id,
        ).first()

        return business, expense

    def get(self, request, business_public_id, expense_public_id):
        business, expense = self.get_object(request, business_public_id, expense_public_id)
        if not business or not expense:
            return self.not_found()
        return Response(expense_data(expense))

    def patch(self, request, business_public_id, expense_public_id):
        business, expense = self.get_object(request, business_public_id, expense_public_id)
        if not business or not expense:
            return self.not_found()
        if not can_manage_business(membership_for(request.user, business)):
            return self.forbidden()
        if expense.status != Expense.Status.ACTIVE:
            return Response({"detail": "Cancelled expenses are immutable."}, status=400)
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
        if "category" in request.data:
            category = ExpenseCategory.objects.filter(
                business=business, public_id=request.data["category"], is_active=True
            ).first()
            if not category:
                return Response({"detail": "Invalid category."}, status=400)
            expense.category = category
        if "amount" in request.data:
            try:
                amount = Decimal(str(request.data["amount"]))
            except (InvalidOperation, TypeError, ValueError):
                amount = Decimal(0)
            if amount <= 0:
                return Response({"detail": "Amount must be positive."}, status=400)
            expense.amount = amount
        if "currency" in request.data:
            if request.data["currency"] != business.primary_currency:
                return Response(
                    {"detail": "Currency must match the Business primary currency."},
                    status=400,
                )
            expense.currency = business.primary_currency
        if "payment_method" in request.data:
            if request.data["payment_method"] not in PaymentMethod.values:
                return Response({"detail": "Invalid payment method."}, status=400)
            expense.payment_method = request.data["payment_method"]
        if "expense_date" in request.data:
            try:
                expense.expense_date = date.fromisoformat(request.data["expense_date"])
            except (TypeError, ValueError):
                return Response({"detail": "Invalid expense date."}, status=400)
        for field in ("description", "reference"):
            if field in request.data:
                setattr(expense, field, request.data[field])
        try:
            expense.save()
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
        business, expense = ExpenseDetail().get_object(request, business_public_id, expense_public_id)
        if not business or not expense:
            return self.not_found()
        if not can_manage_business(membership_for(request.user, business)):
            return self.forbidden()
        reason = request.data.get("cancellation_reason", "")
        if not isinstance(reason, str) or not reason.strip():
            return Response({"detail": "A cancellation reason is required."}, status=400)
        try:
            expense = cancel_expense(expense, request.user, reason)
        except ValidationError:
            return Response({"detail": "This expense cannot be cancelled."}, status=400)
        return Response(expense_data(expense))


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
    responses={200: ExpenseCategorySerializer(many=True), 404: None},
)(Categories.get)
Categories.post = extend_schema(
    tags=["Expense Categories"],
    operation_id="expense_category_create",
    parameters=[_business_id],
    request=ExpenseCategoryCreateSerializer,
    responses={201: ExpenseCategorySerializer, 400: None, 403: None, 404: None},
    description="OWNER et MANAGER créent les catégories personnalisées d'un Business.",
)(Categories.post)
CategoryDetail.get = extend_schema(
    tags=["Expense Categories"],
    operation_id="expense_category_retrieve",
    parameters=[_business_id, _category_id],
    responses={200: ExpenseCategorySerializer, 404: None},
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
    responses={200: ExpenseSerializer(many=True), 400: None, 404: None},
)(Expenses.get)
Expenses.post = extend_schema(
    tags=["Expenses"],
    operation_id="expense_create",
    parameters=[_business_id],
    request=ExpenseCreateSerializer,
    responses={201: ExpenseSerializer, 400: None, 403: None, 404: None},
    description="OWNER et MANAGER créent une dépense ACTIVE avec une catégorie active.",
)(Expenses.post)
ExpenseDetail.get = extend_schema(
    tags=["Expenses"],
    operation_id="expense_retrieve",
    parameters=[_business_id, _expense_id],
    responses={200: ExpenseSerializer, 404: None},
)(ExpenseDetail.get)
ExpenseDetail.patch = extend_schema(
    tags=["Expenses"],
    operation_id="expense_update",
    parameters=[_business_id, _expense_id],
    request=ExpenseUpdateSerializer,
    responses={200: ExpenseSerializer, 400: None, 403: None, 404: None},
    description="Une dépense CANCELLED est terminale ; status ne se modifie pas par PATCH.",
)(ExpenseDetail.patch)
ExpenseCancel.post = extend_schema(
    tags=["Expenses"],
    operation_id="expense_cancel",
    parameters=[_business_id, _expense_id],
    request=ExpenseCancelSerializer,
    responses={200: ExpenseSerializer, 400: None, 403: None, 404: None},
    description="Transition terminale ACTIVE vers CANCELLED pour OWNER et MANAGER.",
)(ExpenseCancel.post)
