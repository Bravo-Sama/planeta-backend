from django import views
from django.contrib import admin
from django.urls import path, include
from api_central import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/telegram/', include('satelite_telegram.urls')), 
    path('ingesta/', include('satelite_limpiador.urls')),
    path('api/', include('api_central.urls')),
    path('dashboard/', views.dashboard_view, name='dashboard_admin'),
]
