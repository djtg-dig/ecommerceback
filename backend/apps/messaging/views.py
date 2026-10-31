"""API REST de la messagerie privée, sans consumer WebSocket métier."""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import FileResponse
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.businesses.models import Business

from .models import Conversation, Message
from .serializers import (
    ConversationCreateSerializer,
    ConversationSerializer,
    EligibleSellerSerializer,
    MessageSerializer,
    MessageWriteSerializer,
    conversation_seller_map,
    seller_projection,
)
from .services import (
    ConversationStateError,
    accessible_conversations,
    close_conversation,
    confirm_delivery,
    confirm_read,
    eligible_sellers,
    get_accessible_conversation,
    get_or_create_conversation,
    reopen_conversation,
    require_conversation_access,
    send_message,
)


class MessagingPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 100


def _validation_error(error):
    if hasattr(error, "message_dict"):
        raise serializers.ValidationError(error.message_dict) from error
    raise serializers.ValidationError({"detail": error.messages}) from error


def _state_conflict(error):
    return Response(
        {"code": "CONVERSATION_STATE_CONFLICT", "detail": str(error)},
        status=status.HTTP_409_CONFLICT,
    )


def _conversation_data(conversation, request):
    conversation = Conversation.objects.select_related("business", "buyer", "seller").get(pk=conversation.pk)
    return ConversationSerializer(
        conversation,
        context={
            "request": request,
            "seller_members": conversation_seller_map([conversation]),
        },
    ).data


class EligibleSellerListView(APIView):
    """Projection publique minimale des vendeurs, réservée aux utilisateurs authentifiés."""

    @extend_schema(responses=EligibleSellerSerializer(many=True), tags=["Messaging"])
    def get(self, request, business_reference):
        business = Business.objects.filter(
            public_id=business_reference,
            status=Business.Status.ACTIVE,
        ).first()
        if business is None:
            raise NotFound("Not found.")
        sellers = [seller_projection(member) for member in eligible_sellers(business=business, buyer=request.user)]
        return Response(EligibleSellerSerializer(sellers, many=True).data)


