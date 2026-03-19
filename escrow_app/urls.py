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
    ProductOrdersView,
    ProductOrderCountsView,
    NotificationListView,
    NotificationUnreadCountView,
    NotificationMarkAllReadView,
    NotificationReadView,
    NotificationDeleteView,
    # Issue / Support system
    ReportIssueView,
    BuyerIssueListView,
    IssueCountView,
    SellerIssueListView,
    IssueDetailView,
    IssueMessageView,
    IssueResolveView,
    IssueEscalateView,
)

# Mount under api/escrow/
# IMPORTANT: all fixed-segment paths must come BEFORE <uuid:pk>/ patterns
escrow_urlpatterns = [
    path('checkout/',                              CheckoutView.as_view()),
    path('incoming/',                              IncomingOrdersView.as_view()),
    path('my-orders/',                             BuyerOrdersView.as_view()),
    path('my-order-counts/',                       BuyerOrderCountsView.as_view()),
    path('product/<int:product_id>/orders/',       ProductOrdersView.as_view()),
    path('product/<int:product_id>/order-counts/', ProductOrderCountsView.as_view()),
    # Issue fixed paths — must be before <uuid:pk>/
    path('my-issues/',                             BuyerIssueListView.as_view()),
    path('my-issue-count/',                        IssueCountView.as_view()),
    path('seller-issues/',                         SellerIssueListView.as_view()),
    path('issues/<int:pk>/',                       IssueDetailView.as_view()),
    path('issues/<int:pk>/message/',               IssueMessageView.as_view()),
    path('issues/<int:pk>/resolve/',               IssueResolveView.as_view()),
    path('issues/<int:pk>/escalate/',              IssueEscalateView.as_view()),
    # Transaction-level paths
    path('<uuid:pk>/ship/',                        ShipOrderView.as_view()),
    path('<uuid:pk>/delivery-info/',               DeliveryInfoView.as_view()),
    path('<uuid:pk>/confirm-receipt/',             ConfirmReceiptView.as_view()),
    path('<uuid:pk>/dispute/',                     DisputeOrderView.as_view()),
    path('<uuid:pk>/report-issue/',                ReportIssueView.as_view()),
]

# Mount under api/notifications/
notification_urlpatterns = [
    path('',               NotificationListView.as_view()),
    path('unread-count/',  NotificationUnreadCountView.as_view()),
    path('read-all/',      NotificationMarkAllReadView.as_view()),
    path('<int:pk>/read/', NotificationReadView.as_view()),
    path('<int:pk>/',      NotificationDeleteView.as_view()),
]