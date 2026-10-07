"""Versioned API routes."""
from django.urls import include

from django.urls import path

from .views import HealthCheckView
from apps.businesses.views import BusinessCategoriesView
from apps.dashboard_views import DashboardView
from apps.profitability_views import ProfitabilitySummaryView
from apps.sales_report_views import ProductReportView, SalesReportView
from apps.expense_receivable_report_views import ExpensesReportView, ReceivablesReportView
from apps.purchase_report_views import PurchasesReportView, SupplierDebtsReportView

urlpatterns = [
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
    path("health/", HealthCheckView.as_view(), name="health"),
    path("auth/", include("apps.accounts.urls")),
]
