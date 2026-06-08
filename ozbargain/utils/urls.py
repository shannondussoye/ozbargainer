from ..config import settings


def normalize_deal_url(url: str) -> str:
    """
    Normalizes OzBargain URLs by prepending the base domain if it is relative
    and stripping redirect paths ('/redir' and '/redir?').
    """
    if url.startswith("/"):
        url = f"{settings.ozbargain_base_url}{url}"

    if "/node/" in url or "/comment/" in url:
        if url.endswith("/redir"):
            url = url.replace("/redir", "")
        elif "/redir?" in url:
            url = url.replace("/redir?", "?")

    # Strip Cloudflare challenge query parameters if present
    if "?" in url:
        base, query = url.split("?", 1)
        params = [p for p in query.split("&") if not p.startswith("__cf_") and not p.startswith("cf_")]
        if params:
            url = f"{base}?{'&'.join(params)}"
        else:
            url = base

    return url
