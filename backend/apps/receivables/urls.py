from django.urls import path

from .views import ReceivableDetailView, ReceivableListView, ReceivablePaymentsView

urlpatterns = [
    path("receivables/", ReceivableListView.as_view()),
    path("receivables/<str:receivable_public_id>/", ReceivableDetailView.as_view()),
    path(
        "receivables/<str:receivable_public_id>/payments/",
        ReceivablePaymentsView.as_view(),
    ),
]
