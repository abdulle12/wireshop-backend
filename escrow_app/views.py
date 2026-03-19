from decimal import Decimal
from django.db import models
from django.shortcuts import get_object_or_404
from django.contrib.auth import get_user_model
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from shop.models import Shop, Product
from .models import EscrowTransaction, Notification
from .serializers import (
    EscrowTransactionSerializer,
    NotificationSerializer,
    CheckoutSerializer,
    ShipOrderSerializer,
)

User = get_user_model()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_as_shop(request):
    """Return Shop if as_shop param is provided AND owned by request.user."""
    shop_id = request.query_params.get('as_shop') or request.data.get('as_shop')
    if not shop_id:
        return None
    try:
        return Shop.objects.get(pk=shop_id, owner=request.user)
    except Shop.DoesNotExist:
        return None


def _notify(transaction, kind, title, message, *, recipient_user=None, recipient_shop=None):
    """Create a Notification. Exactly one of recipient_user/recipient_shop must be given."""
    if not recipient_user and not recipient_shop:
        return
    Notification.objects.create(
        transaction    = transaction,
        kind           = kind,
        title          = title,
        message        = message,
        recipient_user = recipient_user,
        recipient_shop = recipient_shop,
    )


def _safe_name(user):
    """
    Build display name — same priority as frontend getUserDisplayName():
      1. full_name (custom field set at signup)
      2. first_name + last_name
      3. email prefix — never raw email address
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


def _buyer_label(tx):
    if tx.buyer_shop:
        return tx.buyer_shop.shop_name
    return _safe_name(tx.buyer)


def _seller_label(tx):
    if tx.seller_shop:
        return tx.seller_shop.shop_name
    return _safe_name(tx.seller)


# ── Escrow lifecycle ───────────────────────────────────────────────────────────

class CheckoutView(APIView):
    """
    POST /api/escrow/checkout/

    Buyer purchases a product. Money is held in escrow (STATUS_HELD).
    Notifications:
      → seller_shop:          "New Order" — <buyer> bought <product>
      → buyer personal/shop:  "Purchase Confirmed"
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        ser = CheckoutSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        buyer_shop = _get_as_shop(request)

        product = get_object_or_404(Product, pk=d['product_id'])
        if product.shop.owner == request.user:
            return Response({'detail': 'Cannot buy your own product.'}, status=400)

        seller      = product.shop.owner
        seller_shop = product.shop
        qty         = d['quantity']
        unit_price  = product.price
        subtotal    = unit_price * qty
        fee         = (subtotal * EscrowTransaction.PLATFORM_FEE_RATE).quantize(Decimal('0.01'))
        payout      = subtotal - fee

        tx = EscrowTransaction.objects.create(
            buyer            = request.user,
            buyer_shop       = buyer_shop,
            seller           = seller,
            seller_shop      = seller_shop,
            product          = product,
            product_title    = product.title,
            quantity         = qty,
            unit_price       = unit_price,
            subtotal         = subtotal,
            platform_fee     = fee,
            total_amount     = subtotal,
            seller_payout    = payout,
            shipping_address = d['shipping_address'],
            payment_method   = d.get('payment_method', 'mpesa'),
            status           = EscrowTransaction.STATUS_HELD,
        )

        buyer_lbl = buyer_shop.shop_name if buyer_shop else _safe_name(request.user)

        # Notify seller's shop — new order arrived
        _notify(
            tx, Notification.KIND_ORDER_PLACED,
            title   = f'New Order Received 🛒',
            message = f"{buyer_lbl} bought {product.title} ×{qty}. Escrow held: KES {subtotal}.",
            recipient_shop = seller_shop,
        )

        # ✅ NO buyer notification at checkout.
        # The buyer only gets notified when the seller ships (KIND_SHIPPED).
        # Sending a receipt_confirmed here caused buyers to see a broken
        # DeliveryConfirmation page (no shipping info yet) and confused the flow.

        return Response(EscrowTransactionSerializer(tx, context={'request': request}).data, status=201)


