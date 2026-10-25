from django.conf import settings
from django.utils import translation


class ChosenLanguageMiddleware:
    """Korean unless the visitor picked another language in the header (set_language cookie).

    Django's LocaleMiddleware would also follow Accept-Language; a Korean-first service is more
    predictable when the page only changes language on request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        chosen = request.COOKIES.get(settings.LANGUAGE_COOKIE_NAME)
        language = chosen if chosen in dict(settings.LANGUAGES) else settings.LANGUAGE_CODE
        translation.activate(language)
        request.LANGUAGE_CODE = language
        response = self.get_response(request)
        response.headers.setdefault('Content-Language', language)
        translation.deactivate()
        return response
