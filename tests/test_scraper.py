import unittest
from unittest.mock import MagicMock, patch
import sys

# Mock playwright before it's imported by scraper
mock_playwright = MagicMock()
sys.modules['playwright'] = mock_playwright
sys.modules['playwright.sync_api'] = mock_playwright

from ozbargain.core.scraper import OzBargainScraper

class TestOzBargainScraper(unittest.TestCase):
    def setUp(self):
        self.scraper = OzBargainScraper(headless=True)

    @patch('requests.Session.get')
    def test_scrape_deal_fast_success(self, mock_get):
        # Mock Response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '<html><title>Test Deal - OzBargain</title><body><div class="taxonomy"><a>Tag1</a></div></body></html>'
        mock_response.url = "https://www.ozbargain.com.au/node/123456"
        mock_get.return_value = mock_response

        url = "https://www.ozbargain.com.au/node/123456"
        result = self.scraper.scrape_deal_fast(url)

        self.assertEqual(result['id'], 'node/123456')
        self.assertEqual(result['title'], 'Test Deal')
        self.assertIn('Tag1', result['tags'])
        self.assertEqual(result['is_expired'], False)

    @patch('requests.Session.get')
    def test_scrape_deal_fast_expired(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '<html><title>Expired Deal - OzBargain</title><body><div class="node-expired">Expired</div></body></html>'
        mock_response.url = "https://www.ozbargain.com.au/node/654321"
        mock_get.return_value = mock_response

        url = "https://www.ozbargain.com.au/node/654321"
        result = self.scraper.scrape_deal_fast(url)

        self.assertEqual(result['is_expired'], True)

    @patch('requests.Session.get')
    def test_scrape_deal_fast_error(self, mock_get):
        mock_get.side_effect = Exception("Connection Error")

        url = "https://www.ozbargain.com.au/node/111"
        result = self.scraper.scrape_deal_fast(url)

        self.assertIn('error', result)
        self.assertEqual(result['error'], 'Connection Error')

if __name__ == '__main__':
    unittest.main()
