from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/telegram/', include('satelite_telegram.urls')), 
    path('ingesta/', include('satelite_limpiador.urls')),
    path('api/', include('api_central.urls')),
]
