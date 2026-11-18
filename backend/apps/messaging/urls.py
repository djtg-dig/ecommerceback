from django.urls import path

from .views import (
    ConversationCloseView,
    ConversationDetailView,
    ConversationListCreateView,
    ConversationMessageListCreateView,
    ConversationReopenView,
    ConversationWebSocketTicketView,
    BusinessMessagingSettingsView,
    InquiryDetailView,
    InquiryListCreateView,
    MessageAttachmentView,
    MessageDetailView,
    MessageReadView,
    MessageReceivedView,
)


urlpatterns = [
    path("businesses/<str:business_reference>/settings/", BusinessMessagingSettingsView.as_view()),
    path("conversations/", ConversationListCreateView.as_view(), name="conversation-list-create"),
    path("conversations/<str:conversation_reference>/", ConversationDetailView.as_view(), name="conversation-detail"),
    path("conversations/<str:conversation_reference>/close/", ConversationCloseView.as_view(), name="conversation-close"),
    path("conversations/<str:conversation_reference>/reopen/", ConversationReopenView.as_view(), name="conversation-reopen"),
    path("conversations/<str:conversation_reference>/websocket-ticket/", ConversationWebSocketTicketView.as_view(), name="conversation-websocket-ticket"),
    path("conversations/<str:conversation_reference>/messages/", ConversationMessageListCreateView.as_view(), name="message-list-create"),
    path("conversations/<str:conversation_reference>/messages/<str:message_reference>/", MessageDetailView.as_view(), name="message-detail"),
    path("conversations/<str:conversation_reference>/messages/<str:message_reference>/received/", MessageReceivedView.as_view(), name="message-received"),
    path("conversations/<str:conversation_reference>/messages/<str:message_reference>/read/", MessageReadView.as_view(), name="message-read"),
    path("conversations/<str:conversation_reference>/messages/<str:message_reference>/attachment/", MessageAttachmentView.as_view(), name="message-attachment"),
    path("inquiries/", InquiryListCreateView.as_view()),
    path("inquiries/<str:inquiry_reference>/", InquiryDetailView.as_view()),
]
