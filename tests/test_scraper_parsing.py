import pytest
from playwright.sync_api import sync_playwright
from ozbargain.core.scraper import BrowserScraper, FastScraper


@pytest.fixture(scope="module")
def scraper():
    return BrowserScraper(headless=True)


@pytest.fixture(scope="module")
def fast_scraper():
    return FastScraper()


@pytest.fixture(scope="module")
def page_with_fixture():
    html_content = """
    <html>
        <head>
            <title>Test Deal - OzBargain</title>
        </head>
        <body>
            <div class="node-full">
                <h1 id="title">Amazing $19.99 Product</h1>
                <div class="submitted">
                    <a href="/goto/1234">external-store.com</a> on 13/12/2025 - 09:30
                </div>
                <div class="taxonomy">
                    <a href="/cat/electronics">Electronics</a>
                    <a href="/tag/deals">Deals</a>
                </div>
                <div class="couponcode"><strong>SAVE20</strong></div>
                <div class="content">This is an amazing product, enjoy the deal.</div>
                <div class="n-vote">
                    <span class="voteup"><span>150</span></span>
                    <span class="votedown"><span>5</span></span>
                </div>
                <h2 id="comments">Comments (42)</h2>
            </div>
        </body>
    </html>
    """

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Route the specific URL to return our HTML fixture
        page.route(
            "https://www.ozbargain.com.au/node/123456", lambda route: route.fulfill(body=html_content, status=200)
        )
        page.goto("https://www.ozbargain.com.au/node/123456")

        yield page
        browser.close()


def test_extract_deal_data(scraper, page_with_fixture):
    # Pass a dummy url
    dummy_url = "https://www.ozbargain.com.au/node/123456"

    result = scraper._extract_deal_data(page_with_fixture, dummy_url)

    assert result.title == "Amazing $19.99 Product"
    assert result.price == "$19.99"
    assert result.coupon_code == "SAVE20"
    assert result.description == "This is an amazing product, enjoy the deal."
    assert result.upvotes == 150
    assert result.downvotes == 5
    assert result.comment_count == 42
    assert "Electronics" in result.tags
    assert "Deals" in result.tags
    assert result.external_domain == "external-store.com"
    assert result.posted_date == "13/12/2025 - 09:30"
    assert result.id == "node/123456"
    assert result.is_expired is False
    assert result.has_error is False


def test_fast_scraper_parsing(fast_scraper, mocker):
    # Test scrape_deal_fast with a mocked requests.Session.get
    html_content = """
    <html>
        <head>
            <title>Fast Deal $10.00 - OzBargain</title>
            <meta property="og:description" content="Fast meta desc" />
        </head>
        <body>
            <div class="couponcode">FAST10</div>
            <div class="taxonomy">
                <a href="/tag/fast">Fast</a>
            </div>
            <div class="expired"></div>
        </body>
    </html>
    """

    mock_response = mocker.Mock()
    mock_response.text = html_content
    mock_response.url = "https://www.ozbargain.com.au/node/999999"
    mock_response.raise_for_status = mocker.Mock()

    mocker.patch("requests.Session.get", return_value=mock_response)

    result = fast_scraper.scrape_deal_fast("https://www.ozbargain.com.au/node/999999")

    assert result.title == "Fast Deal $10.00"
    assert result.description == "Fast meta desc"
    assert result.coupon_code == "FAST10"
    assert result.tags == ["Fast"]
    assert result.is_expired is True
    assert result.id == "node/999999"
    assert result.has_error is False


def test_ld_json_comment_count_browser(scraper, mocker):
    mock_page = mocker.Mock()
    mock_locator = mocker.Mock()
    mock_locator.all_inner_texts.return_value = [
        '[{"@context":"https://schema.org","@type":"NewsArticle","commentCount":123}]'
    ]
    mock_page.locator.return_value = mock_locator

    count = scraper._get_comment_count(mock_page, "https://www.ozbargain.com.au/node/888888")
    assert count == 123
    mock_page.locator.assert_called_once_with('script[type="application/ld+json"]')


def test_ld_json_comment_count_fast(fast_scraper, mocker):
    html_content = """
    <html>
        <head>
            <script type="application/ld+json">[{"@context":"https://schema.org","commentCount":456}]</script>
        </head>
        <body></body>
    </html>
    """
    mock_response = mocker.Mock()
    mock_response.text = html_content
    mock_response.url = "https://www.ozbargain.com.au/node/777777"
    mock_response.raise_for_status = mocker.Mock()

    mocker.patch("requests.Session.get", return_value=mock_response)

    result = fast_scraper.scrape_deal_fast("https://www.ozbargain.com.au/node/777777")
    assert result.comment_count == 456


def test_fast_scraper_bot_wall(fast_scraper, mocker):
    # Test that FastScraper returns a DealResult with error if the title is in BOT_WALL_TITLES
    html_content = """
    <html>
        <head>
            <title>Performing security verification - OzBargain</title>
        </head>
        <body>
            <div>Access denied.</div>
        </body>
    </html>
    """
    mock_response = mocker.Mock()
    mock_response.text = html_content
    mock_response.url = "https://www.ozbargain.com.au/node/123456"
    mock_response.raise_for_status = mocker.Mock()

    mocker.patch("requests.Session.get", return_value=mock_response)

    result = fast_scraper.scrape_deal_fast("https://www.ozbargain.com.au/node/123456")
    assert result.has_error is True
    assert "Bot-wall block or empty page detected" in result.error


def test_browser_scraper_timeout_error_handling(mocker):
    # Mock playwright connection/launch
    mock_playwright = mocker.MagicMock()
    mock_browser = mocker.MagicMock()
    mock_page = mocker.MagicMock()

    mock_playwright.chromium.launch.return_value = mock_browser
    mock_browser.new_page.return_value = mock_page
    # Make page.goto raise an exception
    mock_page.goto.side_effect = Exception("Playwright navigation timeout")

    # Patch sync_playwright to return our mock
    mocker.patch(
        "ozbargain.core.scraper.sync_playwright",
        return_value=mocker.MagicMock(__enter__=mocker.MagicMock(return_value=mock_playwright)),
    )

    scraper = BrowserScraper(headless=True, cdp_url=None)
    scraper.cdp_url = None
    result = scraper.scrape_deal_page("https://www.ozbargain.com.au/node/123456")

    # Assertions
    assert result.has_error is True
    assert "Playwright navigation timeout" in result.error
    # Ensure browser.close() was called to prevent leaks
    mock_browser.close.assert_called_once()


def test_browser_scraper_reuse_timeout_error_handling(mocker):
    mock_browser = mocker.MagicMock()
    mock_context = mocker.MagicMock()
    mock_page = mocker.MagicMock()

    mock_browser.contexts = [mock_context]
    mock_context.new_page.return_value = mock_page
    mock_page.goto.side_effect = Exception("Browser reuse navigation timeout")

    scraper = BrowserScraper(headless=True)
    result = scraper.scrape_deal_page("https://www.ozbargain.com.au/node/123456", browser=mock_browser)

    assert result.has_error is True
    assert "Browser reuse navigation timeout" in result.error
    # Ensure page.close() was called to prevent leaks
    mock_page.close.assert_called_once()

