"""Translation upkeep without GNU gettext (not available on Windows dev machines).

    python scripts/messages.py missing   # msgids used in the code but untranslated in locale/en
    python scripts/messages.py compile   # .po -> .mo (needs Babel: requirements-dev.txt)

`missing` is also run by the test suite, so an untranslated UI string fails CI.
"""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / 'backend'
LOCALE = BACKEND / 'locale'
TRANSLATE = re.compile(r'{%\s*translate\s+"((?:[^"\\]|\\.)*)"\s*%}')
BLOCK = re.compile(r'{%\s*blocktranslate\s*%}(.*?){%\s*endblocktranslate\s*%}', re.S)
JS_CALL = re.compile(r'(?<![\w.])_\("((?:[^"\\\n]|\\.)*)"\)')
PY_NAMES = {'_', 'gettext', 'gettext_lazy', 'gettext_noop'}


def template_ids():
    ids = set()
    for path in BACKEND.glob('chat/templates/**/process.html'):
        text = path.read_text(encoding='utf-8')
        ids |= set(TRANSLATE.findall(text))
        ids |= {re.sub(r'{{\s*(\w+)\s*}}', r'%(\1)s', block) for block in BLOCK.findall(text)}
    return ids


def python_ids():
    ids = set()
    for path in [BACKEND / 'chat' / 'consumers.py', BACKEND / 'chat' / 'views.py']:
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if (isinstance(node, ast.Call) and getattr(node.func, 'id', None) in PY_NAMES and node.args
                    and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                ids.add(node.args[0].value)
    return ids


def js_ids():
    text = (BACKEND / 'chat' / 'static' / 'js' / 'script.js').read_text(encoding='utf-8')
    return {bytes(m, 'utf-8').decode('unicode_escape').encode('latin-1').decode('utf-8')
            if '\\' in m else m for m in JS_CALL.findall(text)}


def read_po(path):
    """{msgid: msgstr} for the simple single/multi-line entries we write by hand."""
    entries, field, current = {}, None, {'msgid': '', 'msgstr': ''}

    def unquote(value):
        return ast.literal_eval(value.strip())
    for line in path.read_text(encoding='utf-8').splitlines() + ['']:
        line = line.strip()
        if line.startswith('msgid '):
            if field == 'msgstr' and current['msgid']:
                entries[current['msgid']] = current['msgstr']
            current, field = {'msgid': unquote(line[6:]), 'msgstr': ''}, 'msgid'
        elif line.startswith('msgstr '):
            current['msgstr'], field = unquote(line[7:]), 'msgstr'
        elif line.startswith('"') and field:
            current[field] += unquote(line)
        elif not line and field == 'msgstr':
            if current['msgid']:
                entries[current['msgid']] = current['msgstr']
            field = None
    return entries


def missing():
    django_po = read_po(LOCALE / 'en' / 'LC_MESSAGES' / 'django.po')
    js_po = read_po(LOCALE / 'en' / 'LC_MESSAGES' / 'djangojs.po')
    gaps = sorted(i for i in template_ids() | python_ids() if not django_po.get(i))
    gaps += sorted(f'[js] {i}' for i in js_ids() if not js_po.get(i))
    return gaps


def compile_all():
    from babel.messages.mofile import write_mo
    from babel.messages.pofile import read_po as babel_read_po
    from datetime import datetime, timezone
    for po in LOCALE.glob('*/LC_MESSAGES/*.po'):
        with po.open('rb') as source:
            catalog = babel_read_po(source)
        # Babel stamps "now" into the header; a fixed date keeps the committed .mo reproducible.
        catalog.creation_date = catalog.revision_date = datetime(2026, 1, 1, tzinfo=timezone.utc)
        with po.with_suffix('.mo').open('wb') as target:
            write_mo(target, catalog)
        print('compiled', po.relative_to(ROOT))


if __name__ == '__main__':
    if sys.argv[1:] == ['compile']:
        compile_all()
    else:
        gaps = missing()
        print('\n'.join(gaps) or 'all strings translated')
        sys.exit(1 if gaps else 0)
