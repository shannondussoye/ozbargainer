def normalize_deal_url(url: str) -> str:
    """
    Normalizes OzBargain URLs by prepending the base domain if it is relative
    and stripping redirect paths ('/redir' and '/redir?').
    """
    if url.startswith("/"):
        url = f"https://www.ozbargain.com.au{url}"

    if "/node/" in url:
        if url.endswith("/redir"):
            url = url.replace("/redir", "")
        elif "/redir?" in url:
            url = url.replace("/redir?", "?")

    return url