class IncomingOrdersView(APIView):
    """GET /api/escrow/incoming/?as_shop=<id> — orders the seller received."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        as_shop = _get_as_shop(request)
        if as_shop:
            qs = EscrowTransaction.objects.filter(seller_shop=as_shop)
        else:
            qs = EscrowTransaction.objects.filter(seller=request.user)
        return Response(EscrowTransactionSerializer(qs, many=True, context={'request': request}).data)


class ShipOrderView(APIView):
    """
    POST /api/escrow/<pk>/ship/

    Seller fills shipping info → STATUS_SHIPPED.
    Notification → buyer personal or buyer_shop: "Your order has shipped"
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        tx = get_object_or_404(EscrowTransaction, pk=pk, seller=request.user)
        if tx.status != EscrowTransaction.STATUS_HELD:
            return Response({'detail': 'Order cannot be shipped in its current state.'}, status=400)

        ser = ShipOrderSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        tx.carrier                  = d['carrier']
        tx.tracking_number          = d['tracking_number']
        tx.estimated_delivery_date  = d.get('delivery_date')
        tx.delivery_time_window     = d.get('time_window', '')
        tx.status                   = EscrowTransaction.STATUS_SHIPPED
        tx.save()

        seller_lbl = _seller_label(tx)

        # Notify buyer wherever they placed the order
        if tx.buyer_shop:
            _notify(
                tx, Notification.KIND_SHIPPED,
                title   = 'Your Order Has Shipped 📦',
                message = f"{seller_lbl} has shipped your order of {tx.product_title}. Carrier: {tx.carrier}. Tracking: {tx.tracking_number}.",
                recipient_shop = tx.buyer_shop,
            )
        else:
            _notify(
                tx, Notification.KIND_SHIPPED,
                title   = 'Your Order Has Shipped 📦',
                message = f"{seller_lbl} has shipped your order of {tx.product_title}. Carrier: {tx.carrier}. Tracking: {tx.tracking_number}.",
                recipient_user = tx.buyer,
            )

        return Response(EscrowTransactionSerializer(tx, context={'request': request}).data)


class DeliveryInfoView(APIView):
    """GET /api/escrow/<pk>/delivery-info/ — buyer or seller can view."""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        tx = get_object_or_404(EscrowTransaction, pk=pk)
        if tx.buyer != request.user and tx.seller != request.user:
            return Response({'detail': 'Forbidden.'}, status=403)
        return Response(EscrowTransactionSerializer(tx, context={'request': request}).data)


