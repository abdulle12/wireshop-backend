from django.urls import path
from .views import (
    ShopListCreateView,
    ShopDetailView,
    ProductListCreateView,
    ProductDetailView,
    PublicProductFeedView,
    PublicCategoryListView,
    PublicProductDetailView,
    ShareProductView,
    PublicShopDetailView,
    PublicShopProductsView,
    ShopFollowView,
    FollowingFeedView,
    FollowingCategoryListView,
    FollowingShopsListView,
    ShopReviewListCreateView,
    ShopReviewHelpfulView,
    ProductReviewListCreateView,
    ProductReviewHelpfulView,
)

urlpatterns = [
    # ── Owner shop management ──────────────────────────────────────────────
    path('shops/',                                        ShopListCreateView.as_view()),
    path('shops/<int:pk>/',                               ShopDetailView.as_view()),
    path('shops/<int:shop_id>/products/',                 ProductListCreateView.as_view()),
    path('shops/<int:shop_id>/products/<int:pk>/',        ProductDetailView.as_view()),

    # ── Public feed ────────────────────────────────────────────────────────
    path('feed/',                                         PublicProductFeedView.as_view()),
    path('feed/categories/',                              PublicCategoryListView.as_view()),

    # ── Following feed ─────────────────────────────────────────────────────
    path('feed/following/',                               FollowingFeedView.as_view()),
    path('feed/following/categories/',                    FollowingCategoryListView.as_view()),
    path('feed/following/shops/',                         FollowingShopsListView.as_view()),

    # ── Product (item) reviews ─────────────────────────────────────────────
    # Fixed path MUST come before the generic <slug> pattern below,
    # otherwise Django matches 'reviews' as a product slug.
    path('products/reviews/<int:pk>/helpful/',            ProductReviewHelpfulView.as_view()),
    path('products/<slug:slug>/reviews/',                 ProductReviewListCreateView.as_view()),

    # ── Public product & shop detail ───────────────────────────────────────
    path('products/<slug:slug>/',                         PublicProductDetailView.as_view()),
    path('products/<slug:slug>/share/',                   ShareProductView.as_view()),
    path('shops/public/<slug:slug>/',                     PublicShopDetailView.as_view()),
    path('shops/public/<slug:slug>/products/',            PublicShopProductsView.as_view()),
    path('shops/public/<slug:slug>/follow/',              ShopFollowView.as_view()),

    # ── Shop reviews ───────────────────────────────────────────────────────
    path('shops/public/<slug:slug>/reviews/',             ShopReviewListCreateView.as_view()),
    path('reviews/<int:pk>/helpful/',                     ShopReviewHelpfulView.as_view()),
]