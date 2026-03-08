# messaging/views.py
from django.db.models import Q
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from .models import Conversation, Message
from .serializers import ConversationSerializer, MessageSerializer
from shop.models import Shop


def _get_as_shop(request):
    shop_id = request.query_params.get('as_shop') or request.data.get('as_shop')
    if shop_id:
        try:
            return Shop.objects.get(pk=shop_id, owner=request.user)
        except Shop.DoesNotExist:
            pass
    return None


def _find_or_create_conversation(sender_user, sender_shop, target_user, target_shop):
    q1 = Q(user_a=sender_user, shop_a=sender_shop,
            user_b=target_user, shop_b=target_shop)
    q2 = Q(user_a=target_user, shop_a=target_shop,
            user_b=sender_user, shop_b=sender_shop)
    existing = Conversation.objects.filter(q1 | q2).first()
    if existing:
        return existing, False
    conv = Conversation.objects.create(
        user_a=sender_user, shop_a=sender_shop,
        user_b=target_user, shop_b=target_shop,
    )
    return conv, True


class ConversationListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        as_shop = _get_as_shop(request)
        if as_shop:
            qs = Conversation.objects.filter(
                Q(shop_a=as_shop) | Q(shop_b=as_shop)
            ).prefetch_related('messages').select_related(
                'user_a', 'user_b', 'shop_a', 'shop_b'
            )
        else:
            qs = Conversation.objects.filter(
                (Q(user_a=request.user) & Q(shop_a=None)) |
                (Q(user_b=request.user) & Q(shop_b=None))
            ).prefetch_related('messages').select_related(
                'user_a', 'user_b', 'shop_a', 'shop_b'
            )
        serializer = ConversationSerializer(
            qs, many=True,
            context={'request': request, 'as_shop': as_shop}
        )
        return Response(serializer.data)


class ConversationStartView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        as_shop     = _get_as_shop(request)
        target_type = request.data.get('target_type')
        target_id   = request.data.get('target_id')

        if not target_type or not target_id:
            return Response({'detail': 'target_type and target_id are required.'}, status=400)

        target_user = target_shop = None
        if target_type == 'shop':
            try:
                target_shop = Shop.objects.get(pk=target_id)
            except Shop.DoesNotExist:
                return Response({'detail': 'Shop not found.'}, status=404)
            if target_shop.owner == request.user and not as_shop:
                return Response({'detail': 'Cannot message your own shop.'}, status=400)
        elif target_type == 'user':
            from django.contrib.auth import get_user_model
            User = get_user_model()
            try:
                target_user = User.objects.get(pk=target_id)
            except User.DoesNotExist:
                return Response({'detail': 'User not found.'}, status=404)
        else:
            return Response({'detail': 'Invalid target_type.'}, status=400)

        sender_user = None if as_shop else request.user
        conv, _     = _find_or_create_conversation(sender_user, as_shop, target_user, target_shop)

        serializer = ConversationSerializer(
            conv, context={'request': request, 'as_shop': as_shop}
        )
        return Response(serializer.data, status=status.HTTP_200_OK)


class MessageListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, conv_id):
        as_shop = _get_as_shop(request)
        try:
            # ── fetch the conversation as a queryset first, then get() ──
            if as_shop:
                conv = Conversation.objects.select_related(
                    'user_a', 'user_b', 'shop_a', 'shop_b'
                ).get(pk=conv_id)
                if conv.shop_a_id != as_shop.id and conv.shop_b_id != as_shop.id:
                    return Response(status=403)
            else:
                conv = Conversation.objects.select_related(
                    'user_a', 'user_b', 'shop_a', 'shop_b'
                ).get(
                    Q(pk=conv_id) & (
                        (Q(user_a=request.user) & Q(shop_a=None)) |
                        (Q(user_b=request.user) & Q(shop_b=None))
                    )
                )
        except Conversation.DoesNotExist:
            return Response(status=404)

        # Mark incoming messages as read
        unread_qs = conv.messages.filter(read=False)
        if as_shop:
            unread_qs.exclude(sender_shop=as_shop).update(read=True)
        else:
            unread_qs.exclude(sender_user=request.user).update(read=True)

        messages = conv.messages.select_related('sender_user', 'sender_shop').order_by('created_at')
        return Response(MessageSerializer(messages, many=True, context={'request': request}).data)


class MessageSendView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, conv_id):
        as_shop = _get_as_shop(request)
        body    = request.data.get('body', '').strip()
        file    = request.FILES.get('attachment')

        if not body and not file:
            return Response({'detail': 'Message body or attachment is required.'}, status=400)

        try:
            conv = Conversation.objects.get(pk=conv_id)
        except Conversation.DoesNotExist:
            return Response(status=404)

        if as_shop:
            if conv.shop_a_id != as_shop.id and conv.shop_b_id != as_shop.id:
                return Response(status=403)
            msg = Message.objects.create(
                conversation=conv, sender_shop=as_shop,
                body=body, attachment=file
            )
        else:
            has_access = (
                (conv.user_a_id == request.user.id and conv.shop_a_id is None) or
                (conv.user_b_id == request.user.id and conv.shop_b_id is None)
            )
            if not has_access:
                return Response(status=403)
            msg = Message.objects.create(
                conversation=conv, sender_user=request.user,
                body=body, attachment=file
            )

        conv.save(update_fields=['updated_at'])
        return Response(MessageSerializer(msg, context={'request': request}).data, status=201)