class ConfirmReceiptView(APIView):
    """
    POST /api/escrow/<pk>/confirm-receipt/

    Buyer confirms delivery → STATUS_RELEASED → funds go to seller.
    Notifications:
      → seller_shop:         "Funds Released"
      → buyer personal/shop: "Receipt Confirmed"
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        tx = get_object_or_404(EscrowTransaction, pk=pk, buyer=request.user)
        if tx.status != EscrowTransaction.STATUS_SHIPPED:
            return Response({'detail': 'Order has not been marked as shipped yet.'}, status=400)

        tx.status = EscrowTransaction.STATUS_RELEASED
        tx.save()

        # ── Increment the product's buy counter (if the product still exists) ──
        if tx.product_id:
            Product.objects.filter(pk=tx.product_id).update(
                buy_count=models.F('buy_count') + 1
            )

        buyer_lbl  = _buyer_label(tx)

        # Notify seller — buyer confirmed receipt, funds released
        # Kind = KIND_RECEIPT_CONFIRMED so seller sees "buyer confirmed receipt of item"
        if tx.seller_shop:
            _notify(
                tx, Notification.KIND_RECEIPT_CONFIRMED,
                title   = f'{buyer_lbl} confirmed receipt 💰',
                message = f"{buyer_lbl} confirmed receipt of {tx.product_title}. KES {tx.seller_payout} has been released to your account.",
                recipient_shop = tx.seller_shop,
            )
        else:
            _notify(
                tx, Notification.KIND_RECEIPT_CONFIRMED,
                title   = f'{buyer_lbl} confirmed receipt 💰',
                message = f"{buyer_lbl} confirmed receipt of {tx.product_title}. KES {tx.seller_payout} has been released.",
                recipient_user = tx.seller,
            )

        # ✅ NO notification back to the buyer.
        # The buyer just confirmed — they don't need a notification about their own action.

        return Response({
            'status':        'released',
            'seller_payout': str(tx.seller_payout),
            'platform_cut':  str(tx.platform_fee),
        })


class DisputeOrderView(APIView):
    """
    POST /api/escrow/<pk>/dispute/

    Buyer raises dispute → STATUS_DISPUTED → funds frozen.
    Notifications → seller_shop + buyer personal/shop.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        tx = get_object_or_404(EscrowTransaction, pk=pk, buyer=request.user)
        if tx.status not in (EscrowTransaction.STATUS_SHIPPED, EscrowTransaction.STATUS_RELEASED, EscrowTransaction.STATUS_DISPUTED):
            return Response({'detail': 'Cannot dispute in current state.'}, status=400)

        tx.status = EscrowTransaction.STATUS_DISPUTED
        tx.save()

        buyer_lbl = _buyer_label(tx)

        # Notify seller
        if tx.seller_shop:
            _notify(
                tx, Notification.KIND_DISPUTE_OPENED,
                title   = 'Dispute Opened ⚠️',
                message = f"{buyer_lbl} raised a dispute for {tx.product_title}. Funds are frozen pending review.",
                recipient_shop = tx.seller_shop,
            )
        else:
            _notify(
                tx, Notification.KIND_DISPUTE_OPENED,
                title   = 'Dispute Opened ⚠️',
                message = f"{buyer_lbl} raised a dispute for {tx.product_title}.",
                recipient_user = tx.seller,
            )

        # ✅ NO confirmation back to the buyer.
        # The buyer opened the dispute themselves — no need for a self-notification.

        return Response({'status': 'disputed'})


# ── Notification views ─────────────────────────────────────────────────────────

class NotificationListView(APIView):
    """
    GET /api/notifications/
    GET /api/notifications/?as_shop=<id>
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        as_shop = _get_as_shop(request)
        if as_shop:
            qs = Notification.objects.filter(recipient_shop=as_shop).select_related('transaction')
        else:
            qs = Notification.objects.filter(recipient_user=request.user).select_related('transaction')
        return Response(NotificationSerializer(qs, many=True, context={'request': request}).data)


class NotificationUnreadCountView(APIView):
    """
    GET /api/notifications/unread-count/
    GET /api/notifications/unread-count/?as_shop=<id>
    Returns { "count": N }
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        as_shop = _get_as_shop(request)
        if as_shop:
            count = Notification.objects.filter(recipient_shop=as_shop, is_read=False).count()
        else:
            count = Notification.objects.filter(recipient_user=request.user, is_read=False).count()
        return Response({'count': count})


class NotificationReadView(APIView):
    """PATCH /api/notifications/<pk>/read/ — toggle read/unread"""
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        as_shop = _get_as_shop(request)
        if as_shop:
            notif = get_object_or_404(Notification, pk=pk, recipient_shop=as_shop)
        else:
            notif = get_object_or_404(Notification, pk=pk, recipient_user=request.user)
        notif.is_read = not notif.is_read
        notif.save(update_fields=['is_read'])
        return Response(NotificationSerializer(notif, context={'request': request}).data)


class NotificationMarkAllReadView(APIView):
    """PATCH /api/notifications/read-all/"""
    permission_classes = [IsAuthenticated]

    def patch(self, request):
        as_shop = _get_as_shop(request)
        if as_shop:
            Notification.objects.filter(recipient_shop=as_shop, is_read=False).update(is_read=True)
        else:
            Notification.objects.filter(recipient_user=request.user, is_read=False).update(is_read=True)
        return Response({'status': 'ok'})


