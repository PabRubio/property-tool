"""Per-report text and presentation edits; calculated values remain model-owned."""
import copy
import hashlib
import re


STYLE_DEFAULTS = {'accent_color': '#19766e', 'heading_color': '#18333c',
                  'font_family': 'Helvetica', 'font_scale': 1.0, 'heading_size': 23}
FONTS = {'Helvetica': 'Helvetica-Bold', 'Times-Roman': 'Times-Bold', 'Courier': 'Courier-Bold'}


class ReportEditor:
    def __init__(self, record):
        self.settings = record.get('presentation', {})
        self.style = dict(STYLE_DEFAULTS, **self.settings.get('style', {}))
        self.catalog = {}
        self.page = 0

    def text(self, value, kind='label'):
        original = str(value)
        key = hashlib.sha256((kind + '\0' + original).encode()).hexdigest()[:20]
        text = self.settings.get('text', {}).get(key, original)
        item = self.catalog.setdefault(key, {'original': original, 'text': text, 'kind': kind, 'pages': []})
        if self.page not in item['pages']:
            item['pages'].append(self.page)
        return text


def apply_presentation(record, text_edits, style_changes, page_order):
    settings = copy.deepcopy(record.get('presentation', {}))
    text = settings.setdefault('text', {})
    catalog = record.get('report_document', {})
    if not isinstance(text_edits, list) or len(text_edits) > 100:
        raise ValueError('Invalid report text edits')
    seen = set()
    for edit in text_edits:
        if not isinstance(edit, dict) or set(edit) != {'id', 'text'} or not isinstance(edit['id'], str) or edit['id'] not in catalog or edit['id'] in seen:
            raise ValueError('The requested report text could not be identified')
        seen.add(edit['id'])
        value = edit['text']
        if not isinstance(value, str) or not value.strip() or len(value) > 3000:
            raise ValueError('Report text must contain between one and 3000 characters')
        source = catalog[edit['id']]
        if source['kind'] == 'explanation':
            # Reword generated explanations without changing their figures or citations.
            tokens = lambda s: re.findall(r'[£$€]?[-−]?\d[\d,.]*(?:%|x)?|\[[^\]]+\]', s)
            if tokens(value) != tokens(source['original']):
                raise ValueError('Change numerical inputs to update report figures; keep source references in explanations')
        text[edit['id']] = value.strip()
    if not isinstance(style_changes, list) or len(style_changes) > len(STYLE_DEFAULTS):
        raise ValueError('Invalid report style edits')
    style = settings.setdefault('style', {})
    seen = set()
    for change in style_changes:
        if not isinstance(change, dict) or set(change) != {'key', 'value'} or not isinstance(change['key'], str) or change['key'] not in STYLE_DEFAULTS or change['key'] in seen:
            raise ValueError('Unsupported or duplicate report style setting')
        key, value = change['key'], change['value']; seen.add(key)
        if key.endswith('_color'):
            if not isinstance(value, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', value):
                raise ValueError('Report colours must use six-digit hex codes')
        elif key == 'font_family':
            if not isinstance(value, str) or value not in FONTS:
                raise ValueError('Choose Helvetica, Times-Roman or Courier for the report font')
        elif isinstance(value, bool) or not isinstance(value, (int, float)) or not ((.8 <= value <= 1.2) if key == 'font_scale' else (16 <= value <= 26)):
            raise ValueError('Report text size is outside the supported page layout')
        style[key] = value
    if page_order is not None:
        if not isinstance(page_order, list) or len(page_order) != 10 or any(type(n) is not int for n in page_order) or sorted(page_order) != list(range(1, 11)):
            raise ValueError('Page order must contain each of the ten report pages once')
        settings['page_order'] = page_order
    return settings
