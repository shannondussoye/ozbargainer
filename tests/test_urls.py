from ozbargain.utils.urls import normalize_deal_url
from ozbargain.config import settings


def test_normalize_relative_url():
    assert normalize_deal_url("/node/123") == f"{settings.ozbargain_base_url}/node/123"


def test_normalize_redir_stripping():
    assert normalize_deal_url("/node/123/redir") == f"{settings.ozbargain_base_url}/node/123"
    assert normalize_deal_url("https://www.ozbargain.com.au/node/123/redir") == "https://www.ozbargain.com.au/node/123"


def test_normalize_redir_query_stripping():
    assert normalize_deal_url("/node/123/redir?id=456") == f"{settings.ozbargain_base_url}/node/123?id=456"


def test_normalize_absolute_url_passthrough():
    assert normalize_deal_url("https://www.ozbargain.com.au/node/123") == "https://www.ozbargain.com.au/node/123"


def test_normalize_non_node_unmodified():
    assert normalize_deal_url("/wiki/help") == f"{settings.ozbargain_base_url}/wiki/help"
    # Endings with /redir should not be stripped for non-nodes
    assert normalize_deal_url("/wiki/help/redir") == f"{settings.ozbargain_base_url}/wiki/help/redir"


def test_normalize_comment_redir_stripping():
    assert normalize_deal_url("/comment/123/redir") == f"{settings.ozbargain_base_url}/comment/123"
    assert normalize_deal_url("https://www.ozbargain.com.au/comment/123/redir") == "https://www.ozbargain.com.au/comment/123"
    assert normalize_deal_url("/comment/123/redir?id=456") == f"{settings.ozbargain_base_url}/comment/123?id=456"


def test_normalize_cloudflare_parameter_stripping():
    assert normalize_deal_url("https://www.ozbargain.com.au/comment/123?__cf_chl_rt_tk=abc") == "https://www.ozbargain.com.au/comment/123"
    assert normalize_deal_url("https://www.ozbargain.com.au/node/123/redir?id=456&__cf_chl_rt_tk=xyz") == "https://www.ozbargain.com.au/node/123?id=456"
