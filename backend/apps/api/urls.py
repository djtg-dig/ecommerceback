"""Versioned API routes."""
from django.urls import include

from django.urls import path

from .views import HealthCheckView
from apps.businesses.views import (
    BusinessCategoriesView,
    BusinessInvitationAcceptView,
    BusinessInvitationAccountAcceptView,
    BusinessInvitationAccountDeclineView,
    BusinessInvitationDeclineView,
    BusinessInvitationRecipientListView,
    CurrencyListView,
)
from apps.dashboard_views import DashboardView
from apps.profitability_views import ProfitabilitySummaryView
from apps.sales_report_views import ProductReportView, SalesReportView
from apps.expense_receivable_report_views import ExpensesReportView, ReceivablesReportView
from apps.purchase_report_views import PurchasesReportView, SupplierDebtsReportView
from apps.catalog.views import UnitOfMeasureListView
from apps.catalog.views import PublicBusinessView, PublicCatalogPagination, PublicCategoryProductsView, PublicHomeProductsView, PublicProductDetailView, PublicProductSearchView, PublicSuggestionsView
from apps.messaging.views import EligibleSellerListView

urlpatterns = [
    path("currencies/", CurrencyListView.as_view(), name="currency-list"),
    path("units-of-measure/", UnitOfMeasureListView.as_view(), name="unit-of-measure-list"),
    path("public/products/home/", PublicHomeProductsView.as_view()),
    path("public/products/search/", PublicProductSearchView.as_view()),
    path("public/products/suggestions/", PublicSuggestionsView.as_view()),
    path("public/products/<str:product_public_id>/", PublicProductDetailView.as_view()),
    path("public/categories/<slug:slug>/", PublicCategoryProductsView.as_view()),
    path("public/businesses/<str:business_public_id>/", PublicBusinessView.as_view()),
    path(
        "public/businesses/<str:business_reference>/messaging-sellers/",
        EligibleSellerListView.as_view(),
        name="messaging-seller-list",
    ),
    path(
        "me/business-invitations/",
        BusinessInvitationRecipientListView.as_view(),
        name="business-invitation-recipient-list",
    ),
    path(
        "me/business-invitations/<str:invitation_public_id>/accept-authenticated/",
        BusinessInvitationAccountAcceptView.as_view(),
        name="business-invitation-account-accept",
    ),
    path(
        "me/business-invitations/<str:invitation_public_id>/decline-authenticated/",
        BusinessInvitationAccountDeclineView.as_view(),
        name="business-invitation-account-decline",
    ),
    path(
        "me/business-invitations/<str:invitation_public_id>/accept/",
        BusinessInvitationAcceptView.as_view(),
        name="business-invitation-accept",
    ),
    path(
        "me/business-invitations/<str:invitation_public_id>/decline/",
        BusinessInvitationDeclineView.as_view(),
        name="business-invitation-decline",
    ),
    path("businesses/<str:business_public_id>/dashboard/", DashboardView.as_view()),
    path("businesses/<str:business_public_id>/profitability-summary/", ProfitabilitySummaryView.as_view()),
    path("businesses/<str:business_public_id>/reports/sales/", SalesReportView.as_view()),
    path("businesses/<str:business_public_id>/reports/products/", ProductReportView.as_view()),
    path("businesses/<str:business_public_id>/reports/expenses/", ExpensesReportView.as_view()),
    path("businesses/<str:business_public_id>/reports/receivables/", ReceivablesReportView.as_view()),
    path("businesses/<str:business_public_id>/reports/purchases/", PurchasesReportView.as_view()),
    path("businesses/<str:business_public_id>/reports/supplier-debts/", SupplierDebtsReportView.as_view()),
    path("businesses/<str:business_public_id>/", include("apps.expenses.urls")),
    path("businesses/<str:business_public_id>/", include("apps.finance.urls")),
    path("businesses/<str:business_public_id>/", include("apps.receivables.urls")),
    path("businesses/<str:business_public_id>/", include("apps.sales.urls")),
    path("businesses/<str:business_public_id>/", include("apps.purchases.urls")),
    path("businesses/<str:business_public_id>/inventory/", include("apps.inventory.urls")),
    path("businesses/<str:business_public_id>/products/", include("apps.catalog.product_urls")),
    path("businesses/", include("apps.businesses.urls")),
    path("business-categories/", BusinessCategoriesView.as_view()),
    path("product-categories/", include("apps.catalog.urls")),
    path("carts/", include("apps.carts.urls")),
    path("messaging/", include("apps.messaging.urls")),
    path("health/", HealthCheckView.as_view(), name="health"),
    path("auth/", include("apps.accounts.urls")),
]
