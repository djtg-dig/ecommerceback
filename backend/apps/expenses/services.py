from django.utils import timezone
STANDARD=(('RENT','Loyer'),('ELECTRICITY','Électricité'),('WATER','Eau'),('INTERNET','Internet'),('TRANSPORT','Transport'),('SALARY','Salaire'),('MAINTENANCE','Maintenance'),('SUPPLIES','Fournitures'),('TAX','Taxe / impôt'),('MARKETING','Marketing'),('OTHER','Autre'))
def ensure_default_expense_categories(business):
 from .models import ExpenseCategory
 for i,(code,name) in enumerate(STANDARD):ExpenseCategory.objects.get_or_create(business=business,code=code,defaults={'name':name,'is_system':True,'sort_order':i})
