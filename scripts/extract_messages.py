"""Extract translatable strings into locale/*/LC_MESSAGES/django.po catalogs.

Substitute for `manage.py makemessages` on hosts without GNU gettext.
The Docker image installs gettext, so the canonical flow inside containers is:

    docker compose run --rm web python manage.py makemessages -l en -l prs -l ps
    docker compose run --rm web python manage.py compilemessages

Run this script from the repository root:  python scripts/extract_messages.py
"""
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
LOCALES = ["en", "prs", "ps"]
SKIP_DIRS = {".venv", "node_modules", "staticfiles", ".git", "media", "locale"}

# Python-side: gettext_lazy("...") / _("...")
PY_PATTERN = re.compile(r"""(?:gettext_lazy|gettext|_)\(\s*["']((?:\\.|[^"'])+)["']""")
# Template-side: {% translate "..." %} / {% blocktranslate %} skipped (none used)
TPL_PATTERN = re.compile(r"""\{%\s*translate\s+["']((?:\\.|[^"'])+)["']""")


def iter_source_files():
    for path in BASE_DIR.rglob("*"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix in {".py", ".html"} and path.is_file():
            yield path


def extract() -> list[str]:
    seen: dict[str, None] = {}  # ordered unique set
    for path in iter_source_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        pattern = PY_PATTERN if path.suffix == ".py" else TPL_PATTERN
        for match in pattern.finditer(text):
            msg = match.group(1).replace("\\'", "'").replace('\\"', '"')
            seen.setdefault(msg, None)
    return list(seen)


def escape_po(msg: str) -> str:
    return msg.replace("\\", "\\\\").replace('"', '\\"')


def write_catalog(locale: str, messages: list[str]) -> None:
    out = BASE_DIR / "locale" / locale / "LC_MESSAGES" / "django.po"
    out.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M%z")
    lines = [
        '# AUTOMEX CarFlow catalog. Regenerate with makemessages (gettext) when',
        '# available; this file is maintained by scripts/extract_messages.py.',
        'msgid ""',
        'msgstr ""',
        '"Project-Id-Version: automex-carflow 1.0\\n"',
        '"Report-Msgid-Bugs-To: \\n"',
        f'"POT-Creation-Date: {now}\\n"',
        f'"PO-Revision-Date: {now}\\n"',
        '"Language: %s\\n"' % locale,
        '"MIME-Version: 1.0\\n"',
        '"Content-Type: text/plain; charset=UTF-8\\n"',
        '"Content-Transfer-Encoding: 8bit\\n"',
        "",
    ]
    for msg in messages:
        lines.append(f'msgid "{escape_po(msg)}"')
        lines.append('msgstr ""')
        lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"{out}: {len(messages)} strings")


def main() -> int:
    messages = extract()
    for locale in LOCALES:
        write_catalog(locale, messages)
    print(f"Total unique strings: {len(messages)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
