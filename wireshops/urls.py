from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static
from escrow_app.urls import escrow_urlpatterns, notification_urlpatterns

urlpatterns = [
    path('admin/',             admin.site.urls),
    path('api/auth/',          include('accounts.urls')),
    path('api/',               include('shop.urls')),
    path('api/messages/',      include('messaging.urls')),
    path('api/escrow/',        include(escrow_urlpatterns)),
    path('api/notifications/', include(notification_urlpatterns)),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)