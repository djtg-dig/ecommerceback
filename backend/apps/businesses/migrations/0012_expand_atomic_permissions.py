from django.db import migrations


LEGACY_PERMISSION_MAP = {
    "VIEW_MEMBERS": ["MEMBER_VIEW", "MEMBER_PERMISSION_VIEW", "INVITATION_VIEW"],
    "MANAGE_MEMBERS": [
        "MEMBER_UPDATE", "MEMBER_SUSPEND", "MEMBER_REACTIVATE", "MEMBER_REMOVE",
        "MEMBER_PERMISSION_GRANT", "MEMBER_PERMISSION_REVOKE",
        "INVITATION_CREATE", "INVITATION_RESEND", "INVITATION_REVOKE",
    ],
    "UPDATE_BUSINESS": ["BUSINESS_UPDATE"],
    "VIEW_PAYMENT_METHODS": ["PAYMENT_METHOD_VIEW"],
    "MANAGE_PAYMENT_METHODS": ["PAYMENT_METHOD_CREATE", "PAYMENT_METHOD_UPDATE"],
    "VIEW_CUSTOMERS": ["CUSTOMER_VIEW"],
    "MANAGE_CUSTOMERS": ["CUSTOMER_CREATE", "CUSTOMER_UPDATE", "CUSTOMER_DEACTIVATE", "CUSTOMER_REACTIVATE"],
    "VIEW_CATALOG": ["PRODUCT_VIEW", "PRODUCT_VARIANT_VIEW"],
    "MANAGE_CATALOG": ["PRODUCT_CREATE", "PRODUCT_UPDATE", "PRODUCT_DEACTIVATE", "PRODUCT_VARIANT_CREATE", "PRODUCT_VARIANT_UPDATE"],
    "VIEW_INVENTORY": ["INVENTORY_VIEW", "INVENTORY_MOVEMENT_VIEW"],
    "MANAGE_INVENTORY": ["INVENTORY_INITIALIZE", "INVENTORY_IN", "INVENTORY_OUT", "INVENTORY_ADJUST"],
    "VIEW_PURCHASES": ["SUPPLIER_VIEW", "PURCHASE_VIEW", "PURCHASE_LINE_VIEW", "SUPPLIER_PAYMENT_VIEW"],
    "MANAGE_PURCHASES": [
        "SUPPLIER_CREATE", "SUPPLIER_UPDATE", "SUPPLIER_DEACTIVATE", "SUPPLIER_REACTIVATE",
        "PURCHASE_CREATE", "PURCHASE_UPDATE", "PURCHASE_CONFIRM", "PURCHASE_RECEIVE", "PURCHASE_CANCEL",
        "PURCHASE_LINE_CREATE", "PURCHASE_LINE_UPDATE", "PURCHASE_LINE_DELETE",
        "SUPPLIER_PAYMENT_CREATE", "SUPPLIER_PAYMENT_REVERSE",
    ],
    "USE_POS": ["SALE_CREATE", "SALE_UPDATE", "SALE_LINE_CREATE", "SALE_COMPLETE"],
    "VIEW_SALES": ["SALE_VIEW", "SALE_LINE_VIEW"],
    "MANAGE_SALES": ["SALE_CANCEL"],
    "MANAGE_SALE_RETURNS": ["SALE_RETURN_VIEW", "SALE_RETURN"],
    "VIEW_RECEIVABLES": ["RECEIVABLE_VIEW", "RECEIVABLE_PAYMENT_VIEW"],
    "MANAGE_RECEIVABLES": ["RECEIVABLE_UPDATE", "RECEIVABLE_PAYMENT_CREATE"],
    "VIEW_FINANCIAL_SUMMARY": ["FINANCIAL_SUMMARY_VIEW", "FINANCIAL_MOVEMENT_VIEW"],
    "MANAGE_EXPENSE_CATEGORIES": ["EXPENSE_CATEGORY_CREATE", "EXPENSE_CATEGORY_UPDATE"],
    "CREATE_EXPENSES": ["EXPENSE_CREATE"],
    "VIEW_EXPENSES": ["EXPENSE_CATEGORY_VIEW", "EXPENSE_VIEW", "EXPENSE_PAYMENT_VIEW"],
    "MANAGE_EXPENSES": ["EXPENSE_UPDATE", "EXPENSE_CANCEL", "EXPENSE_PAYMENT_CREATE", "EXPENSE_PAYMENT_REVERSE"],
    "VIEW_DASHBOARD": ["DASHBOARD_VIEW"],
    "VIEW_PROFITABILITY": ["PROFITABILITY_VIEW"],
    "VIEW_REPORTS": ["SALE_REPORT_VIEW", "PURCHASE_REPORT_VIEW", "EXPENSE_RECEIVABLE_REPORT_VIEW"],
}
ATOMIC_PERMISSION_VALUES = frozenset(
    permission
    for permissions in LEGACY_PERMISSION_MAP.values()
    for permission in permissions
) | {"PRODUCT_DELETE"}


def forwards(apps, schema_editor):
    Permission = apps.get_model("businesses", "BusinessMemberPermission")
    Invitation = apps.get_model("businesses", "BusinessMemberInvitation")

    # Keep legacy rows during this expansion step so either application version
    # remains authorized throughout a rolling deployment.
    for row in Permission.objects.filter(permission__in=LEGACY_PERMISSION_MAP):
        Permission.objects.bulk_create(
            [Permission(member_id=row.member_id, permission=value) for value in LEGACY_PERMISSION_MAP[row.permission]],
            ignore_conflicts=True,
        )

    for invitation in Invitation.objects.all().only("pk", "permissions"):
        expanded = []
        for permission in invitation.permissions or []:
            if permission in LEGACY_PERMISSION_MAP:
                expanded.append(permission)
                expanded.extend(LEGACY_PERMISSION_MAP[permission])
            elif permission in ATOMIC_PERMISSION_VALUES:
                expanded.append(permission)
        normalized = list(dict.fromkeys(expanded))
        if normalized != invitation.permissions:
            invitation.permissions = normalized
            invitation.save(update_fields=("permissions",))


def backwards(apps, schema_editor):
    # Removing only the new rows is unsafe when they may have been granted
    # independently after deployment. Keep them on rollback.
    pass


class Migration(migrations.Migration):
    dependencies = [("businesses", "0011_businessmemberinvitation_permissions")]
    operations = [migrations.RunPython(forwards, backwards)]
