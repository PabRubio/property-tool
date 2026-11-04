"""Branded PDFs carry their fonts and preserve explicit report font choices."""
import subprocess
import tempfile
import unittest
from pathlib import Path

from screening.reports import generate_report
from test_lacewing_updates import build


class BrandedReports(unittest.TestCase):
    def test_brand_fonts_are_embedded_in_main_and_companion_pdfs(self):
        record = build()
        with tempfile.TemporaryDirectory() as folder:
            artifacts = generate_report(record, folder)
            for key in ('pdf', 'sources_pdf', 'internal_review_pdf'):
                with self.subTest(document=key):
                    path = Path(folder) / artifacts[key]
                    fonts = subprocess.check_output(['pdffonts', str(path)], text=True)
                    self.assertIn('Inter', fonts)
                    self.assertIn('CormorantGaramond', fonts)
                    for line in fonts.splitlines()[2:]:
                        if 'Inter' in line or 'CormorantGaramond' in line:
                            self.assertRegex(line, r'yes\s+yes\s+yes')
                    text = subprocess.check_output(['pdftotext', str(path), '-'], text=True)
                    self.assertIn('Lacewing Analytics', text)

    def test_existing_font_override_still_renders(self):
        record = build()
        record['presentation'] = {'style': {'font_family': 'Times-Roman'}}
        with tempfile.TemporaryDirectory() as folder:
            artifacts = generate_report(record, folder)
            fonts = subprocess.check_output(['pdffonts', str(Path(folder) / artifacts['pdf'])], text=True)
            self.assertIn('Times-Roman', fonts)
            self.assertEqual(artifacts['page_count'], 10)


if __name__ == '__main__':
    unittest.main()
