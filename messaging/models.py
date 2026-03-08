from django.db import models

# Create your models here.
# messaging/models.py
from django.db import models
from django.conf import settings


class Conversation(models.Model):
    """
    A conversation has exactly two participants.
    Each participant can be either a User (personal) or a Shop.
    """
    # Participant A
    user_a  = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                on_delete=models.CASCADE, related_name='conversations_as_a')
    shop_a  = models.ForeignKey('shop.Shop', null=True, blank=True,
                                on_delete=models.CASCADE, related_name='conversations_as_a')

    # Participant B
    user_b  = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                on_delete=models.CASCADE, related_name='conversations_as_b')
    shop_b  = models.ForeignKey('shop.Shop', null=True, blank=True,
                                on_delete=models.CASCADE, related_name='conversations_as_b')

    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def get_participants(self):
        return {
            'a': {'type': 'shop', 'obj': self.shop_a}  if self.shop_a else {'type': 'user', 'obj': self.user_a},
            'b': {'type': 'shop', 'obj': self.shop_b}  if self.shop_b else {'type': 'user', 'obj': self.user_b},
        }

    def __str__(self):
        p = self.get_participants()
        def name(x): return x['obj'].shop_name if x['type'] == 'shop' else x['obj'].email
        return f"{name(p['a'])} ↔ {name(p['b'])}"


class Message(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='messages')

    sender_user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.CASCADE, related_name='sent_messages')
    sender_shop = models.ForeignKey('shop.Shop', null=True, blank=True,
                                    on_delete=models.CASCADE, related_name='sent_messages')

    body        = models.TextField(blank=True)          # can be empty if attachment sent
    attachment  = models.FileField(upload_to='messages/attachments/', null=True, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    read        = models.BooleanField(default=False)

    class Meta:
        ordering = ['created_at']

    @property
    def sender_name(self):
        if self.sender_shop: return self.sender_shop.shop_name
        if self.sender_user: return self.sender_user.full_name or self.sender_user.email
        return 'Unknown'

    @property
    def sender_avatar(self):
        if self.sender_shop and self.sender_shop.avatar:
            return self.sender_shop.avatar.url
        return None

    def __str__(self):
        return f"{self.sender_name}: {self.body[:40] or '[attachment]'}"
