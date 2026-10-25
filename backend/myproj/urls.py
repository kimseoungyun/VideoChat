from django.contrib import admin
from django.urls import path, include
from .health import health
from .metrics import metrics

urlpatterns = [
    path('health/', health, name='health'),
    path('metrics/', metrics, name='metrics'),
    path('admin/', admin.site.urls),
    path('', include('main.urls')),
    path('chat/', include('chat.urls', namespace='chat')),
]