class NotificationDeleteView(APIView):
    """DELETE /api/notifications/<pk>/"""
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        as_shop = _get_as_shop(request)
        if as_shop:
            notif = get_object_or_404(Notification, pk=pk, recipient_shop=as_shop)
        else:
            notif = get_object_or_404(Notification, pk=pk, recipient_user=request.user)
        notif.delete()
        return Response(status=204)


class BuyerOrdersView(APIView):
    """
    GET /api/escrow/my-orders/?status=held|shipped|released&as_shop=<id>

    Returns the buyer's own purchase history filtered by status group:
      held     → STATUS_HELD      (paid, waiting for seller to ship)
      shipped  → STATUS_SHIPPED   (seller shipped, buyer hasn't confirmed yet)
      released → STATUS_RELEASED  (buyer confirmed receipt — completed)

    Each transaction includes has_review: true/false so the frontend
    can show "Write Review" vs "Reviewed" on the received list.
    """
    permission_classes = [IsAuthenticated]

    STATUS_MAP = {
        'held':     [EscrowTransaction.STATUS_HELD],
        'shipped':  [EscrowTransaction.STATUS_SHIPPED],
        'released': [EscrowTransaction.STATUS_RELEASED],
    }

    def get(self, request):
        as_shop    = _get_as_shop(request)
        status_key = request.query_params.get('status', 'held')
        statuses   = self.STATUS_MAP.get(status_key, [EscrowTransaction.STATUS_HELD])

        if as_shop:
            qs = EscrowTransaction.objects.filter(
                buyer_shop=as_shop,
                status__in=statuses,
            )
        else:
            qs = EscrowTransaction.objects.filter(
                buyer=request.user,
                status__in=statuses,
            )

        qs = qs.select_related(
            'product', 'seller_shop', 'seller', 'buyer_shop'
        ).order_by('-created_at')

        serializer = EscrowTransactionSerializer(qs, many=True, context={'request': request})
        data = serializer.data

        # Annotate each tx with has_review so frontend can show correct CTA
        tx_ids = [tx.id for tx in qs]
        reviewed_ids = set(
            EscrowTransaction.objects.filter(
                id__in=tx_ids,
                product_review__isnull=False,
            ).values_list('id', flat=True)
        )

        for item, tx in zip(data, qs):
            item['has_review'] = str(tx.id) in {str(i) for i in reviewed_ids}

        return Response(data)


class BuyerOrderCountsView(APIView):
    """
    GET /api/escrow/my-order-counts/?as_shop=<id>

    Returns { held: N, shipped: N, released: N }
    Used by the Navbar sidebar to show live counts.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        as_shop = _get_as_shop(request)

        if as_shop:
            base_qs = EscrowTransaction.objects.filter(buyer_shop=as_shop)
        else:
            base_qs = EscrowTransaction.objects.filter(buyer=request.user)

        return Response({
            'held':     base_qs.filter(status=EscrowTransaction.STATUS_HELD).count(),
            'shipped':  base_qs.filter(status=EscrowTransaction.STATUS_SHIPPED).count(),
            'released': base_qs.filter(status=EscrowTransaction.STATUS_RELEASED).count(),
        })


class ProductOrdersView(APIView):
    """
    GET /api/escrow/product/<product_id>/orders/?status=held|shipped|released

    Returns all orders for a specific product where the requesting user is
    the seller. Used by the shop owner to see per-product customer lists.

    Includes seller_payout on each transaction so the paid list can total up.
    """
    permission_classes = [IsAuthenticated]

    STATUS_MAP = {
        'held':     [EscrowTransaction.STATUS_HELD],
        'shipped':  [EscrowTransaction.STATUS_SHIPPED],
        'released': [EscrowTransaction.STATUS_RELEASED],
    }

    def get(self, request, product_id):
        status_key = request.query_params.get('status', 'held')
        statuses   = self.STATUS_MAP.get(status_key, [EscrowTransaction.STATUS_HELD])

        qs = EscrowTransaction.objects.filter(
            seller=request.user,
            product_id=product_id,
            status__in=statuses,
        ).select_related(
            'buyer', 'buyer_shop'
        ).order_by('-created_at')

        return Response(EscrowTransactionSerializer(qs, many=True, context={'request': request}).data)


class ProductOrderCountsView(APIView):
    """
    GET /api/escrow/product/<product_id>/order-counts/

    Returns { held: N, shipped: N, released: N } for a specific product.
    Used by the shop owner's product cards to show live counts on buttons.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, product_id):
        base = EscrowTransaction.objects.filter(
            seller=request.user,
            product_id=product_id,
        )
        return Response({
            'held':     base.filter(status=EscrowTransaction.STATUS_HELD).count(),
            'shipped':  base.filter(status=EscrowTransaction.STATUS_SHIPPED).count(),
            'released': base.filter(status=EscrowTransaction.STATUS_RELEASED).count(),
        })


