"""Environment-based settings shared by development and ASGI deployment."""
import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
DEBUG = os.getenv('DJANGO_DEBUG', '1') == '1'
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'local-development-only-not-for-production')
if not DEBUG and SECRET_KEY == 'local-development-only-not-for-production':
    raise ImproperlyConfigured('Set DJANGO_SECRET_KEY in production.')
ALLOWED_HOSTS = os.getenv('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')
INSTALLED_APPS = [
    'daphne', 'django.contrib.admin', 'django.contrib.auth',
    'django.contrib.contenttypes', 'django.contrib.sessions',
    'django.contrib.messages', 'django.contrib.staticfiles',
    'chat', 'channels', 'main.apps.MainConfig',
]
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
ROOT_URLCONF = 'myproj.urls'
ASGI_APPLICATION = 'myproj.asgi.application'
WSGI_APPLICATION = 'myproj.wsgi.application'
TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [BASE_DIR / 'templates'], 'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.request',
        'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages',
    ]},
}]
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3',
                        'NAME': os.getenv('DATABASE_PATH', str(BASE_DIR / 'db.sqlite3'))}}
REDIS_URL = os.getenv('REDIS_URL', 'redis://127.0.0.1:6379/0')
REDIS_POOL_SIZE = int(os.getenv('REDIS_POOL_SIZE', '50'))
CHANNEL_LAYERS = {'default': {'BACKEND': 'channels_redis.core.RedisChannelLayer',
                              # capacity bounds one process's shared inbox, so it scales with
                              # sockets per process, not per conversation.
                              'CONFIG': {'hosts': [REDIS_URL], 'expiry': 30,
                                         'capacity': int(os.getenv('CHANNEL_CAPACITY', '5000'))}}}
MATCHMAKING_PREFIX = os.getenv('MATCHMAKING_PREFIX', 'videochat:{match}:')
PRESENCE_TTL = 60
# A dropped socket keeps its call this long so the browser can resume it on a new socket.
RESUME_GRACE_SECONDS = int(os.getenv('RESUME_GRACE_SECONDS', '15'))
# Language/interest preferences are honoured until someone has waited this long.
MATCH_RELAX_SECONDS = int(os.getenv('MATCH_RELAX_SECONDS', '10'))
MATCH_LANGUAGES = ('ko', 'en', 'ja', 'zh')
MATCH_INTERESTS = ('music', 'games', 'movies', 'sports', 'travel', 'study', 'pets', 'food')
# Abuse limits. Guests behind one NAT share an IP, so per-IP caps are deliberately loose.
WS_MAX_PER_IP = int(os.getenv('WS_MAX_PER_IP', '10'))
WS_CONNECT_RATE = int(os.getenv('WS_CONNECT_RATE', '60'))  # new sockets per IP per minute
LOGIN_FAILURES_PER_USER = 5  # per 15 minutes
LOGIN_FAILURES_PER_IP = 20
SIGNUPS_PER_IP = 5  # per hour
# One fetch per user per match; a school or office NAT can carry dozens of users.
RTC_CONFIG_PER_IP = int(os.getenv('RTC_CONFIG_PER_IP', '300'))  # per minute
REPORT_BAN_THRESHOLD = int(os.getenv('REPORT_BAN_THRESHOLD', '3'))  # distinct reporters
REPORT_WINDOW_SECONDS = 24 * 3600
REPORT_BAN_SECONDS = int(os.getenv('REPORT_BAN_SECONDS', '3600'))
REPORT_BLOCK_SECONDS = 24 * 3600
METRICS_TOKEN = os.getenv('METRICS_TOKEN', '')
TURN_URLS = [url for url in os.getenv('TURN_URLS', '').split(',') if url]
TURN_SECRET = os.getenv('TURN_SECRET', '')
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
LOGIN_URL = '/login/'
LANGUAGE_CODE = 'ko-kr'
TIME_ZONE = 'Asia/Seoul'
USE_I18N = True
USE_TZ = True
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = not DEBUG
SECURE_HSTS_SECONDS = 31536000 if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
# Only enable behind a trusted proxy that overwrites these headers.
TRUST_PROXY = os.getenv('TRUST_PROXY', '0') == '1'
if TRUST_PROXY:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
