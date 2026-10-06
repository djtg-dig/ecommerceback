from django.urls import path
from .views import Categories,Expenses
urlpatterns=[path('expense-categories/',Categories.as_view()),path('expenses/',Expenses.as_view())]
