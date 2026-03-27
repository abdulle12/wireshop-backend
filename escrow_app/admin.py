# escrow_app/admin.py
"""
Marketplace admin for managing escalated disputes.

Access at: /admin/escrow_app/issue/
Filter by stage=escalated to see all disputes needing resolution.

Actions available:
  - force_release : Release funds to seller (settlement in seller's favour)
  - force_refund  : Refund buyer (settlement in buyer's favour)

Both actions:
  - Post a marketplace message in the issue thread
  - Set issue.stage = 'resolved'
  - Set tx.status = 'released' (release) or 'refunded' (refund)
  - Notify both parties
"""

from django.contrib import admin
from django.utils.html import format_html, mark_safe
from django.utils.safestring import mark_safe
from django.db import models as db_models
from .models import EscrowTransaction, Notification, Issue, IssueMessage


# ── Inline: show messages inside Issue detail page ───────────────────────────
class IssueMessageInline(admin.TabularInline):
    model        = IssueMessage
    extra        = 0
    readonly_fields = ('sender_role', 'sender', 'text', 'created_at')
    can_delete   = False
    ordering     = ('created_at',)
    max_num      = 0   # no adding new messages via inline — use the action instead

    def has_add_permission(self, request, obj=None):
        return False


# ── Helpers ───────────────────────────────────────────────────────────────────
def _safe_name(user):
    if not user: return '—'
    full = (getattr(user, 'full_name', '') or '').strip()
    if full: return full
    joined = ' '.join(p for p in [user.first_name, user.last_name] if p)
    if joined: return joined
    return (user.email or '').split('@')[0]


def _notify_both(tx, kind, title, message):
    """Send notification to both buyer and seller."""
    kwargs = {'transaction': tx, 'kind': kind, 'title': title, 'message': message}
    if tx.buyer_shop:
        Notification.objects.create(recipient_shop=tx.buyer_shop, **kwargs)
    else:
        Notification.objects.create(recipient_user=tx.buyer, **kwargs)
    if tx.seller_shop:
        Notification.objects.create(recipient_shop=tx.seller_shop, **kwargs)
    else:
        Notification.objects.create(recipient_user=tx.seller, **kwargs)


# ── Custom admin actions ──────────────────────────────────────────────────────
@admin.action(description='✅ Force Release — release funds to seller (seller wins)')
def force_release(modeladmin, request, queryset):
    """
    Marketplace resolves in seller's favour:
    - tx.status → released
    - issue.stage → resolved
    - buy_count++
    - Notify both parties
    - Post marketplace message in thread
    """
    from shop.models import Product
    resolved = 0
    skipped  = 0

    for issue in queryset.select_related(
        'transaction', 'transaction__buyer', 'transaction__seller',
        'transaction__buyer_shop', 'transaction__seller_shop', 'transaction__product'
    ):
        if issue.stage != Issue.STAGE_ESCALATED:
            skipped += 1
            continue

        tx = issue.transaction

        # Release funds
        tx.status = EscrowTransaction.STATUS_RELEASED
        tx.save(update_fields=['status'])

        # buy_count
        if tx.product_id:
            Product.objects.filter(pk=tx.product_id).update(
                buy_count=db_models.F('buy_count') + 1
            )

        # Close issue
        issue.stage = Issue.STAGE_RESOLVED
        issue.save(update_fields=['stage'])

        # Marketplace message in thread
        IssueMessage.objects.create(
            issue=issue,
            sender=None,
            sender_role=IssueMessage.ROLE_MARKET,
            text=(
                f'After reviewing this dispute, the Wireshops Marketplace team has '
                f'decided to release the escrow funds of KES {tx.seller_payout} to the seller. '
                f'This case is now closed. Thank you for your patience.'
            ),
        )

        # Notify both
        buyer_lbl  = (tx.buyer_shop.shop_name if tx.buyer_shop else _safe_name(tx.buyer))
        seller_lbl = (tx.seller_shop.shop_name if tx.seller_shop else _safe_name(tx.seller))

        _notify_both(
            tx,
            kind    = Notification.KIND_ISSUE_RESOLVED,
            title   = f'Dispute resolved: "{tx.product_title}"',
            message = (
                f'The marketplace has reviewed the dispute between {buyer_lbl} and {seller_lbl}. '
                f'Decision: funds (KES {tx.seller_payout}) released to the seller.'
            ),
        )
        resolved += 1

    modeladmin.message_user(
        request,
        f'{resolved} dispute(s) resolved in favour of seller. {skipped} skipped (not escalated).'
    )


