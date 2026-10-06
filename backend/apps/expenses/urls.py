from django.urls import path

from .views import Categories, CategoryDetail, ExpenseCancel, ExpenseDetail, Expenses

urlpatterns = [
    path("expense-categories/", Categories.as_view()),
    path("expense-categories/<str:category_public_id>/", CategoryDetail.as_view()),
    path("expenses/", Expenses.as_view()),
    path("expenses/<str:expense_public_id>/", ExpenseDetail.as_view()),
    path("expenses/<str:expense_public_id>/cancel/", ExpenseCancel.as_view()),
]
