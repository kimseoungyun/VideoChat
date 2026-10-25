from django.contrib import admin
from django.urls import path, include
from main.throttle import admin_login
from .health import health
from .metrics import metrics

# Staff accounts can read report evidence: their login gets the same throttling as /login/.
admin.site.login = admin_login

urlpatterns = [
    path('health/', health, name='health'),
    path('metrics/', metrics, name='metrics'),
    path('admin/', admin.site.urls),
    path('', include('main.urls')),
    path('chat/', include('chat.urls', namespace='chat')),
]
