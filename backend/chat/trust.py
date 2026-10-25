"""What the session says about a user before they may be matched: rules/age consent and,
when required, a verified adult identity."""
from datetime import datetime, timezone
from django.conf import settings
from . import limits

CONSENT = 'videochat_consent'
VERIFIED = 'videochat_verified'


def record_consent(session):
    session[CONSENT] = {'version': settings.CONSENT_VERSION, 'at': datetime.now(timezone.utc).isoformat()}


def record_verification(session, verification, provider):
    session[VERIFIED] = {'adult': verification.adult, 'subject': limits.anonymize(verification.subject),
                         'provider': provider, 'at': datetime.now(timezone.utc).isoformat()}


def consented(session):
    return (session.get(CONSENT) or {}).get('version') == settings.CONSENT_VERSION


def verified_subject(session):
    """Hashed identifier of a verified adult, or None."""
    verified = session.get(VERIFIED) or {}
    return verified.get('subject') if verified.get('adult') else None


def gate(session):
    """None when the user may be matched, otherwise what is missing."""
    if settings.CONSENT_REQUIRED and not consented(session):
        return 'consent_required'
    if settings.REQUIRE_VERIFIED_ADULT and not verified_subject(session):
        return 'verification_required'
    return None


def page_state(session):
    return {'consented': consented(session) or not settings.CONSENT_REQUIRED,
            'verified': bool(verified_subject(session)),
            'verification_required': settings.REQUIRE_VERIFIED_ADULT,
            'minor': (session.get(VERIFIED) or {}).get('adult') is False}