class ConversationListCreateView(APIView):
    @extend_schema(responses=ConversationSerializer(many=True), tags=["Messaging"])
    def get(self, request):
        conversations = accessible_conversations(request.user)
        business = request.query_params.get("business")
        if business:
            conversations = conversations.filter(business__public_id=business)
        conversation_status = request.query_params.get("status")
        if conversation_status:
            if conversation_status not in Conversation.Status.values:
                raise serializers.ValidationError({"status": "Statut de conversation invalide."})
            conversations = conversations.filter(status=conversation_status)
        paginator = MessagingPagination()
        page = paginator.paginate_queryset(conversations, request)
        page = list(page)
        data = ConversationSerializer(
            page,
            many=True,
            context={
                "request": request,
                "seller_members": conversation_seller_map(page),
            },
        ).data
        return paginator.get_paginated_response(data)

    @extend_schema(
        request=ConversationCreateSerializer,
        responses={200: ConversationSerializer, 201: ConversationSerializer},
        tags=["Messaging"],
    )
    def post(self, request):
        serializer = ConversationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        business = Business.objects.filter(public_id=serializer.validated_data["business"]).first()
        if business is None:
            raise serializers.ValidationError({"business": "Entreprise introuvable."})
        try:
            conversation, created = get_or_create_conversation(
                buyer=request.user,
                business=business,
                seller_reference=serializer.validated_data["seller"],
            )
        except DjangoValidationError as error:
            _validation_error(error)
        return Response(
            _conversation_data(conversation, request),
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class ConversationDetailView(APIView):
    @extend_schema(responses=ConversationSerializer, tags=["Messaging"])
    def get(self, request, conversation_reference):
        conversation = get_accessible_conversation(
            identity=request.user,
            reference=conversation_reference,
        )
        return Response(_conversation_data(conversation, request))


class ConversationMessageListCreateView(APIView):
    def conversation(self, request, reference, *, write=False):
        return get_accessible_conversation(
            identity=request.user,
            reference=reference,
            write=write,
        )

    @extend_schema(responses=MessageSerializer(many=True), tags=["Messaging"])
    def get(self, request, conversation_reference):
        conversation = self.conversation(request, conversation_reference)
        messages = conversation.messages.select_related(
            "conversation__buyer",
            "conversation__seller",
            "reply_to",
            "cart",
        )
        paginator = MessagingPagination()
        page = paginator.paginate_queryset(messages, request)
        return paginator.get_paginated_response(MessageSerializer(page, many=True).data)

    @extend_schema(
        request=MessageWriteSerializer,
        responses={201: MessageSerializer},
        tags=["Messaging"],
    )
    def post(self, request, conversation_reference):
        conversation = self.conversation(request, conversation_reference)
        serializer = MessageWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            message = send_message(
                identity=request.user,
                conversation=conversation,
                content=serializer.validated_data.get("content", ""),
                reply_reference=serializer.validated_data.get("reply_to", ""),
                cart_reference=serializer.validated_data.get("cart", ""),
                upload=serializer.validated_data.get("file"),
            )
        except DjangoValidationError as error:
            _validation_error(error)
        except ConversationStateError as error:
            return _state_conflict(error)
        message = Message.objects.select_related("conversation", "reply_to", "cart").get(pk=message.pk)
        return Response(MessageSerializer(message).data, status=status.HTTP_201_CREATED)


class MessageViewMixin:
    def message(self, request, conversation_reference, message_reference):
        conversation = get_accessible_conversation(
            identity=request.user,
            reference=conversation_reference,
        )
        message = Message.objects.select_related(
            "conversation__business",
            "conversation__buyer",
            "conversation__seller",
            "reply_to",
            "cart",
        ).filter(
            reference=message_reference,
            conversation=conversation,
        ).first()
        if message is None:
            raise NotFound("Not found.")
        return message


class MessageDetailView(MessageViewMixin, APIView):
    @extend_schema(responses=MessageSerializer, tags=["Messaging"])
    def get(self, request, conversation_reference, message_reference):
        return Response(MessageSerializer(self.message(request, conversation_reference, message_reference)).data)


class MessageReceivedView(MessageViewMixin, APIView):
    @extend_schema(request=None, responses=MessageSerializer, tags=["Messaging"])
    def post(self, request, conversation_reference, message_reference):
        message = self.message(request, conversation_reference, message_reference)
        return Response(MessageSerializer(confirm_delivery(identity=request.user, message=message)).data)


class MessageReadView(MessageViewMixin, APIView):
    @extend_schema(request=None, responses=MessageSerializer, tags=["Messaging"])
    def post(self, request, conversation_reference, message_reference):
        message = self.message(request, conversation_reference, message_reference)
        return Response(MessageSerializer(confirm_read(identity=request.user, message=message)).data)


class MessageAttachmentView(MessageViewMixin, APIView):
    @extend_schema(responses={(200, "application/octet-stream"): bytes}, tags=["Messaging"])
    def get(self, request, conversation_reference, message_reference):
        message = self.message(request, conversation_reference, message_reference)
        require_conversation_access(request.user, message.conversation)
        if not message.file:
            raise NotFound("Not found.")
        try:
            stream = message.file.open("rb")
        except FileNotFoundError as error:
            raise NotFound("Not found.") from error
        response = FileResponse(
            stream,
            as_attachment=True,
            filename=message.file_name,
            content_type=message.file_content_type or "application/octet-stream",
        )
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Security-Policy"] = "sandbox"
        return response


class ConversationCloseView(APIView):
    @extend_schema(request=None, responses=ConversationSerializer, tags=["Messaging"])
    def post(self, request, conversation_reference):
        conversation = get_accessible_conversation(identity=request.user, reference=conversation_reference)
        try:
            conversation = close_conversation(identity=request.user, conversation=conversation)
        except ConversationStateError as error:
            return _state_conflict(error)
        return Response(_conversation_data(conversation, request))


class ConversationReopenView(APIView):
    @extend_schema(request=None, responses=ConversationSerializer, tags=["Messaging"])
    def post(self, request, conversation_reference):
        conversation = get_accessible_conversation(identity=request.user, reference=conversation_reference)
        try:
            conversation = reopen_conversation(identity=request.user, conversation=conversation)
        except ConversationStateError as error:
            return _state_conflict(error)
        return Response(_conversation_data(conversation, request))
