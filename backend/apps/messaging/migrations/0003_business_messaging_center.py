import uuid

import django.db.models.deletion
from django.db import migrations, models
from django.db.models import Q


def preserve_legacy_sender_members(apps, schema_editor):
    Message = apps.get_model("messaging", "Message")
    BusinessMember = apps.get_model("businesses", "BusinessMember")
    for message in Message.objects.select_related("conversation"):
        if message.sender_id == message.conversation.buyer_id:
            continue
        member = BusinessMember.objects.filter(
            business_id=message.conversation.business_id,
            identity_id=message.sender_id,
        ).first()
        if member:
            Message.objects.filter(pk=message.pk).update(sender_member_id=member.pk)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0005_carriidentity_avatar_url"), ("businesses", "0009_address_administrativearea_country_and_more"), ("catalog", "0009_product_is_home_deliverable_and_more"), ("messaging", "0002_websocketticket")]
    operations = [
        migrations.AddField(model_name="conversation", name="kind", field=models.CharField(choices=[("DIRECT", "Direct discussion"), ("INQUIRY", "Commercial inquiry")], db_index=True, default="DIRECT", max_length=12)),
        migrations.RemoveConstraint(model_name="conversation", name="messaging_conversation_participants_unique"),
        migrations.AddConstraint(constraint=models.UniqueConstraint(fields=("business", "buyer", "seller", "kind"), name="messaging_conversation_participants_unique"), model_name="conversation"),
        migrations.AddIndex(model_name="conversation", index=models.Index(fields=["business", "kind"], name="msg_conv_business_kind_idx")),
        migrations.AddField(model_name="message", name="sender_member", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="messaging_messages_sent", to="businesses.businessmember")),
        migrations.CreateModel(name="BusinessMessagingSettings", fields=[("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("is_enabled", models.BooleanField(default=True)), ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)), ("business", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="messaging_settings", to="businesses.business")), ("designated_agent", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="designated_messaging_for", to="businesses.businessmember"))]),
        migrations.CreateModel(name="Inquiry", fields=[("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)), ("reference", models.CharField(db_index=True, editable=False, max_length=12, unique=True)), ("product_reference", models.CharField(blank=True, default="", max_length=12)), ("product_name", models.CharField(blank=True, default="", max_length=240)), ("quantity", models.DecimalField(blank=True, decimal_places=3, max_digits=14, null=True)), ("description", models.TextField(blank=True, default="")), ("status", models.CharField(choices=[("OPEN", "Open"), ("IN_PROGRESS", "In progress"), ("CLOSED", "Closed")], db_index=True, default="OPEN", max_length=16)), ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)), ("business", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="messaging_inquiries", to="businesses.business")), ("buyer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="messaging_inquiries", to="accounts.carriidentity")), ("conversation", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="inquiry", to="messaging.conversation")), ("product", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="messaging_inquiries", to="catalog.product"))], options={"ordering": ("-created_at",)}),
        migrations.AddIndex(model_name="inquiry", index=models.Index(fields=["business", "status"], name="msg_inquiry_biz_status_idx")),
        migrations.RunPython(preserve_legacy_sender_members, migrations.RunPython.noop),
    ]
