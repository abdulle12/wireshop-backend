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
        if tx.status not in (EscrowTransaction.STATUS_SHIPPED, EscrowTransaction.STATUS_DELIVERED):
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