@admin.action(description='💸 Force Refund — refund buyer (buyer wins)')
def force_refund(modeladmin, request, queryset):
    """
    Marketplace resolves in buyer's favour:
    - tx.status → refunded
    - issue.stage → resolved
    - Notify both parties
    - Post marketplace message in thread
    """
    resolved = 0
    skipped  = 0

    for issue in queryset.select_related(
        'transaction', 'transaction__buyer', 'transaction__seller',
        'transaction__buyer_shop', 'transaction__seller_shop',
    ):
        if issue.stage != Issue.STAGE_ESCALATED:
            skipped += 1
            continue

        tx = issue.transaction

        # Refund
        tx.status = EscrowTransaction.STATUS_REFUNDED
        tx.save(update_fields=['status'])

        # Close issue
        issue.stage = Issue.STAGE_RESOLVED
        issue.save(update_fields=['stage'])

        # Marketplace message
        IssueMessage.objects.create(
            issue=issue,
            sender=None,
            sender_role=IssueMessage.ROLE_MARKET,
            text=(
                f'After reviewing this dispute, the Wireshops Marketplace team has '
                f'decided to refund the buyer KES {tx.subtotal}. '
                f'The seller will not receive payment for this transaction. '
                f'This case is now closed. Thank you for your patience.'
            ),
        )

        buyer_lbl  = (tx.buyer_shop.shop_name if tx.buyer_shop else _safe_name(tx.buyer))
        seller_lbl = (tx.seller_shop.shop_name if tx.seller_shop else _safe_name(tx.seller))

        _notify_both(
            tx,
            kind    = Notification.KIND_ISSUE_RESOLVED,
            title   = f'Dispute resolved: "{tx.product_title}"',
            message = (
                f'The marketplace has reviewed the dispute between {buyer_lbl} and {seller_lbl}. '
                f'Decision: buyer refunded KES {tx.subtotal}. Seller will not receive payment.'
            ),
        )
        resolved += 1

    modeladmin.message_user(
        request,
        f'{resolved} dispute(s) resolved in favour of buyer (refunded). {skipped} skipped (not escalated).'
    )


@admin.action(description='💬 Post marketplace message to selected issues')
def post_marketplace_message(modeladmin, request, queryset):
    """
    Placeholder — opens a form to type a message.
    For simplicity, posts a standard "under review" message.
    Replace with a custom intermediate page for free-text if needed.
    """
    for issue in queryset:
        if issue.stage != Issue.STAGE_ESCALATED:
            continue
        IssueMessage.objects.create(
            issue=issue,
            sender=None,
            sender_role=IssueMessage.ROLE_MARKET,
            text=(
                'This dispute is under active review by the Wireshops Marketplace team. '
                'We will contact both parties with our decision within 24 hours. '
                'Thank you for your patience.'
            ),
        )
    modeladmin.message_user(request, f'Message posted to {queryset.count()} issue(s).')


