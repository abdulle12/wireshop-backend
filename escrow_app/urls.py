from django.urls import path
from .views import (
    CheckoutView,
    IncomingOrdersView,
    ShipOrderView,
    DeliveryInfoView,
    ConfirmReceiptView,
    DisputeOrderView,
    BuyerOrdersView,
    BuyerOrderCountsView,
    NotificationListView,
    NotificationUnreadCountView,
    NotificationMarkAllReadView,
    NotificationReadView,
    NotificationDeleteView,
)

# Mount under api/escrow/
# IMPORTANT: fixed paths (checkout/, incoming/, my-orders/, my-order-counts/)
# must come BEFORE the <uuid:pk>/ patterns so Django doesn't try to match
# those words as UUIDs.
escrow_urlpatterns = [
    path('checkout/',                  CheckoutView.as_view()),
    path('incoming/',                  IncomingOrdersView.as_view()),
    path('my-orders/',                 BuyerOrdersView.as_view()),
    path('my-order-counts/',           BuyerOrderCountsView.as_view()),
    path('<uuid:pk>/ship/',            ShipOrderView.as_view()),
    path('<uuid:pk>/delivery-info/',   DeliveryInfoView.as_view()),
    path('<uuid:pk>/confirm-receipt/', ConfirmReceiptView.as_view()),
    path('<uuid:pk>/dispute/',         DisputeOrderView.as_view()),
]

# Mount under api/notifications/
# IMPORTANT: fixed paths must come before <int:pk>/ patterns
notification_urlpatterns = [
    path('',               NotificationListView.as_view()),
    path('unread-count/',  NotificationUnreadCountView.as_view()),
    path('read-all/',      NotificationMarkAllReadView.as_view()),
    path('<int:pk>/read/', NotificationReadView.as_view()),
    path('<int:pk>/',      NotificationDeleteView.as_view()),
]