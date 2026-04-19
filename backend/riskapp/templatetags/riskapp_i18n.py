from django import template

from riskapp.i18n import translate


register = template.Library()


@register.simple_tag(takes_context=True)
def t(context, key):
    return translate(key, context.get("ui_language", "ru"))
