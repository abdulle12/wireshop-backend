from rest_framework import serializers
from django.contrib.auth import get_user_model

from .models import EscrowTransaction, Notification

User = get_user_model()


def _user_display_name(user):
    """
    Single source of truth for user display names across all escrow serializers.
    Priority: full_name → first+last → email prefix (never raw email).
    Matches frontend getUserDisplayName() and backend NotificationSerializer._display_name.
    """
    full = (getattr(user, 'full_name', '') or '').strip()
    if full:
        return full
    first  = (user.first_name or '').strip()
    last   = (user.last_name  or '').strip()
    joined = ' '.join(p for p in [first, last] if p)
    if joined:
        return joined
    return (user.email or '').split('@')[0].replace('.', ' ').replace('_', ' ').title()


# ── EscrowTransaction ──────────────────────────────────────────────────────────

class EscrowTransactionSerializer(serializers.ModelSerializer):
    # Buyer identity
    buyer_name        = serializers.SerializerMethodField()
    buyer_email       = serializers.EmailField(source='buyer.email', read_only=True)
    buyer_shop_name   = serializers.CharField(source='buyer_shop.shop_name', read_only=True, default=None)
    buyer_shop_avatar = serializers.SerializerMethodField()

    # Product extras — slug, description and first image from the live Product FK
    product_slug        = serializers.SerializerMethodField()
    product_description = serializers.SerializerMethodField()
    product_image       = serializers.SerializerMethodField()

    # Seller identity
    seller_name        = serializers.SerializerMethodField()
    seller_email       = serializers.EmailField(source='seller.email', read_only=True)
    seller_shop_name   = serializers.CharField(source='seller_shop.shop_name', read_only=True, default=None)
    seller_shop_slug   = serializers.CharField(source='seller_shop.slug',      read_only=True, default=None)
    seller_shop_avatar = serializers.SerializerMethodField()

    class Meta:
        model  = EscrowTransaction
        fields = [
            # IDs & status
            'id', 'status',

            # Buyer
            'buyer_name', 'buyer_email',
            'buyer_shop_name', 'buyer_shop_avatar',

            # Seller
            'seller_name', 'seller_email',
            'seller_shop_name', 'seller_shop_slug', 'seller_shop_avatar',

            # Product snapshot
            'product_title', 'product_slug', 'product_description', 'product_image',
            'quantity', 'unit_price',

            # Money
            'subtotal', 'platform_fee', 'total_amount', 'seller_payout',

            # Shipping
            'shipping_address',
            'payment_method',
            'carrier', 'tracking_number',
            'estimated_delivery_date', 'delivery_time_window',

            # Timestamps
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'status',
            'buyer_name', 'buyer_email', 'buyer_shop_name', 'buyer_shop_avatar',
            'seller_name', 'seller_email', 'seller_shop_name', 'seller_shop_slug', 'seller_shop_avatar',
            'subtotal', 'platform_fee', 'total_amount', 'seller_payout',
            'created_at', 'updated_at',
        ]

    def get_product_slug(self, obj):
        if obj.product:
            return obj.product.slug
        return None

    def get_product_description(self, obj):
        if obj.product:
            return obj.product.description
        return None

    def get_product_image(self, obj):
        if not obj.product:
            return None
        images = obj.product.images
        if not images or not isinstance(images, list):
            return None
        first = images[0]
        if not first:
            return None
        if str(first).startswith("http"):
            return str(first)
        request = self.context.get("request")
        return request.build_absolute_uri(first) if request else first

    def get_buyer_name(self, obj):
        if obj.buyer_shop:
            return obj.buyer_shop.shop_name
        return _user_display_name(obj.buyer)

    def get_seller_name(self, obj):
        if obj.seller_shop:
            return obj.seller_shop.shop_name
        return _user_display_name(obj.seller)

    def get_buyer_shop_avatar(self, obj):
        if obj.buyer_shop and obj.buyer_shop.avatar:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.buyer_shop.avatar.url)
            return obj.buyer_shop.avatar.url
        return None

    def get_seller_shop_avatar(self, obj):
        if obj.seller_shop and obj.seller_shop.avatar:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.seller_shop.avatar.url)
            return obj.seller_shop.avatar.url
        return None
