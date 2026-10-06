from django.urls import path

from .views import (
    FinancialMovementDetailView,
    FinancialMovementListView,
    FinancialSummaryView,
)

urlpatterns = [
    path("financial-movements/", FinancialMovementListView.as_view()),
    path(
        "financial-movements/<str:movement_public_id>/",
        FinancialMovementDetailView.as_view(),
    ),
    path("financial-summary/", FinancialSummaryView.as_view()),
]
