import uuid
from decimal import Decimal
from django.db import models
from django.conf import settings

User = settings.AUTH_USER_MODEL


class EscrowTransaction(models.Model):
    STATUS_PENDING   = 'pending'
    STATUS_HELD      = 'held'
    STATUS_SHIPPED   = 'shipped'
    STATUS_DELIVERED = 'delivered'
    STATUS_RELEASED  = 'released'
    STATUS_DISPUTED  = 'disputed'
    STATUS_REFUNDED  = 'refunded'

    STATUS_CHOICES = [
        (STATUS_PENDING,   'Pending'),
        (STATUS_HELD,      'Held'),
        (STATUS_SHIPPED,   'Shipped'),
        (STATUS_DELIVERED, 'Delivered'),
        (STATUS_RELEASED,  'Released'),
        (STATUS_DISPUTED,  'Disputed'),
        (STATUS_REFUNDED,  'Refunded'),
    ]

    PLATFORM_FEE_RATE = Decimal('0.0499')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # ── Buyer ──────────────────────────────────────────────────────────────────
    buyer      = models.ForeignKey(User, on_delete=models.PROTECT, related_name='purchases')
    buyer_shop = models.ForeignKey(                          # set when buyer checked out AS a shop
        'shop.Shop', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='shop_purchases'
    )

    # ── Seller ─────────────────────────────────────────────────────────────────
    seller      = models.ForeignKey(User, on_delete=models.PROTECT, related_name='sales')
    seller_shop = models.ForeignKey(
        'shop.Shop', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='shop_sales'
    )

    # ── Product snapshot (denormalised so deleting the product doesn't break records)
    product       = models.ForeignKey('shop.Product', on_delete=models.SET_NULL, null=True)
    product_title = models.CharField(max_length=255)
    quantity      = models.PositiveIntegerField(default=1)
    unit_price    = models.DecimalField(max_digits=12, decimal_places=2)

    # ── Money ──────────────────────────────────────────────────────────────────
    subtotal      = models.DecimalField(max_digits=12, decimal_places=2)   # unit_price × qty
    platform_fee  = models.DecimalField(max_digits=10, decimal_places=2)   # subtotal × 0.0499
    total_amount  = models.DecimalField(max_digits=12, decimal_places=2)   # what buyer pays (= subtotal for now)
    seller_payout = models.DecimalField(max_digits=12, decimal_places=2)   # subtotal − platform_fee

    # ── Shipping ───────────────────────────────────────────────────────────────
    # shipping_address is stored as a JSON snapshot at checkout time:
    # { first_name, last_name, address, city, state, phone }
    shipping_address        = models.JSONField(default=dict)
    payment_method          = models.CharField(max_length=50, default='mpesa')
    carrier                 = models.CharField(max_length=100, blank=True)
    tracking_number         = models.CharField(max_length=200, blank=True)
    estimated_delivery_date = models.DateField(null=True, blank=True)
    delivery_time_window    = models.CharField(max_length=100, blank=True)

    # ── State ──────────────────────────────────────────────────────────────────
    status     = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Escrow {self.id} — {self.product_title}"


class Notification(models.Model):
    """
    Exactly ONE of recipient_user / recipient_shop is non-null:
      recipient_user  → personal account feed   (no ?as_shop)
      recipient_shop  → shop feed               (?as_shop=<id>)

    Routing:
      order_placed      → seller_shop (new sale)
                          buyer personal OR buyer_shop (purchase confirmed)
      shipped           → buyer personal OR buyer_shop
      receipt_confirmed → seller_shop
      funds_released    → seller_shop
      dispute_opened    → seller_shop + buyer personal OR buyer_shop
      refunded          → buyer personal OR buyer_shop
    """
    KIND_ORDER_PLACED      = 'order_placed'
    KIND_SHIPPED           = 'shipped'
    KIND_RECEIPT_CONFIRMED = 'receipt_confirmed'
    KIND_FUNDS_RELEASED    = 'funds_released'
    KIND_DISPUTE_OPENED    = 'dispute_opened'
    KIND_REFUNDED          = 'refunded'

    KIND_CHOICES = [
        (KIND_ORDER_PLACED,      'Order Placed'),
        (KIND_SHIPPED,           'Shipped'),
        (KIND_RECEIPT_CONFIRMED, 'Receipt Confirmed'),
        (KIND_FUNDS_RELEASED,    'Funds Released'),
        (KIND_DISPUTE_OPENED,    'Dispute Opened'),
        (KIND_REFUNDED,          'Refunded'),
    ]

    recipient_user = models.ForeignKey(
        User, on_delete=models.CASCADE,
        null=True, blank=True, related_name='notifications'
    )
    recipient_shop = models.ForeignKey(
        'shop.Shop', on_delete=models.CASCADE,
        null=True, blank=True, related_name='notifications'
    )

    transaction = models.ForeignKey(
        EscrowTransaction, on_delete=models.CASCADE, related_name='notifications'
    )
    kind       = models.CharField(max_length=30, choices=KIND_CHOICES)
    title      = models.CharField(max_length=255)
    message    = models.TextField()
    is_read    = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        target = self.recipient_shop or self.recipient_user
        return f"[{self.kind}] → {target}"