class NotificationSerializer(serializers.ModelSerializer):
    transaction    = serializers.UUIDField(source='transaction.id', read_only=True)
    avatar         = serializers.SerializerMethodField()
    actor_name     = serializers.SerializerMethodField()
    actor_initials = serializers.SerializerMethodField()
    # Rich row extras — sent to frontend for Facebook-style rendering
    product_title  = serializers.CharField(source='transaction.product_title', read_only=True)
    product_image  = serializers.SerializerMethodField()

    class Meta:
        model  = Notification
        fields = [
            'id', 'kind', 'title', 'message',
            'is_read', 'created_at',
            'transaction',
            'avatar', 'actor_name', 'actor_initials',
            'product_title', 'product_image',
        ]
        read_only_fields = fields

    # ── helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _display_name(user):
        """Delegates to module-level _user_display_name for consistency."""
        return _user_display_name(user)

    @staticmethod
    def _initials(display_name):
        """
        "Noor Hassan" → "NH"   "Ali Aden" → "AA"   "Wireshops Escrow" → "WE"
        """
        parts = display_name.replace('.', '').split()
        return ''.join(p[0].upper() for p in parts[:2])

    @staticmethod
    def _user_photo(user, request):
        """
        Returns the user's real profile photo URL if they have one.
        Works with a UserProfile.profile_picture field (OneToOne on User).
        Returns None if no photo — frontend will render initials avatar instead.
        """
        try:
            photo = user.userprofile.profile_picture
            if photo:
                url = photo.url if hasattr(photo, 'url') else str(photo)
                return request.build_absolute_uri(url) if request else url
        except Exception:
            pass
        return None

    def _abs(self, image_field):
        if not image_field:
            return None
        request = self.context.get('request')
        url = image_field.url if hasattr(image_field, 'url') else str(image_field)
        return request.build_absolute_uri(url) if request else url

    def _actor_user_and_shop(self, obj):
        """
        Returns (user, shop_or_None) for whoever triggered this notification.
        Buyer-triggered: order_placed, receipt_confirmed, dispute_opened
        Seller-triggered: shipped
        System: funds_released, refunded
        """
        tx = obj.transaction
        if obj.kind in (
            Notification.KIND_ORDER_PLACED,
            Notification.KIND_RECEIPT_CONFIRMED,
            Notification.KIND_DISPUTE_OPENED,
        ):
            return tx.buyer, tx.buyer_shop
        if obj.kind == Notification.KIND_SHIPPED:
            return tx.seller, tx.seller_shop
        return None, None  # system

    # ── serializer methods ─────────────────────────────────────────────────────

    def get_product_image(self, obj):
        product = obj.transaction.product
        if not product:
            return None
        images = product.images
        if not images or not isinstance(images, list):
            return None
        first = images[0]
        if not first:
            return None
        if str(first).startswith('http'):
            return str(first)
        request = self.context.get('request')
        return request.build_absolute_uri(first) if request else first

    def get_actor_name(self, obj):
        user, shop = self._actor_user_and_shop(obj)
        if user is None:
            return 'Wireshops Escrow'
        if shop:
            return shop.shop_name
        return self._display_name(user)

    def get_actor_initials(self, obj):
        return self._initials(self.get_actor_name(obj))

    def get_avatar(self, obj):
        request = self.context.get('request')
        user, shop = self._actor_user_and_shop(obj)

        if user is None:
            # System notification — no avatar, frontend renders "W" monogram
            return None

        # Shop avatar takes priority (shop logo)
        if shop and shop.avatar:
            return self._abs(shop.avatar)

        # Real user profile photo
        photo = self._user_photo(user, request)
        if photo:
            return photo

        # No photo — return None so frontend renders initials circle
        return None


# ── Request-body serializers ───────────────────────────────────────────────────

class ShippingAddressSerializer(serializers.Serializer):
    first_name = serializers.CharField()
    last_name  = serializers.CharField()
    address    = serializers.CharField()
    city       = serializers.CharField()
    state      = serializers.CharField()
    phone      = serializers.CharField()


class CheckoutSerializer(serializers.Serializer):
    """
    POST /api/escrow/checkout/

    {
      product_id:       <int>,
      quantity:         <int>,
      payment_method:   'mpesa' | 'card' | 'paypal',
      payment_ref:      <str>,
      shipping_address: { first_name, last_name, address, city, state, phone },
      as_shop:          <int> | null
    }
    """
    product_id       = serializers.IntegerField()
    quantity         = serializers.IntegerField(min_value=1, default=1)
    payment_method   = serializers.ChoiceField(choices=['card', 'mpesa', 'paypal'])
    payment_ref      = serializers.CharField(allow_blank=True, required=False, default='')
    shipping_address = ShippingAddressSerializer()
    as_shop          = serializers.IntegerField(required=False, allow_null=True)


class ShipOrderSerializer(serializers.Serializer):
    """
    POST /api/escrow/<pk>/ship/

    { carrier, tracking_number, delivery_date, time_window }
    """
    carrier         = serializers.CharField()
    tracking_number = serializers.CharField()
    delivery_date   = serializers.DateField(required=False, allow_null=True)
    time_window     = serializers.CharField(allow_blank=True, required=False, default='')