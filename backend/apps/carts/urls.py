from django.urls import path

from .views import AddToCartView, CartClearView, CartDetailView, CartItemDetailView, CartItemListCreateView, CartListCreateView, CartTransferView

urlpatterns = [
    path("", CartListCreateView.as_view(), name="cart-list-create"),
    path("items/", AddToCartView.as_view(), name="cart-add-product"),
    path("transfers/", CartTransferView.as_view(), name="cart-transfer"),
    path("<str:reference>/", CartDetailView.as_view(), name="cart-detail"),
    path("<str:reference>/items/", CartItemListCreateView.as_view(), name="cart-item-list-create"),
    path("<str:reference>/items/<str:product_reference>/", CartItemDetailView.as_view(), name="cart-item-detail"),
    path("<str:reference>/clear/", CartClearView.as_view(), name="cart-clear"),
]
