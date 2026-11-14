"""The public brief and private dashboard have separate entry points."""
from html.parser import HTMLParser
from pathlib import Path
import tempfile
import unittest
from app import create_app

WEBSITE = Path(__file__).resolve().parents[1] / 'web' / 'public'


class Document(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.forms = []
        self.fields = []
        self.links = []
        self.feed(markup)

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        if tag == 'form':
            self.forms.append(attributes.get('id'))
        if tag in ('input', 'select', 'textarea') and attributes.get('name'):
            self.fields.append((tag, attributes))
        if tag == 'a':
            self.links.append(attributes)


class WebEntrypoints(unittest.TestCase):
    def test_local_home_and_review_open_dashboard_with_public_form_link(self):
        with tempfile.TemporaryDirectory() as folder:
            client = create_app(folder).test_client()
            for route in ('/', '/review'):
                with self.subTest(route=route):
                    response = client.get(route)
                    self.assertEqual(response.status_code, 200)
                    markup = response.get_data(as_text=True)
                    response.close()
                    self.assertIn('id="import-brief"', markup)
                    self.assertIn('assets/review.js', markup)
                    self.assertIn('Client property form →', markup)
                    links = [link for link in Document(markup).links if link.get('class') == 'header-link']
                    self.assertEqual([link.get('href') for link in links], ['https://lacewinganalytics.co.uk/#contact'])
                    self.assertNotIn('id="brief-form"', markup)

    def test_temporary_local_brief_is_retired(self):
        with tempfile.TemporaryDirectory() as folder:
            client = create_app(folder).test_client()
            for route in ('/brief', '/assets/local-intake.js', '/assets/local-brief.css'):
                with self.subTest(route=route):
                    response = client.get(route)
                    self.assertEqual(response.status_code, 404)
                    response.close()

    def test_public_index_embeds_brief_without_local_assets(self):
        landing = (WEBSITE / 'index.html').read_text()
        embedded = Document(landing)
        self.assertEqual(embedded.forms, ['brief-form'])
        field_names = {attributes['name'] for _, attributes in embedded.fields}
        self.assertTrue({'name', 'email', 'address', 'postcode', 'terms_accepted'} <= field_names)
        self.assertIn('id="property-brief-script"', landing)
        self.assertIn('id="terms-document"', landing)
        self.assertIn('id="privacy-document"', landing)
        self.assertIn('Download brief as JSON', landing)
        self.assertNotIn('assets/intake.js', landing)
        self.assertNotIn('assets/style.css', landing)
        self.assertNotIn('127.0.0.1', landing)
        self.assertNotIn('Analyst dashboard', landing)
        self.assertFalse(any(link.get('id') == 'review-link' for link in embedded.links))


if __name__ == '__main__':
    unittest.main()