# ── Issue admin ───────────────────────────────────────────────────────────────
@admin.register(Issue)
class IssueAdmin(admin.ModelAdmin):
    list_display  = (
        'id', 'stage_badge', 'product_title', 'issue_type',
        'buyer_display', 'seller_display',
        'amount_held', 'created_at',
    )
    list_filter   = ('stage', 'created_at')
    search_fields = (
        'transaction__product_title',
        'transaction__buyer__email', 'transaction__seller__email',
        'issue_type',
    )
    ordering      = ('-created_at',)
    readonly_fields = (
        'stage', 'issue_type', 'created_at', 'updated_at',
        'transaction_detail', 'message_thread',
    )
    fieldsets = (
        ('Issue', {
            'fields': ('stage', 'issue_type', 'created_at', 'updated_at'),
        }),
        ('Transaction', {
            'fields': ('transaction_detail',),
        }),
        ('Message Thread', {
            'fields': ('message_thread',),
            'classes': ('wide',),
        }),
    )
    actions = [force_release, force_refund, post_marketplace_message]

    # ── List display helpers ──────────────────────────────────────────────────
    @admin.display(description='Stage')
    def stage_badge(self, obj):
        colours = {
            'open':            '#f59e0b',
            'replied':         '#3b82f6',
            'seller_resolved': '#f97316',
            'resolved':        '#22c55e',
            'escalated':       '#ef4444',
        }
        colour = colours.get(obj.stage, '#6b7280')
        return format_html(
            '<span style="background:{};color:white;padding:2px 8px;border-radius:12px;font-size:11px;font-weight:600">{}</span>',
            colour, obj.get_stage_display()
        )

    @admin.display(description='Product')
    def product_title(self, obj):
        return obj.transaction.product_title

    @admin.display(description='Buyer')
    def buyer_display(self, obj):
        tx = obj.transaction
        if tx.buyer_shop:
            return f'{tx.buyer_shop.shop_name} (shop)'
        return _safe_name(tx.buyer)

    @admin.display(description='Seller')
    def seller_display(self, obj):
        tx = obj.transaction
        if tx.seller_shop:
            return f'{tx.seller_shop.shop_name} (shop)'
        return _safe_name(tx.seller)

    @admin.display(description='Held (KES)')
    def amount_held(self, obj):
        return f'KES {obj.transaction.subtotal}'

    # ── Detail page helpers ───────────────────────────────────────────────────
    @admin.display(description='Transaction Details')
    def transaction_detail(self, obj):
        tx = obj.transaction
        addr = tx.shipping_address or {}
        buyer_lbl  = (tx.buyer_shop.shop_name + ' (shop)') if tx.buyer_shop else _safe_name(tx.buyer)
        seller_lbl = (tx.seller_shop.shop_name + ' (shop)') if tx.seller_shop else _safe_name(tx.seller)
        return format_html(
            '''
            <table style="border-collapse:collapse;width:100%;font-size:13px">
              <tr><td style="padding:6px 12px;font-weight:600;color:#374151;width:160px">Transaction ID</td>
                  <td style="padding:6px 12px;color:#6b7280;font-family:monospace">{}</td></tr>
              <tr style="background:#f9fafb"><td style="padding:6px 12px;font-weight:600;color:#374151">Status</td>
                  <td style="padding:6px 12px"><b style="color:#dc2626">{}</b></td></tr>
              <tr><td style="padding:6px 12px;font-weight:600;color:#374151">Product</td>
                  <td style="padding:6px 12px">{}</td></tr>
              <tr style="background:#f9fafb"><td style="padding:6px 12px;font-weight:600;color:#374151">Buyer</td>
                  <td style="padding:6px 12px">{}</td></tr>
              <tr><td style="padding:6px 12px;font-weight:600;color:#374151">Seller</td>
                  <td style="padding:6px 12px">{}</td></tr>
              <tr style="background:#f9fafb"><td style="padding:6px 12px;font-weight:600;color:#374151">Subtotal</td>
                  <td style="padding:6px 12px">KES {}</td></tr>
              <tr><td style="padding:6px 12px;font-weight:600;color:#374151">Seller Payout</td>
                  <td style="padding:6px 12px">KES {} <small style="color:#9ca3af">(after 4.99% fee)</small></td></tr>
              <tr style="background:#f9fafb"><td style="padding:6px 12px;font-weight:600;color:#374151">Shipping Address</td>
                  <td style="padding:6px 12px">{}</td></tr>
              <tr><td style="padding:6px 12px;font-weight:600;color:#374151">Payment Method</td>
                  <td style="padding:6px 12px">{}</td></tr>
              <tr style="background:#f9fafb"><td style="padding:6px 12px;font-weight:600;color:#374151">Carrier / Tracking</td>
                  <td style="padding:6px 12px">{} / {}</td></tr>
            </table>
            ''',
            tx.id,
            tx.status.upper(),
            tx.product_title,
            buyer_lbl,
            seller_lbl,
            tx.subtotal,
            tx.seller_payout,
            ', '.join(filter(None, [addr.get('address'), addr.get('city'), addr.get('state')])) or '—',
            tx.payment_method,
            tx.carrier or '—',
            tx.tracking_number or '—',
        )

    @admin.display(description='Full Message Thread')
    def message_thread(self, obj):
        messages = obj.messages.all().order_by('created_at')
        if not messages:
            return 'No messages yet.'

        role_colours = {
            'buyer':       ('#dbeafe', '#1e40af'),   # blue
            'seller':      ('#dcfce7', '#15803d'),   # green
            'marketplace': ('#f3f4f6', '#374151'),   # gray
        }

        rows = []
        for m in messages:
            bg, fg = role_colours.get(m.sender_role, ('#f9fafb', '#111827'))
            sender_display = {
                'buyer':       (obj.transaction.buyer_shop.shop_name if obj.transaction.buyer_shop
                                else _safe_name(obj.transaction.buyer)),
                'seller':      (obj.transaction.seller_shop.shop_name if obj.transaction.seller_shop
                                else _safe_name(obj.transaction.seller)),
                'marketplace': 'Wireshops Support',
            }.get(m.sender_role, 'Unknown')

            rows.append(format_html(
                '''
                <div style="margin-bottom:12px;padding:12px 16px;background:{};border-radius:8px;border-left:4px solid {}">
                  <div style="display:flex;justify-content:space-between;margin-bottom:4px">
                    <span style="font-weight:700;color:{};font-size:12px">{} <small style="font-weight:400;opacity:.7">({})</small></span>
                    <span style="font-size:11px;color:#9ca3af">{}</span>
                  </div>
                  <p style="margin:0;font-size:13px;color:#1f2937;line-height:1.5">{}</p>
                </div>
                ''',
                bg, fg, fg,
                sender_display, m.sender_role,
                m.created_at.strftime('%b %d, %Y %H:%M'),
                m.text,
            ))

        return mark_safe(''.join(r for r in rows))

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'transaction', 'transaction__buyer', 'transaction__seller',
            'transaction__buyer_shop', 'transaction__seller_shop',
        ).prefetch_related('messages__sender')


# ── EscrowTransaction admin — lightweight view for context ───────────────────
@admin.register(EscrowTransaction)
class EscrowTransactionAdmin(admin.ModelAdmin):
    list_display  = ('id', 'product_title', 'status', 'subtotal', 'buyer_display', 'seller_display', 'created_at')
    list_filter   = ('status', 'payment_method', 'created_at')
    search_fields = ('product_title', 'buyer__email', 'seller__email', 'tracking_number')
    readonly_fields = [f.name for f in EscrowTransaction._meta.fields]
    ordering      = ('-created_at',)

    @admin.display(description='Buyer')
    def buyer_display(self, obj):
        if obj.buyer_shop: return f'{obj.buyer_shop.shop_name} (shop)'
        return _safe_name(obj.buyer)

    @admin.display(description='Seller')
    def seller_display(self, obj):
        if obj.seller_shop: return f'{obj.seller_shop.shop_name} (shop)'
        return _safe_name(obj.seller)