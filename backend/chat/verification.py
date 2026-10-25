"""Identity verification adapters.

A real provider (Korean 본인인증 such as PASS, or an age-estimation vendor) redirects the user
out and calls back; the adapter turns the callback into a Verification. Only two facts are kept:
whether the person is an adult, and a hash of the provider's stable per-person identifier (CI),
which becomes the identity bans attach to: it survives new IPs, accounts and devices.
"""
from dataclasses import dataclass
from datetime import date
from django.conf import settings
from django.shortcuts import render
from django.utils.module_loading import import_string


@dataclass
class Verification:
    adult: bool
    subject: str  # the provider's stable per-person identifier; hashed before it is stored


class Verifier:
    name = 'base'

    def begin(self, request):
        """Response that starts verification (usually a redirect to the provider)."""
        raise NotImplementedError

    def complete(self, request):
        """Verification from the provider's callback, or None if it failed or was cancelled."""
        raise NotImplementedError


class DevVerifier(Verifier):
    """Development stand-in: trusts whatever is typed. settings refuses it outside DEBUG."""
    name = 'dev'

    def begin(self, request):
        return render(request, 'chat/verify_dev.html', {'min_age': settings.MIN_AGE,
                                                        'next': request.GET.get('next', '')})

    def complete(self, request):
        try:
            born = date.fromisoformat(request.POST.get('birth_date', ''))
        except ValueError:
            return None
        name = request.POST.get('name', '').strip()
        if not name:
            return None
        today = date.today()
        age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
        return Verification(adult=age >= settings.MIN_AGE, subject=f'dev:{name}:{born.isoformat()}')


def get_verifier():
    return import_string(settings.IDENTITY_VERIFIER)() if settings.IDENTITY_VERIFIER else None
