"""{% static_v 'portal/app.css' %} = the normal static address plus
?v=<the file's last change time>. Without it a browser keeps an old copy of
the css / js after a change and you need Ctrl+F5 to see the new look.
(Copied from the main NOP portal.)"""
from pathlib import Path

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static

register = template.Library()


@register.simple_tag
def static_v(path: str) -> str:
    found = finders.find(path)
    try:
        stamp = int(Path(found).stat().st_mtime) if found else 0
    except (OSError, TypeError):
        stamp = 0
    return f"{static(path)}?v={stamp}"
