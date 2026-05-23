from markupsafe import Markup, escape
from sympy import re

def render_cloze_hidden(text: str) -> Markup:
    escaped = escape(text)

    hidden = re.sub(
        r"\{\{c\d+::(.*?)\}\}",
        '<span class="cloze-blank">_____</span>',
        str(escaped)
    )

    return Markup(hidden)


def render_cloze_revealed(text: str) -> Markup:
    escaped = escape(text)

    revealed = re.sub(
        r"\{\{c\d+::(.*?)\}\}",
        r'<span class="cloze-answer">\1</span>',
        str(escaped)
    )

    return Markup(revealed)