# ══════════════════════════════════════════════════════════════════════════════
# ISSUE / SUPPORT SYSTEM
# ══════════════════════════════════════════════════════════════════════════════

def _issue_buyer_check(issue, request):
    """Return True if request.user is the buyer on this issue's transaction."""
    tx = issue.transaction
    return tx.buyer == request.user


def _issue_seller_check(issue, request):
    """Return True if request.user is the seller on this issue's transaction."""
    tx = issue.transaction
    return tx.seller == request.user


class ReportIssueView(APIView):
    """
    POST /api/escrow/<uuid:pk>/report-issue/

    Buyer creates an Issue + first message against a SHIPPED or RELEASED transaction.
    Creates Issue with stage='open', freezes funds (STATUS_DISPUTED),
    and notifies the seller.

    Body: { issue_type, message, as_shop? }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        from .models import EscrowTransaction, Issue, IssueMessage, Notification

        try:
            tx = EscrowTransaction.objects.get(pk=pk, buyer=request.user)
        except EscrowTransaction.DoesNotExist:
            return Response({'detail': 'Transaction not found.'}, status=404)

        allowed = [EscrowTransaction.STATUS_SHIPPED, EscrowTransaction.STATUS_RELEASED]
        if tx.status not in allowed:
            return Response({'detail': 'Can only report an issue on shipped or released orders.'}, status=400)

        if hasattr(tx, 'issue'):
            return Response({'detail': 'An issue has already been reported for this order.'}, status=400)

        issue_type = request.data.get('issue_type', '').strip()
        message    = request.data.get('message', '').strip()

        if not issue_type:
            return Response({'detail': 'issue_type is required.'}, status=400)
        if not message:
            return Response({'detail': 'message is required.'}, status=400)

        # Freeze funds
        tx.status = EscrowTransaction.STATUS_DISPUTED
        tx.save(update_fields=['status'])

        issue = Issue.objects.create(
            transaction=tx,
            issue_type=issue_type,
            stage=Issue.STAGE_OPEN,
        )

        IssueMessage.objects.create(
            issue=issue,
            sender=request.user,
            sender_role=IssueMessage.ROLE_BUYER,
            text=message,
        )

        # Notify seller
        buyer_lbl = tx.buyer_shop.shop_name if tx.buyer_shop else _safe_name(tx.buyer)
        notif_data = {
            'transaction': tx,
            'kind':        Notification.KIND_DISPUTE_OPENED,
            'title':       f'Issue reported: {tx.product_title}',
            'message':     f'{buyer_lbl} reported an issue: "{issue_type}". Funds are frozen pending resolution.',
        }
        if tx.seller_shop:
            Notification.objects.create(recipient_shop=tx.seller_shop,  **notif_data)
        else:
            Notification.objects.create(recipient_user=tx.seller, **notif_data)

        from .serializers import IssueSerializer
        return Response(IssueSerializer(issue, context={'request': request}).data, status=201)


class BuyerIssueListView(APIView):
    """
    GET /api/escrow/my-issues/
    GET /api/escrow/my-issues/?as_shop=<id>

    Personal mode (no ?as_shop): issues on transactions where buyer_shop is null.
    Shop mode    (?as_shop=<id>): issues on transactions where buyer_shop matches.
    The two sets are completely separate — switching identity shows only that
    identity's issues.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .models import Issue
        from .serializers import IssueSerializer

        as_shop_id = request.query_params.get('as_shop')

        qs = Issue.objects.filter(transaction__buyer=request.user)

        if as_shop_id:
            # Shop identity — only issues from purchases made as this shop
            qs = qs.filter(transaction__buyer_shop__id=as_shop_id)
        else:
            # Personal identity — only issues from personal purchases
            qs = qs.filter(transaction__buyer_shop__isnull=True)

        qs = qs.select_related(
            'transaction', 'transaction__buyer_shop',
            'transaction__seller_shop', 'transaction__seller',
            'transaction__product',
        ).prefetch_related('messages__sender')

        return Response(IssueSerializer(qs, many=True, context={'request': request}).data)


