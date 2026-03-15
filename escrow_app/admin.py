from django.contrib import admin
from .models import EscrowTransaction, Notification


@admin.register(EscrowTransaction)
class EscrowTransactionAdmin(admin.ModelAdmin):

    # ── List view ─────────────────────────────────────────────────────────────
    list_display  = [
        'id', 'status', 'product_title',
        'total_amount',          # was total_charged  ← FIXED
        'buyer_display', 'seller_display',
        'created_at',
    ]
    list_filter   = ['status', 'payment_method', 'created_at']
    search_fields = [
        'product_title',
        'buyer__email', 'seller__email',
        'buyer_shop__shop_name', 'seller_shop__shop_name',
        'tracking_number',
    ]
    ordering = ['-created_at']

    # ── Detail view ───────────────────────────────────────────────────────────
    readonly_fields = [
        'id',
        'platform_fee',          # was platform_cut  ← FIXED
        'total_amount',          # was total_charged  ← FIXED
        'seller_payout',
        # held_at / shipped_at / delivered_at / released_at do NOT exist
        # on the new model — removed  ← FIXED
        'created_at', 'updated_at',
        'buyer_display', 'seller_display',
    ]

    fieldsets = (
        ('Transaction', {
            'fields': ('id', 'status', 'created_at', 'updated_at'),
        }),
        ('Parties', {
            'fields': (
                'buyer', 'buyer_shop',
                'seller', 'seller_shop',
                'buyer_display', 'seller_display',
            ),
        }),
        ('Product', {
            'fields': ('product', 'product_title', 'quantity', 'unit_price'),
        }),
        ('Money', {
            'fields': ('subtotal', 'platform_fee', 'total_amount', 'seller_payout'),
        }),
        ('Shipping & Payment', {
            'fields': (
                'shipping_address', 'payment_method',
                'carrier', 'tracking_number',
                'estimated_delivery_date', 'delivery_time_window',
            ),
        }),
    )

    # ── Helpers ───────────────────────────────────────────────────────────────
    @admin.display(description='Buyer')
    def buyer_display(self, obj):
        if obj.buyer_shop:
            return f'{obj.buyer_shop.shop_name} (shop)'
        return obj.buyer.get_full_name() or obj.buyer.email

    @admin.display(description='Seller')
    def seller_display(self, obj):
        if obj.seller_shop:
            return f'{obj.seller_shop.shop_name} (shop)'
        return obj.seller.get_full_name() or obj.seller.email


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):

    # ── List view ─────────────────────────────────────────────────────────────
    list_display = [
        'id', 'kind',
        'recipient_display',     # was 'recipient'  ← FIXED (not a model field)
        'title', 'is_read', 'created_at',
    ]
    list_filter   = ['kind', 'is_read', 'created_at']
    search_fields = [
        'title', 'message',
        'recipient_user__email',
        'recipient_shop__shop_name',
    ]
    ordering      = ['-created_at']

    readonly_fields = [
        'kind', 'title', 'message',
        'recipient_display',
        'transaction', 'created_at',
    ]

    fieldsets = (
        ('Notification', {
            'fields': ('kind', 'title', 'message', 'is_read', 'created_at'),
        }),
        ('Recipient', {
            'description': 'Exactly one of recipient_user / recipient_shop is set.',
            'fields': ('recipient_user', 'recipient_shop', 'recipient_display'),
        }),
        ('Transaction', {
            'fields': ('transaction',),
        }),
    )

    # ── Helper ────────────────────────────────────────────────────────────────
    @admin.display(description='Recipient')
    def recipient_display(self, obj):
        if obj.recipient_shop:
            return f'Shop: {obj.recipient_shop.shop_name}'
        if obj.recipient_user:
            return f'User: {obj.recipient_user.get_full_name() or obj.recipient_user.email}'
        return '—'