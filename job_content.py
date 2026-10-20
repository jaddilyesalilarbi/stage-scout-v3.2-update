"""Content fields shared by collection, migration and the offline dashboard."""
import csv
import html
import re
from urllib.parse import urlparse, urlunparse

# Descriptions can exceed the csv module's 128 KiB default.
csv.field_size_limit(10 * 1024 * 1024)
CONTENT_FIELDS = ['description_url', 'apply_url', 'description',
                  'description_source', 'description_status']


def safe_url(value):
    value = str(value or '').strip()
    try:
        parsed = urlparse(value)
        if (parsed.scheme.lower() in ('http', 'https') and parsed.hostname
                and not parsed.username and not parsed.password
                and not re.search(r'[\x00-\x20\x7f]', value)):
            return value
    except ValueError:
        pass
    return ''


def split_links(description_url='', apply_url=''):
    """Only reverse application paths for known ATS hosts and path shapes."""
    listing, application = safe_url(description_url), safe_url(apply_url)
    candidate = listing or application
    if candidate:
        parsed = urlparse(candidate)
        host, path = parsed.hostname.lower(), parsed.path.rstrip('/')
        suffix = ''
        if host in ('jobs.lever.co', 'jobs.eu.lever.co') and re.fullmatch(r'/[^/]+/[^/]+/apply', path):
            suffix = '/apply'
        elif host == 'jobs.ashbyhq.com' and re.fullmatch(r'/[^/]+/[^/]+/application', path):
            suffix = '/application'
        elif host.endswith('.recruitee.com') and re.fullmatch(r'/o/[^/]+/c/new', path):
            suffix = '/c/new'
        if suffix:
            listing = urlunparse(parsed._replace(path=path[:-len(suffix)], fragment=''))
            application = application or candidate
    return listing, application


def description_text(value):
    """Readable plain text, keeping paragraphs and lists without a length cap."""
    text = html.unescape(str(value or ''))
    text = re.sub(r'(?is)<(script|style)\b[^>]*>.*?</\1>', '', text)
    text = re.sub(r'(?i)<li\b[^>]*>', '\n• ', text)
    text = re.sub(r'(?i)<(?:br\b[^>]*|/(?:p|div|li|ul|ol|h[1-6])\s*)>', '\n', text)
    text = re.sub(r'(?s)<[^>]+>', '', text)
    text = html.unescape(text).replace('\r\n', '\n').replace('\r', '\n')
    text = '\n'.join(re.sub(r'[^\S\n]+', ' ', line).strip() for line in text.split('\n'))
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def merge_content(job, old=None):
    """Never replace an archived body with an empty or shorter source excerpt."""
    old = old or {}
    body = job.get('description') or ''
    previous = old.get('description') or ''
    owner = old if len(previous) > len(body) else job
    body = owner.get('description') or ''
    return {
        'description_url': safe_url(job.get('description_url')) or old.get('description_url', ''),
        'apply_url': safe_url(job.get('apply_url')) or old.get('apply_url', ''),
        'description': body,
        'description_source': owner.get('description_source') or (owner.get('source', '') if body else ''),
        'description_status': owner.get('description_status') or ('source_provided' if body else 'missing'),
        'description_excerpt': body[:300] if body else old.get('description_excerpt', ''),
    }
