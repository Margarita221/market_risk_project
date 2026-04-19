from riskapp.i18n import get_request_language


def ui_language(request):
    return {"ui_language": get_request_language(request)}
