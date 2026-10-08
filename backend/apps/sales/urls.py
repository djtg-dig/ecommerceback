from django.urls import path
from .views import *
urlpatterns=[path('customers/',Customers.as_view()),path('sales/',Sales.as_view()),path('sales/<str:sale_public_id>/',SD.as_view()),path('sales/<str:sale_public_id>/lines/',Lines.as_view()),path('sales/<str:sale_public_id>/complete/',Complete.as_view()),path('sales/<str:sale_public_id>/cancel/',Cancel.as_view()),path('sales/<str:sale_public_id>/returns/',SaleReturns.as_view())]
