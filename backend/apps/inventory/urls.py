"""Tenant inventory routes."""

from django.urls import path

from .views import BusinessStockMovementHistoryView, InventoryDetailView, InventoryListCreateView, InventorySummaryView, StockMovementListCreateView

urlpatterns = [
    path("", InventoryListCreateView.as_view(), name="inventory-list-create"),
    path("summary/", InventorySummaryView.as_view(), name="inventory-summary"),
    path("movements/", BusinessStockMovementHistoryView.as_view(), name="inventory-movement-history"),
    path("<str:inventory_public_id>/", InventoryDetailView.as_view(), name="inventory-detail"),
    path("<str:inventory_public_id>/movements/", StockMovementListCreateView.as_view(), name="stock-movement-list-create"),
]