class IssueCountView(APIView):
    """
    GET /api/escrow/my-issue-count/
    GET /api/escrow/my-issue-count/?as_shop=<id>

    Returns { count } of open/replied issues for this buyer identity.
    Personal mode: buyer_shop is null. Shop mode: filters by buyer_shop.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .models import Issue
        as_shop_id = request.query_params.get('as_shop')

        # Include all active stages — seller_resolved needs buyer action too
        qs = Issue.objects.filter(
            transaction__buyer=request.user,
            stage__in=[Issue.STAGE_OPEN, Issue.STAGE_REPLIED, Issue.STAGE_SELLER_RESOLVED],
        )
        if as_shop_id:
            qs = qs.filter(transaction__buyer_shop__id=as_shop_id)
        else:
            qs = qs.filter(transaction__buyer_shop__isnull=True)

        return Response({'count': qs.count()})


class SellerIssueListView(APIView):
    """
    GET /api/escrow/seller-issues/
    GET /api/escrow/seller-issues/?as_shop=<id>

    Returns all issues on the seller's transactions.
    If ?as_shop=<id> — only issues on transactions where seller_shop matches.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .models import Issue
        from .serializers import IssueSerializer

        as_shop_id = request.query_params.get('as_shop')

        if as_shop_id:
            issues = Issue.objects.filter(
                transaction__seller=request.user,
                transaction__seller_shop__id=as_shop_id,
            )
        else:
            # Personal identity — only issues on personal sales (seller_shop is null)
            issues = Issue.objects.filter(
                transaction__seller=request.user,
                transaction__seller_shop__isnull=True,
            )

        issues = issues.select_related(
            'transaction', 'transaction__buyer_shop',
            'transaction__seller_shop', 'transaction__buyer',
            'transaction__product',
        ).prefetch_related('messages__sender')

        return Response(IssueSerializer(issues, many=True, context={'request': request}).data)


