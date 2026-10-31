from django.contrib import admin

from .models import Conversation, Message


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
