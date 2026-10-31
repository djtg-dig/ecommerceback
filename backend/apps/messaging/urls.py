from django.urls import path

from .views import (
    ConversationCloseView,
    ConversationDetailView,
    ConversationListCreateView,
    ConversationMessageListCreateView,
    ConversationReopenView,
    MessageAttachmentView,
    MessageDetailView,
    MessageReadView,
    MessageReceivedView,
)


urlpatterns = [
    path("conversations/", ConversationListCreateView.as_view(), name="conversation-list-create"),
    path("conversations/<str:conversation_reference>/", ConversationDetailView.as_view(), name="conversation-detail"),
    path("conversations/<str:conversation_reference>/close/", ConversationCloseView.as_view(), name="conversation-close"),
    path("conversations/<str:conversation_reference>/reopen/", ConversationReopenView.as_view(), name="conversation-reopen"),
    path("conversations/<str:conversation_reference>/messages/", ConversationMessageListCreateView.as_view(), name="message-list-create"),
    path("conversations/<str:conversation_reference>/messages/<str:message_reference>/", MessageDetailView.as_view(), name="message-detail"),
    path("conversations/<str:conversation_reference>/messages/<str:message_reference>/received/", MessageReceivedView.as_view(), name="message-received"),
    path("conversations/<str:conversation_reference>/messages/<str:message_reference>/read/", MessageReadView.as_view(), name="message-read"),
    path("conversations/<str:conversation_reference>/messages/<str:message_reference>/attachment/", MessageAttachmentView.as_view(), name="message-attachment"),
]
