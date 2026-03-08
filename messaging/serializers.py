# messaging/serializers.py
from rest_framework import serializers
from .models import Conversation, Message


class MessageSerializer(serializers.ModelSerializer):
    sender_name    = serializers.CharField(read_only=True)
    sender_type    = serializers.SerializerMethodField()
    sender_id      = serializers.SerializerMethodField()
    sender_avatar  = serializers.SerializerMethodField()
    attachment_url = serializers.SerializerMethodField()

    class Meta:
        model  = Message
        fields = ['id', 'conversation', 'sender_name', 'sender_type', 'sender_id',
                  'sender_avatar', 'body', 'attachment_url', 'created_at', 'read']

    def get_sender_type(self, obj):
        return 'shop' if obj.sender_shop_id else 'user'

    def get_sender_id(self, obj):
        return obj.sender_shop_id or obj.sender_user_id

    def get_sender_avatar(self, obj):
        request = self.context.get('request')
        if obj.sender_shop and obj.sender_shop.avatar:
            url = obj.sender_shop.avatar.url
            return request.build_absolute_uri(url) if request else url
        return None

    def get_attachment_url(self, obj):
        request = self.context.get('request')
        if obj.attachment:
            url = obj.attachment.url
            return request.build_absolute_uri(url) if request else url
        return None


class ConversationSerializer(serializers.ModelSerializer):
    other_name      = serializers.SerializerMethodField()
    other_avatar    = serializers.SerializerMethodField()
    other_type      = serializers.SerializerMethodField()
    other_id        = serializers.SerializerMethodField()
    last_message    = serializers.SerializerMethodField()
    last_message_at = serializers.SerializerMethodField()
    unread_count    = serializers.SerializerMethodField()

    class Meta:
        model  = Conversation
        fields = ['id', 'other_name', 'other_avatar', 'other_type', 'other_id',
                  'last_message', 'last_message_at', 'unread_count', 'updated_at']

    def _me(self, obj):
        request = self.context.get('request')
        as_shop = self.context.get('as_shop')
        user    = request.user if request else None
        if as_shop:
            if obj.shop_a_id == as_shop.id: return 'a'
            if obj.shop_b_id == as_shop.id: return 'b'
        if user:
            if obj.user_a_id == user.id and not obj.shop_a_id: return 'a'
            if obj.user_b_id == user.id and not obj.shop_b_id: return 'b'
        return 'a'

    def _other(self, obj):
        me         = self._me(obj)
        other_side = 'b' if me == 'a' else 'a'
        shop = obj.shop_b if other_side == 'b' else obj.shop_a
        user = obj.user_b if other_side == 'b' else obj.user_a
        if shop: return ('shop', shop)
        return ('user', user)

    def get_other_name(self, obj):
        kind, entity = self._other(obj)
        if not entity: return 'Unknown'
        return entity.shop_name if kind == 'shop' else (entity.full_name or entity.email)

    def get_other_avatar(self, obj):
        request = self.context.get('request')
        kind, entity = self._other(obj)
        if kind == 'shop' and entity and entity.avatar:
            url = entity.avatar.url
            return request.build_absolute_uri(url) if request else url
        return None

    def get_other_type(self, obj):
        kind, _ = self._other(obj)
        return kind

    def get_other_id(self, obj):
        kind, entity = self._other(obj)
        return entity.id if entity else None

    def get_last_message(self, obj):
        msg = obj.messages.last()
        return msg.body if msg else None

    def get_last_message_at(self, obj):
        msg = obj.messages.last()
        return msg.created_at if msg else obj.updated_at

    def get_unread_count(self, obj):
        me = self._me(obj)
        qs = obj.messages.filter(read=False)
        if me == 'a':
            if obj.shop_b_id:  qs = qs.filter(sender_shop_id=obj.shop_b_id)
            elif obj.user_b_id: qs = qs.filter(sender_user_id=obj.user_b_id)
        else:
            if obj.shop_a_id:  qs = qs.filter(sender_shop_id=obj.shop_a_id)
            elif obj.user_a_id: qs = qs.filter(sender_user_id=obj.user_a_id)
        return qs.count()