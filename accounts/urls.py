from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from .views import SignupView, LogoutView, MeView

urlpatterns = [
    path('signup/',          SignupView.as_view()),
    path('login/',           TokenObtainPairView.as_view()),   # built-in
    path('token/refresh/',   TokenRefreshView.as_view()),
    path('logout/',          LogoutView.as_view()),
    path('me/',              MeView.as_view()),
]