class IssueDetailView(APIView):
    """
    GET  /api/escrow/issues/<pk>/   — buyer or seller fetches full detail + messages
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        from .models import Issue
        from .serializers import IssueSerializer

        try:
            issue = Issue.objects.select_related(
                'transaction', 'transaction__buyer_shop',
                'transaction__seller_shop', 'transaction__seller',
                'transaction__buyer', 'transaction__product',
            ).prefetch_related('messages__sender').get(pk=pk)
        except Issue.DoesNotExist:
            return Response({'detail': 'Issue not found.'}, status=404)

        tx = issue.transaction
        if tx.buyer != request.user and tx.seller != request.user:
            return Response({'detail': 'Not authorised.'}, status=403)

        return Response(IssueSerializer(issue, context={'request': request}).data)


class IssueMessageView(APIView):
    """
    POST /api/escrow/issues/<pk>/message/

    Buyer or seller adds a message to the thread.
    Seller reply advances stage → 'replied'.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        from .models import Issue, IssueMessage, Notification
        from .serializers import IssueMessageSerializer

        try:
            issue = Issue.objects.select_related(
                'transaction', 'transaction__buyer',
                'transaction__seller', 'transaction__buyer_shop',
                'transaction__seller_shop',
            ).get(pk=pk)
        except Issue.DoesNotExist:
            return Response({'detail': 'Issue not found.'}, status=404)

        tx = issue.transaction
        is_buyer  = tx.buyer  == request.user
        is_seller = tx.seller == request.user

        if not is_buyer and not is_seller:
            return Response({'detail': 'Not authorised.'}, status=403)

        if issue.stage in [Issue.STAGE_RESOLVED, Issue.STAGE_ESCALATED]:
            return Response({'detail': 'This issue is closed.'}, status=400)

        text = request.data.get('text', '').strip()
        if not text:
            return Response({'detail': 'text is required.'}, status=400)

        role = IssueMessage.ROLE_BUYER if is_buyer else IssueMessage.ROLE_SELLER

        msg = IssueMessage.objects.create(
            issue=issue,
            sender=request.user,
            sender_role=role,
            text=text,
        )

        # Seller reply moves stage to 'replied'
        if is_seller and issue.stage == Issue.STAGE_OPEN:
            issue.stage = Issue.STAGE_REPLIED
            issue.save(update_fields=['stage'])

        # Notify the other party
        if is_seller:
            notif_kwargs = {'transaction': tx, 'kind': 'issue_replied',
                'title': f'Seller replied on: {tx.product_title}',
                'message': text[:120]}
            if tx.buyer_shop:
                Notification.objects.create(recipient_shop=tx.buyer_shop,  **notif_kwargs)
            else:
                Notification.objects.create(recipient_user=tx.buyer, **notif_kwargs)
        else:
            notif_kwargs = {'transaction': tx, 'kind': 'issue_replied',
                'title': f'Buyer replied on: {tx.product_title}',
                'message': text[:120]}
            if tx.seller_shop:
                Notification.objects.create(recipient_shop=tx.seller_shop, **notif_kwargs)
            else:
                Notification.objects.create(recipient_user=tx.seller, **notif_kwargs)

        return Response(IssueMessageSerializer(msg, context={'request': request}).data, status=201)


class IssueResolveView(APIView):
    """
    PATCH /api/escrow/issues/<pk>/resolve/

    SELLER → stage: seller_resolved  (funds still frozen, buyer notified to confirm)
    BUYER  → stage: resolved, tx: STATUS_RELEASED, buy_count++, funds released
    """
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        from .models import Issue, Notification
        from .serializers import IssueSerializer

        try:
            issue = Issue.objects.select_related(
                'transaction', 'transaction__buyer', 'transaction__seller',
                'transaction__buyer_shop', 'transaction__seller_shop',
                'transaction__product',
            ).get(pk=pk)
        except Issue.DoesNotExist:
            return Response({'detail': 'Issue not found.'}, status=404)

        tx        = issue.transaction
        is_buyer  = tx.buyer  == request.user
        is_seller = tx.seller == request.user

        if not is_buyer and not is_seller:
            return Response({'detail': 'Not authorised.'}, status=403)
        if issue.stage == Issue.STAGE_ESCALATED:
            return Response({'detail': 'Escalated issues are handled by the marketplace.'}, status=400)
        if issue.stage == Issue.STAGE_RESOLVED:
            return Response({'detail': 'Already resolved.'}, status=400)

        # ── SELLER marks resolved ─────────────────────────────────────────────
        # Funds stay frozen. Buyer must confirm before funds are released.
        if is_seller:
            issue.stage = Issue.STAGE_SELLER_RESOLVED
            issue.save(update_fields=['stage'])

            seller_lbl = tx.seller_shop.shop_name if tx.seller_shop else _safe_name(tx.seller)
            notif = {
                'transaction': tx,
                'kind':        'issue_replied',
                'title':       f'{seller_lbl} marked the issue as resolved',
                'message':     f'Please confirm if the issue with "{tx.product_title}" is resolved, or escalate to the marketplace.',
            }
            if tx.buyer_shop:
                Notification.objects.create(recipient_shop=tx.buyer_shop, **notif)
            else:
                Notification.objects.create(recipient_user=tx.buyer, **notif)

            return Response(IssueSerializer(issue, context={'request': request}).data)

        # ── BUYER confirms resolution ─────────────────────────────────────────
        # Only allowed when seller has marked resolved (or stage is replied).
        if issue.stage not in (Issue.STAGE_SELLER_RESOLVED, Issue.STAGE_REPLIED, Issue.STAGE_OPEN):
            return Response({'detail': 'Nothing to confirm yet.'}, status=400)

        issue.stage = Issue.STAGE_RESOLVED
        issue.save(update_fields=['stage'])

        # Release escrow
        funds_released = False
        if tx.status == EscrowTransaction.STATUS_DISPUTED:
            tx.status = EscrowTransaction.STATUS_RELEASED
            tx.save(update_fields=['status'])
            funds_released = True
            if tx.product_id:
                Product.objects.filter(pk=tx.product_id).update(
                    buy_count=models.F('buy_count') + 1
                )

        buyer_lbl = _buyer_label(tx)
        notif = {
            'transaction': tx,
            'kind':        Notification.KIND_RECEIPT_CONFIRMED,
            'title':       f'Issue resolved — funds released',
            'message':     f'{buyer_lbl} confirmed the issue is resolved for "{tx.product_title}". KES {tx.seller_payout} released.',
        }
        if tx.seller_shop:
            Notification.objects.create(recipient_shop=tx.seller_shop, **notif)
        else:
            Notification.objects.create(recipient_user=tx.seller, **notif)

        return Response({
            **IssueSerializer(issue, context={'request': request}).data,
            'funds_released': funds_released,
            'seller_payout':  str(tx.seller_payout),
            'platform_cut':   str(tx.platform_fee),
        })


