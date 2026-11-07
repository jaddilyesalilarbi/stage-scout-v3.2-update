"""Retrieve one historical posting by its official identity, never by similarity.

The caller owns HTTP timeouts, retries and pacing. No network session is created
here; requests exceptions intentionally propagate to the caller.
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse, urlunparse

from job_content import description_text, safe_url, split_links


def _normal(value):
    text = unicodedata.normalize('NFKD', str(value or '').casefold())
    text = ''.join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r'\b(?:h\s*[/\-]\s*f|f\s*[/\-]\s*h|m\s*[/\-]\s*f|f\s*[/\-]\s*m|m/f/d|f/m/d)\b', '', text)
    return ' '.join(re.findall(r'\w+', text))


def _title_matches(expected, actual):
    # Punctuation, accents and gender suffixes can vary across ATS exports.
    # Keeping every other word prevents a neighbouring vacancy being accepted.
    return bool(_normal(expected)) and _normal(expected) == _normal(actual)


def _result(source='', **changes):
    result = dict(outcome='unsupported', description_status='missing', availability='unknown',
        detail_url='', apply_url='', description='', source=source, confidence='none',
        matched_title='', matched_company='', matched_location='', evidence={}, structured={}, error='')
    result.update(changes)
    return result


def _body(*parts):
    return '\n\n'.join(text for part in parts if (text := description_text(part)))


def _structured(data, *keys):
    return {key: data[key] for key in keys if data.get(key) not in (None, '', [], {})}


def _location(value):
    if isinstance(value, list):
        return '; '.join(filter(None, (_location(item) for item in value)))
    if isinstance(value, dict):
        address = value.get('address') or value
        if isinstance(address, dict):
            return ', '.join(str(address[k]) for k in ('addressLocality', 'addressRegion',
                'addressCountry', 'city', 'region', 'country') if address.get(k))
        return str(address)
    return str(value or '')


def _url_key(url):
    parsed = urlparse(safe_url(url))
    return parsed.netloc.casefold(), unquote(parsed.path).rstrip('/').casefold()


def _same_detail(expected, actual):
    return bool(safe_url(actual)) and _url_key(expected) == _url_key(actual)


def _application_url(url):
    return bool(re.search(r'/(?:apply|application|c/new)(?:/|$)', urlparse(url).path, re.I))


def _get(http, url, source, params=None):
    response = http.get(url, params=params)
    status = response.status_code
    if status >= 400:
        outcome = 'expired' if status == 410 else 'not_found' if status == 404 else 'inaccessible'
        return response, _result(source, outcome=outcome,
            availability='expired' if status == 410 else 'unknown',
            evidence={'requested_url': url, 'response_url': response.url, 'http_status': status},
            error=f'HTTP {status}')
    return response, None


def _json(response, source):
    try:
        return response.json(), None
    except (ValueError, TypeError):
        return None, _result(source, outcome='inaccessible', error='Expected JSON response',
            evidence={'response_url': response.url, 'http_status': response.status_code})


def _verified(row, source, identity, title, company, location, detail, apply, body,
              *, availability='open', complete=True, evidence=None, structured=None):
    proof = dict(evidence or {}, identity=identity)
    if not identity or not _title_matches(row.get('title'), title):
        return _result(source, outcome='mismatch', matched_title=str(title or ''),
            matched_company=str(company or ''), matched_location=_location(location),
            evidence=proof, error='Official identity or title does not match archived posting')
    body = description_text(body)
    return _result(source, outcome='expired' if availability == 'expired' else 'enriched',
        availability=availability, detail_url=safe_url(detail), apply_url=safe_url(apply),
        description=body, description_status=('complete' if complete else 'partial') if body else 'missing',
        confidence='high', matched_title=str(title or ''), matched_company=str(company or ''),
        matched_location=_location(location), evidence=proof, structured=structured or {})


def _smartrecruiters(row, http, parsed):
    source = 'SmartRecruiters API'
    match = re.match(r'^/([^/]+)/(\d+)(?:-|/|$)', parsed.path)
    if not match:
        return _result(source, error='Missing official company/posting ID')
    company, posting = match.groups()
    endpoint = f'https://api.smartrecruiters.com/v1/companies/{quote(company)}/postings/{posting}'
    response, failure = _get(http, endpoint, source)
    if failure:
        return failure
    data, failure = _json(response, source)
    if failure:
        return failure
    if not isinstance(data, dict):
        return _result(source, outcome='inaccessible', error='Invalid posting object')
    employer = data.get('company') or {}
    identity = (str(data.get('id', '')) == posting
        and str(employer.get('identifier', '')).casefold() == company.casefold())
    sections = (data.get('jobAd') or {}).get('sections') or {}
    parts = []
    for section in sections.values():
        if isinstance(section, dict):
            parts.extend([section.get('title', ''), section.get('text', '')])
    detail = data.get('postingUrl') or ''
    # A returned public posting URL must preserve tenant and numeric ID.
    if detail:
        detail_match = re.match(r'^/([^/]+)/(\d+)(?:-|/|$)', urlparse(detail).path)
        identity = identity and urlparse(detail).hostname == 'jobs.smartrecruiters.com' and bool(
            detail_match and detail_match.group(1).casefold() == company.casefold()
            and detail_match.group(2) == posting)
    else:
        detail = urlunparse(parsed._replace(query='', fragment=''))
    return _verified(row, source, identity, data.get('name'), employer.get('name', company),
        data.get('location'), detail, data.get('applyUrl'), _body(*parts),
        availability='expired' if data.get('active') is False else 'open',
        structured=_structured(data, 'language', 'typeOfEmployment', 'location', 'experienceLevel',
            'department', 'industry', 'releasedDate', 'refNumber', 'active'),
        evidence={'api_url': endpoint, 'posting_id': posting, 'tenant': company})


def _oracle(row, http, parsed):
    source = 'Oracle API'
    modern = re.search(r'/sites/([^/]+)/job/([^/?#]+)', parsed.path)
    queries = parse_qs(parsed.query)
    job_id = modern.group(2) if modern else parsed.fragment
    site = modern.group(1) if modern else queries.get('site_number', ['CX'])[0]
    if not re.fullmatch(r'[\w-]+', job_id or '') or not re.fullmatch(r'[\w-]+', site):
        return _result(source, error='Missing official Oracle requisition ID')
    root = f'https://{parsed.netloc}'
    endpoint = root + '/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails'
    response, failure = _get(http, endpoint, source, {'finder': f'ById;Id={job_id}', 'onlyData': 'true'})
    if failure:
        return failure
    payload, failure = _json(response, source)
    if failure:
        return failure
    items = payload.get('items', []) if isinstance(payload, dict) else []
    if not items:
        return _result(source, outcome='not_found', evidence={'api_url': endpoint, 'requisition_id': job_id})
    # RequisitionNumber is the public identifier; some tenants also return Id.
    matches = [item for item in items if isinstance(item, dict) and str(
        item.get('RequisitionNumber') or item.get('ReqNumber') or item.get('Id') or item.get('RequisitionId') or '') == job_id]
    data = matches[0] if len(matches) == 1 else items[0]
    identity = len(matches) == 1
    detail = root + f'/hcmUI/CandidateExperience/en/sites/{quote(site)}/job/{quote(job_id)}'
    return _verified(row, source, identity, data.get('Title') or data.get('JobTitle'),
        data.get('Organization') or data.get('LegalEmployer') or row.get('company'),
        data.get('PrimaryLocation'), detail, data.get('ApplyURL') or data.get('ApplyUrl'),
        _body(*(data.get(key) for key in ('ExternalDescriptionStr', 'ExternalResponsibilitiesStr',
            'ExternalQualificationsStr'))), availability='unknown',
        structured=_structured(data, 'PrimaryLocation', 'JobType', 'WorkerType', 'JobSchedule',
            'PostedDate', 'ExternalPostedStartDate', 'ExternalPostedEndDate', 'LanguageCode',
            'RequisitionNumber', 'TravelPercentage', 'Organization', 'LegalEmployer'),
        evidence={'api_url': endpoint, 'requisition_id': job_id, 'site': site})


def _lever(row, http, parsed):
    source = 'Lever API'
    segments = parsed.path.strip('/').split('/')
    if len(segments) < 2:
        return _result(source, error='Missing official Lever posting ID')
    company, posting = segments[:2]
    host = 'api.eu.lever.co' if parsed.hostname == 'jobs.eu.lever.co' else 'api.lever.co'
    endpoint = f'https://{host}/v0/postings/{quote(company)}/{quote(posting)}'
    response, failure = _get(http, endpoint, source)
    if failure:
        return failure
    data, failure = _json(response, source)
    if failure:
        return failure
    if not isinstance(data, dict):
        return _result(source, outcome='inaccessible', error='Invalid posting object')
    expected = f'https://{parsed.hostname}/{company}/{posting}'
    detail = data.get('hostedUrl') or expected
    identity = str(data.get('id', '')) == posting and _same_detail(expected, detail)
    parts = [data.get('openingPlain') or data.get('opening'),
             data.get('descriptionPlain') or data.get('description')]
    for section in data.get('lists') or []:
        parts.extend([section.get('text'), section.get('content')])
    parts.append(data.get('additionalPlain') or data.get('additional'))
    return _verified(row, source, identity, data.get('text'), row.get('company'),
        (data.get('categories') or {}).get('location'), detail, data.get('applyUrl'), _body(*parts),
        structured=_structured(data, 'categories', 'workplaceType', 'country', 'createdAt'),
        evidence={'api_url': endpoint, 'posting_id': posting, 'tenant': company})


def _recruitee(row, http, parsed):
    source = 'Recruitee API'
    match = re.match(r'^/o/([^/]+)', parsed.path)
    if not match:
        return _result(source, error='Missing official offer slug')
    slug = match.group(1)
    endpoint = f'https://{parsed.netloc}/api/offers/{quote(slug)}'
    response, failure = _get(http, endpoint, source)
    if failure:
        return failure
    payload, failure = _json(response, source)
    if failure:
        return failure
    data = payload.get('offer', payload) if isinstance(payload, dict) else {}
    expected = f'https://{parsed.netloc}/o/{slug}'
    detail = data.get('careers_url') or expected
    identity = str(data.get('slug', '')) == slug and _same_detail(expected, detail)
    return _verified(row, source, identity, data.get('title') or data.get('position'),
        data.get('company_name') or row.get('company'), data.get('location') or data.get('city'),
        detail, data.get('careers_apply_url'), _body(data.get('description'), data.get('requirements')),
        availability='expired' if data.get('status') in ('closed', 'archived') else 'open',
        structured=_structured(data, 'location', 'locations', 'country', 'city', 'remote',
            'employment_type', 'employment_type_code', 'education', 'experience', 'category', 'schedule'),
        evidence={'api_url': endpoint, 'offer_slug': slug, 'tenant': parsed.hostname})


def _workday(row, http, parsed):
    source = 'Workday API'
    match = re.match(r'^/(?:[a-z]{2}-[A-Z]{2}/)?([^/]+)(/job/.+)', parsed.path)
    if not match:
        return _result(source, error='Missing Workday site/job path')
    site, path = match.groups()
    tenant = parsed.hostname.split('.')[0]
    expected_id = unquote(path).rsplit('_', 1)[-1]
    endpoint = f'https://{parsed.netloc}/wday/cxs/{tenant}/{quote(site)}{path}'
    response, failure = _get(http, endpoint, source)
    if failure:
        return failure
    payload, failure = _json(response, source)
    if failure:
        return failure
    data = payload.get('jobPostingInfo') or {} if isinstance(payload, dict) else {}
    returned_id = str(data.get('jobReqId') or '')
    # Workday IDs can contain underscores; the URL can add a numeric posting
    # variant (e.g. title_JR_1053360-3 for requisition JR_1053360).
    identity = bool(returned_id) and bool(re.search(
        '_' + re.escape(returned_id) + r'(?:-\d+)?$', unquote(path), re.I))
    detail = urlunparse(parsed._replace(query='', fragment=''))
    return _verified(row, source, identity, data.get('title'), row.get('company'),
        data.get('location'), detail, data.get('applyUrl'), data.get('jobDescription'),
        availability='expired' if data.get('isExpired') is True else 'open',
        structured=_structured(data, 'jobReqId', 'location', 'additionalLocations', 'timeType',
            'jobType', 'startDate', 'endDate', 'remoteType', 'jobPostingCountry', 'postedOn'),
        evidence={'api_url': endpoint, 'requisition_id': expected_id, 'tenant': tenant, 'site': site})


def _ashby(row, http, parsed):
    source = 'Ashby API'
    segments = parsed.path.strip('/').split('/')
    if len(segments) < 2:
        return _result(source, error='Missing Ashby board/posting ID')
    board, posting = segments[:2]
    endpoint = f'https://api.ashbyhq.com/posting-api/job-board/{quote(board)}'
    response, failure = _get(http, endpoint, source)
    if failure:
        return failure
    payload, failure = _json(response, source)
    if failure:
        return failure
    expected = f'https://jobs.ashbyhq.com/{board}/{posting}'
    jobs = payload.get('jobs', []) if isinstance(payload, dict) else []
    matches = [job for job in jobs if _same_detail(expected, job.get('jobUrl', ''))]
    if len(matches) != 1:
        return _result(source, outcome='not_found', evidence={'api_url': endpoint, 'posting_id': posting})
    data = matches[0]
    return _verified(row, source, True, data.get('title'), row.get('company'), data.get('location'),
        data.get('jobUrl'), data.get('applyUrl'), data.get('descriptionHtml') or data.get('descriptionPlain'),
        availability='expired' if data.get('isListed') is False else 'open',
        structured=_structured(data, 'employmentType', 'workplaceType', 'location',
            'secondaryLocations', 'isRemote', 'publishedAt', 'department', 'team'),
        evidence={'api_url': endpoint, 'posting_id': posting, 'tenant': board})


def _workable(row, http, parsed, company, posting):
    source = 'Workable API'
    endpoint = f'https://apply.workable.com/api/v2/accounts/{quote(company)}/jobs/{quote(posting)}/'
    response, failure = _get(http, endpoint, source)
    if failure:
        return failure
    data, failure = _json(response, source)
    if failure:
        return failure
    if not isinstance(data, dict):
        return _result(source, outcome='inaccessible', error='Invalid posting object')
    expected = f'https://apply.workable.com/{company}/j/{posting}'
    detail = data.get('url') or expected
    identity = str(data.get('shortcode') or data.get('code') or '').casefold() == posting.casefold()
    identity = identity and _same_detail(expected, detail)
    return _verified(row, source, identity, data.get('title'), row.get('company'),
        data.get('location'), detail, data.get('application_url') or data.get('applicationUrl'),
        _body(data.get('description'), data.get('requirements'), data.get('benefits')),
        availability='expired' if data.get('state') in ('closed', 'archived') else 'open',
        structured=_structured(data, 'location', 'locations', 'employment_type', 'experience',
            'education', 'department', 'telecommuting', 'workplace', 'published_on', 'state'),
        evidence={'api_url': endpoint, 'posting_id': posting, 'tenant': company})


class _Page(HTMLParser):
    """Capture only JSON-LD, explicit description containers and apply links."""
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.scripts, self.descriptions, self.links = [], [], []
        self.titles, self.metadata = [], {}
        self.script = None
        self.capture = None
        self.stack = []
        self.anchor = None
        self.title_capture, self.title_depth = None, 0
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        void = tag in ('br', 'img', 'hr', 'input', 'meta', 'link', 'source', 'wbr', 'area', 'base', 'embed')
        if tag == 'meta':
            self.metadata[attributes.get('property') or attributes.get('name') or ''] = attributes.get('content', '')
        if self.title_capture is not None and not void:
            self.title_depth += 1
        elif attributes.get('itemprop') == 'title' or tag == 'h1':
            self.title_capture, self.title_depth = [], 1
        if tag == 'script' and attributes.get('type', '').lower() == 'application/ld+json':
            self.script = []
        if tag == 'a':
            self.anchor = [attributes.get('href', ''), []]
        target = attributes.get('itemprop') == 'description' or bool(re.search(
            r'(?:^|[\s_-])(?:job[-_]?description|job[-_]?detail[-_]?description|jobdescription)(?:$|[\s_-])',
            attributes.get('id', '') + ' ' + attributes.get('class', ''), re.I))
        if self.capture is None and target:
            self.capture = []
            self.stack = [tag]
        elif self.capture is not None:
            self.capture.append(self.get_starttag_text())
            if not void:
                self.stack.append(tag)

    def handle_endtag(self, tag):
        if self.title_capture is not None:
            self.title_depth -= 1
            if self.title_depth == 0:
                self.titles.append(''.join(self.title_capture).strip())
                self.title_capture = None
        if tag == 'script' and self.script is not None:
            self.scripts.append(''.join(self.script))
            self.script = None
        if tag == 'a' and self.anchor:
            self.links.append((self.anchor[0], ''.join(self.anchor[1])))
            self.anchor = None
        if self.capture is not None and tag in self.stack:
            while self.stack:
                opened = self.stack.pop()
                if opened == tag:
                    break
            if self.stack:
                self.capture.append(f'</{tag}>')
            else:
                self.descriptions.append(''.join(self.capture))
                self.capture = None

    def handle_data(self, data):
        if self.title_capture is not None:
            self.title_capture.append(data)
        if self.script is not None:
            self.script.append(data)
        if self.capture is not None:
            self.capture.append(data)
        if self.anchor:
            self.anchor[1].append(data)


def _postings(value):
    if isinstance(value, list):
        for item in value:
            yield from _postings(item)
    elif isinstance(value, dict):
        types = value.get('@type', [])
        if 'JobPosting' in (types if isinstance(types, list) else [types]):
            yield value
        if '@graph' in value:
            yield from _postings(value['@graph'])


def _identifier(value):
    if isinstance(value, dict):
        return str(value.get('value') or value.get('@id') or value.get('name') or '')
    return str(value or '')


def _path_id(parsed):
    # iCIMS places its ID before the slug; SuccessFactors ends in digits.
    match = re.search(r'/jobs/(\d+)(?:/|$)', parsed.path, re.I)
    if match:
        return match.group(1)
    numbers = re.findall(r'(?:^|/)(\d+)(?=/|$)', parsed.path)
    return numbers[-1] if numbers else unquote(parsed.path.rstrip('/').split('/')[-1])


def _company_matches(expected, actual, host):
    if _normal(expected).replace(' ', '') == _normal(actual).replace(' ', '') and _normal(actual):
        return True
    # Some iCIMS datasets use the complete tenant hostname as the company.
    # Accept only this documented alias, never a different arbitrary employer.
    if host.endswith('.icims.com') and str(expected).casefold() == host.split('.')[0]:
        tenant = re.sub(r'\b(?:jobs?|careers?|uscareers|fr|us|uk|en|de|com|ca)\b', '',
                        _normal(expected))
        return bool(_normal(actual)) and _normal(tenant) == _normal(actual)
    return False


def _company_on_host(company, host):
    # This fallback is reserved for employer-hosted SuccessFactors detail URLs.
    # The brand must occur as an actual hostname label or part of its hyphenated
    # brand label; legal suffixes alone provide no evidence.
    ignored = {'international', 'group', 'groupe', 'gmbh', 'company', 'inc', 'ltd', 'sa', 's', 'a'}
    words = [word for word in _normal(company).split() if word not in ignored and len(word) >= 4]
    labels = re.split(r'[.\-]', host)
    return any(word in labels for word in words)


def _apply_link(page, url):
    for href, label in page.links:
        candidate = safe_url(urljoin(url, href))
        if candidate and re.search(r'\b(?:apply|postuler|candidater|bewerben)\b', label, re.I):
            return candidate
    return ''


def _html(row, http, url):
    source = 'Employer JobPosting JSON-LD'
    response, failure = _get(http, url, source)
    if failure:
        return failure
    original, redirected = urlparse(url), urlparse(response.url)
    if original.hostname == 'apply.workable.com' and redirected.hostname == original.hostname:
        initial_code = re.match(r'^/j/([^/]+)/?$', original.path)
        account_job = re.match(r'^/([^/]+)/j/([^/]+)/?$', redirected.path)
        if initial_code and account_job and initial_code.group(1) == account_job.group(2):
            return _workable(row, http, redirected, *account_job.groups())
    if not _same_detail(url, response.url) or _application_url(response.url):
        return _result(source, outcome='mismatch', evidence={'requested_url': url, 'response_url': response.url},
            error='Response redirected away from the exact detail page')
    page = _Page(response.text)
    jobs = []
    for script in page.scripts:
        try:
            jobs.extend(_postings(json.loads(script)))
        except (ValueError, TypeError):
            continue
    expected_id = _path_id(urlparse(url))
    matches = []
    for job in jobs:
        declared_url = job.get('url') or ''
        identifier = _identifier(job.get('identifier'))
        identity = _same_detail(url, declared_url) if declared_url else bool(
            expected_id and identifier and identifier.casefold() == expected_id.casefold())
        if identity:
            matches.append(job)
    if len(matches) != 1:
        # SuccessFactors also renders first-party semantic HTML without JSON-LD.
        # Preserve its targeted body as partial, never the surrounding page.
        sf_path = bool(re.search(r'/job/[^/]+/\d+/?$', original.path))
        titles = page.titles + [page.metadata.get('og:title', '')]
        title = next((title for title in titles if _title_matches(row.get('title'), title)), '')
        if not jobs and sf_path and page.descriptions and title:
            return _verified(row, 'Employer semantic HTML', _company_on_host(row.get('company'), original.hostname),
                title, row.get('company'), '', response.url, _apply_link(page, response.url),
                _body(*page.descriptions), availability='unknown', complete=False,
                evidence={'response_url': response.url, 'official_id': expected_id,
                    'identity_basis': 'same official job URL, matching title and employer hostname',
                    'description_selector': 'itemprop=description or jobdescription'})
        return _result(source, outcome='mismatch' if jobs else 'unsupported',
            evidence={'response_url': response.url, 'jobposting_count': len(jobs)},
            error='No unique JobPosting with the original official identity')
    job = matches[0]
    company = (job.get('hiringOrganization') or {}).get('name', '')
    company_match = _company_matches(row.get('company'), company, original.hostname)
    body = job.get('description') or ''
    complete = bool(description_text(body))
    if not complete:
        body = _body(*page.descriptions)
    body = _body(body, *(job.get(key) for key in ('responsibilities', 'qualifications', 'skills',
        'experienceRequirements', 'educationRequirements') if isinstance(job.get(key), str)))
    apply = _apply_link(page, response.url)
    availability = 'unknown'
    valid_through = job.get('validThrough')
    if valid_through:
        try:
            expiration = datetime.fromisoformat(str(valid_through).replace('Z', '+00:00'))
            if expiration.tzinfo is None:
                expiration = expiration.replace(tzinfo=timezone.utc)
            availability = 'expired' if expiration < datetime.now(timezone.utc) else 'open'
        except ValueError:
            pass
    return _verified(row, source, company_match, job.get('title'), company, job.get('jobLocation'),
        response.url, apply, body, availability=availability, complete=complete,
        structured=_structured(job, 'inLanguage', 'employmentType', 'jobLocation', 'validThrough',
            'datePosted', 'jobStartDate', 'workHours', 'experienceRequirements', 'educationRequirements',
            'qualifications', 'skills', 'responsibilities', 'eligibilityToWorkRequirement',
            'applicantLocationRequirements', 'jobLocationType', 'securityClearanceRequirement'),
        evidence={'response_url': response.url, 'official_id': expected_id,
            'jsonld_url': job.get('url', ''), 'jsonld_identifier': _identifier(job.get('identifier'))})


def retrieve(row: dict, http) -> dict:
    """Retrieve exactly the historical posting; preserve old values on mismatch.

    Returned fields contain newly verified source data only. A caller must merge
    archival values itself, including preserving bodies for failed retrievals.
    """
    candidates = [safe_url(row.get(key)) for key in ('description_url', 'url', 'apply_url')]
    def aggregator(value):
        host = (urlparse(value).hostname or '').casefold()
        return bool(re.search(r'(?:^|\.)(?:indeed\.[a-z.]+|linkedin\.com|glassdoor\.[a-z.]+)$', host))
    url = next((value for value in candidates if value and not aggregator(value)), '')
    url = url or next((value for value in candidates if value), '')
    if not url:
        return _result(error='No safe official URL')
    parsed = urlparse(url)
    host = parsed.hostname.casefold()
    if host == 'jobs.smartrecruiters.com':
        return _smartrecruiters(row, http, parsed)
    if host.endswith('.oraclecloud.com'):
        return _oracle(row, http, parsed)
    if host in ('jobs.lever.co', 'jobs.eu.lever.co'):
        return _lever(row, http, parsed)
    if host.endswith('.recruitee.com'):
        return _recruitee(row, http, parsed)
    if host.endswith('.myworkdayjobs.com'):
        return _workday(row, http, parsed)
    if host == 'jobs.ashbyhq.com':
        return _ashby(row, http, parsed)
    if host == 'apply.workable.com':
        # Public job code routes expose JSON-LD even when no account is known.
        match = re.match(r'^/(?:([^/]+)/)?j/([^/]+)(?:/apply)?/?$', parsed.path)
        if match:
            if match.group(1):
                return _workable(row, http, parsed, *match.groups())
            path = parsed.path.rstrip('/')
            if path.endswith('/apply'):
                path = path[:-6]
            url = urlunparse(parsed._replace(path=path, query='', fragment=''))
    else:
        url, _ = split_links(url, '')
    if not url or _application_url(url):
        return _result(error='Application form is not a detail page')
    return _html(row, http, url)
