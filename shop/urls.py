# shop/urls.py
from django.urls import path
from .views import (
    ShopListCreateView,
    ShopDetailView,
    ProductListCreateView,
    PublicProductFeedView,
    PublicCategoryListView,
    PublicProductDetailView,
    PublicShopDetailView,
    PublicShopProductsView,
    ShopFollowView,
    FollowingFeedView, 
    FollowingCategoryListView,
    FollowingShopsListView
    
)

urlpatterns = [
    path('shops/',                        ShopListCreateView.as_view()),
    path('shops/<int:pk>/',               ShopDetailView.as_view()),
    path('shops/<int:shop_id>/products/', ProductListCreateView.as_view()),
    path('feed/',                         PublicProductFeedView.as_view()),
    path('feed/categories/',              PublicCategoryListView.as_view()),
    path('products/<slug:slug>/',         PublicProductDetailView.as_view()),
    path('shops/public/<slug:slug>/',            PublicShopDetailView.as_view()),
    path('shops/public/<slug:slug>/products/',   PublicShopProductsView.as_view()),
    path('shops/public/<slug:slug>/follow/',          ShopFollowView.as_view()),
    path('feed/following/',            FollowingFeedView.as_view()),
    path('feed/following/categories/', FollowingCategoryListView.as_view()),
    path('feed/following/shops/', FollowingShopsListView.as_view()),
]