class IssueEscalateView(APIView):
    """
    PATCH /api/escrow/issues/<pk>/escalate/

    Buyer escalates to marketplace after seller reply didn't satisfy.
    Stage → 'escalated'. Transaction stays STATUS_DISPUTED (funds frozen).
    Marketplace admins will review via Django admin or a future admin dashboard.
    """
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        from .models import Issue, IssueMessage, Notification
        from .serializers import IssueSerializer

        try:
            issue = Issue.objects.select_related('transaction').get(pk=pk)
        except Issue.DoesNotExist:
            return Response({'detail': 'Issue not found.'}, status=404)

        tx = issue.transaction
        if tx.buyer != request.user:
            return Response({'detail': 'Only the buyer can escalate an issue.'}, status=403)

        if issue.stage == Issue.STAGE_ESCALATED:
            return Response({'detail': 'Already escalated.'}, status=400)

        if issue.stage == Issue.STAGE_RESOLVED:
            return Response({'detail': 'Cannot escalate a resolved issue.'}, status=400)

        issue.stage = Issue.STAGE_ESCALATED
        issue.save(update_fields=['stage'])

        # System message in thread
        IssueMessage.objects.create(
            issue=issue,
            sender=request.user,
            sender_role=IssueMessage.ROLE_MARKET,
            text='This issue has been escalated to Wireshops Marketplace Support. '
                 'Our team will review and contact both parties within 24 hours. '
                 'Funds remain frozen until a resolution is reached.',
        )

        # Notify seller
        buyer_lbl = tx.buyer_shop.shop_name if tx.buyer_shop else _safe_name(tx.buyer)
        notif_kwargs = {'transaction': tx, 'kind': Notification.KIND_DISPUTE_OPENED,
            'title': f'Issue escalated: {tx.product_title}',
            'message': f'{buyer_lbl} has escalated this issue to the marketplace. Funds remain frozen.'}
        if tx.seller_shop:
            Notification.objects.create(recipient_shop=tx.seller_shop, **notif_kwargs)
        else:
            Notification.objects.create(recipient_user=tx.seller, **notif_kwargs)

        return Response(IssueSerializer(issue, context={'request': request}).data)