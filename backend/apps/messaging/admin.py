from django.contrib import admin

from .models import BusinessMessagingSettings, Conversation, Inquiry, Message


@admin.register(BusinessMessagingSettings)
class BusinessMessagingSettingsAdmin(admin.ModelAdmin):
    list_display = ("business", "designated_agent", "is_enabled", "updated_at")
    list_filter = ("is_enabled",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(Inquiry)
class InquiryAdmin(admin.ModelAdmin):
    list_display = ("reference", "business", "buyer", "product_name", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("reference", "business__public_id", "product_name")
    readonly_fields = ("reference", "created_at", "updated_at", "product_reference", "product_name")


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("reference", "business", "buyer", "seller", "status", "last_message_at")
    list_filter = ("status",)
    search_fields = ("reference", "business__public_id")
    readonly_fields = ("reference", "created_at", "updated_at", "last_message_at")


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("reference", "conversation", "sender", "recipient", "sent_at", "read_at")
    search_fields = ("reference", "conversation__reference")
    readonly_fields = (
        "reference",
        "sender",
        "recipient",
        "sent_at",
        "received_at",
        "read_at",
        "file_sha256",
    )
