from django.urls import path
from .views import *
urlpatterns=[path('receivables/',List.as_view()),path('receivables/<str:receivable_public_id>/',Detail.as_view()),path('receivables/<str:receivable_public_id>/payments/',Payments.as_view())]
