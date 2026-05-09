import pytest
from playwright.sync_api import sync_playwright
from ozbargain.core.scraper import OzBargainScraper

@pytest.fixture(scope="module")
def scraper():
    return OzBargainScraper(headless=True)

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
        page.route("https://www.ozbargain.com.au/node/123456", lambda route: route.fulfill(body=html_content, status=200))
        page.goto("https://www.ozbargain.com.au/node/123456")
        
        yield page
        browser.close()

def test_extract_deal_data(scraper, page_with_fixture):
    # Pass a dummy url
    dummy_url = "https://www.ozbargain.com.au/node/123456"
    
    data = scraper._extract_deal_data(page_with_fixture, dummy_url)
    
    assert data["title"] == "Amazing $19.99 Product"
    assert data["price"] == "$19.99"
    assert data["coupon_code"] == "SAVE20"
    assert data["description"] == "This is an amazing product, enjoy the deal."
    assert data["upvotes"] == 150
    assert data["downvotes"] == 5
    assert data["comment_count"] == 42
    assert "Electronics" in data["tags"]
    assert "Deals" in data["tags"]
    assert data["external_domain"] == "external-store.com"
    assert data["posted_date"] == "13/12/2025 - 09:30"
    assert data["id"] == "node/123456"
    assert data["is_expired"] == False

def test_fast_scraper_parsing(scraper, mocker):
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
    
    data = scraper.scrape_deal_fast("https://www.ozbargain.com.au/node/999999")
    
    assert data["title"] == "Fast Deal $10.00"
    assert data["description"] == "Fast meta desc"
    assert data["coupon_code"] == "FAST10"
    assert data["tags"] == ["Fast"]
    assert data["is_expired"] == True
    assert data["id"] == "node/999999"
