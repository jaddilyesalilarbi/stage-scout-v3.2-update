"""Exact-source retrieval fixtures: no live network and no similar-job search."""
import json
import unittest

import requests

from enrichment_sources import retrieve


class Response:
    def __init__(self, url, data=None, text='', status=200):
        self.url, self.data, self.text, self.status_code = url, data, text, status

    def json(self):
        if self.data is None:
            raise ValueError('not JSON')
        return self.data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


class HTTP:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def get(self, url, params=None):
        self.calls.append((url, params))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def row(url, **kwargs):
    return dict(company='ACME', title='Mechanical intern', url=url, **kwargs)


def html_job(url, **kwargs):
    return '<script type="application/ld+json">' + json.dumps(dict(
        **{'@type': 'JobPosting'}, title='Mechanical intern', url=url,
        hiringOrganization={'name': 'ACME'}, description='<p>Full text</p>',
        **kwargs)) + '</script>'


class RetrievalTests(unittest.TestCase):
    def test_smartrecruiters_all_sections_without_length_cap(self):
        url = 'https://jobs.smartrecruiters.com/Acme/744000123-slug'
        api = 'https://api.smartrecruiters.com/v1/companies/Acme/postings/744000123'
        sections = {name: {'title': name, 'text': '<p>' + text + '</p>'} for name, text in [
            ('companyDescription', 'Company'), ('jobDescription', 'Long ' * 10000),
            ('qualifications', 'Qualifications'), ('additionalInformation', 'FINAL')]}
        http = HTTP(Response(api, dict(id='744000123', name='Mechanical intern',
            company={'identifier': 'ACME', 'name': 'ACME'}, active=True,
            postingUrl=url, applyUrl=url + '/apply', jobAd={'sections': sections})))
        result = retrieve(row(url), http)
        self.assertEqual(result['outcome'], 'enriched')
        self.assertEqual(result['description_status'], 'complete')
        self.assertIn('FINAL', result['description'])
        self.assertGreater(len(result['description']), 40000)
        self.assertEqual(http.calls[0][0], api)
        self.assertEqual(result['apply_url'], url + '/apply')

    def test_smartrecruiters_wrong_id_or_title_or_tenant_is_mismatch(self):
        url = 'https://jobs.smartrecruiters.com/acme/123'
        for updates in [dict(id='124'), dict(name='Electrical intern'),
                        dict(company={'identifier': 'another', 'name': 'Another'})]:
            payload = dict(id='123', name='Mechanical intern', company={'identifier': 'acme'},
                           jobAd={'sections': {'jobDescription': {'text': 'WRONG'}}})
            payload.update(updates)
            result = retrieve(row(url), HTTP(Response('https://api.smartrecruiters.com', payload)))
            self.assertEqual(result['outcome'], 'mismatch')
            self.assertEqual(result['description'], '')

    def test_oracle_legacy_fragment_exact_id_and_all_sections(self):
        url = 'https://acme.fa.us2.oraclecloud.com/?mode=jobs&site_number=CX#4439'
        api = 'https://acme.fa.us2.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails'
        http = HTTP(Response(api, {'items': [dict(Id='4439', RequisitionNumber='4439',
            Title='Mechanical intern', ExternalDescriptionStr='Description',
            ExternalResponsibilitiesStr='Responsibilities', ExternalQualificationsStr='Qualifications')]}))
        result = retrieve(row(url), http)
        self.assertEqual(result['outcome'], 'enriched')
        self.assertEqual(http.calls[0][1], {'finder': 'ById;Id=4439', 'onlyData': 'true'})
        self.assertTrue(result['detail_url'].endswith('/sites/CX/job/4439'))
        self.assertIn('Responsibilities', result['description'])
        self.assertIn('Qualifications', result['description'])

    def test_oracle_never_accepts_first_other_requisition(self):
        url = 'https://acme.fa.oraclecloud.com/?site_number=CX#4439'
        result = retrieve(row(url), HTTP(Response(url, {'items': [dict(
            Id='999', RequisitionNumber='999', Title='Mechanical intern', ExternalDescriptionStr='WRONG')]})))
        self.assertEqual(result['outcome'], 'mismatch')

    def test_lever_uses_exact_posting_and_preserves_sections(self):
        url = 'https://jobs.lever.co/acme/uuid/apply'
        api = 'https://api.lever.co/v0/postings/acme/uuid'
        payload = dict(id='uuid', text='Mechanical intern', hostedUrl=url[:-6], applyUrl=url,
            openingPlain='Opening', descriptionPlain='Body',
            lists=[{'text': 'Requirements', 'content': '<ul><li>CAD</li></ul>'}], additionalPlain='FINAL')
        result = retrieve(row(url), HTTP(Response(api, payload)))
        self.assertEqual(result['outcome'], 'enriched')
        for text in ['Opening', 'Body', 'Requirements', 'CAD', 'FINAL']:
            self.assertIn(text, result['description'])

    def test_recruitee_description_and_requirements(self):
        url = 'https://acme.recruitee.com/o/mechanical-intern/c/new'
        api = 'https://acme.recruitee.com/api/offers/mechanical-intern'
        http = HTTP(Response(api, {'offer': dict(slug='mechanical-intern', title='Mechanical intern',
            description='<p>Mission</p>', requirements='<p>FINAL</p>')}))
        result = retrieve(row(url), http)
        self.assertEqual(result['outcome'], 'enriched')
        self.assertIn('FINAL', result['description'])

    def test_workday_exact_requisition_id(self):
        url = 'https://acme.wd3.myworkdayjobs.com/en-US/Careers/job/Paris/Intern_REQ123'
        api = 'https://acme.wd3.myworkdayjobs.com/wday/cxs/acme/Careers/job/Paris/Intern_REQ123'
        http = HTTP(Response(api, {'jobPostingInfo': dict(title='Mechanical intern',
            jobReqId='REQ123', jobDescription='<p>FINAL</p>', location='Paris')}))
        result = retrieve(row(url), http)
        self.assertEqual(http.calls[0][0], api)
        self.assertEqual(result['outcome'], 'enriched')

    def test_workday_wrong_id_never_replaces_body(self):
        url = 'https://acme.wd3.myworkdayjobs.com/en-US/Careers/job/Paris/Intern_REQ123'
        result = retrieve(row(url), HTTP(Response(url, {'jobPostingInfo': dict(
            title='Mechanical intern', jobReqId='REQ124', jobDescription='WRONG')})))
        self.assertEqual(result['outcome'], 'mismatch')
        self.assertEqual(result['description'], '')

    def test_workday_requisition_contains_underscore_and_variant_suffix(self):
        url = 'https://zeiss.wd3.myworkdayjobs.com/en-US/Careers/job/Paris/Intern_JR_1053360-3'
        result = retrieve(row(url), HTTP(Response(url, {'jobPostingInfo': dict(
            title='Mechanical intern', jobReqId='JR_1053360', jobDescription='FINAL')})))
        self.assertEqual(result['outcome'], 'enriched')

    def test_ashby_board_requires_exact_url_not_similar_title(self):
        url = 'https://jobs.ashbyhq.com/acme/uuid/application'
        api = 'https://api.ashbyhq.com/posting-api/job-board/acme'
        unrelated = dict(title='Mechanical intern', jobUrl='https://jobs.ashbyhq.com/acme/other',
            descriptionHtml='WRONG')
        result = retrieve(row(url), HTTP(Response(api, {'jobs': [unrelated]})))
        self.assertEqual(result['outcome'], 'not_found')
        exact = dict(title='Mechanical intern', jobUrl=url[:-12], applyUrl=url,
            descriptionHtml='<p>FINAL</p>', isListed=True)
        result = retrieve(row(url), HTTP(Response(api, {'jobs': [unrelated, exact]})))
        self.assertEqual(result['outcome'], 'enriched')

    def test_workable_without_tenant_reverses_application_to_jsonld(self):
        url = 'https://apply.workable.com/j/5F42029A85/apply'
        detail = url[:-6]
        http = HTTP(Response(detail, text=html_job(detail)))
        result = retrieve(row(url), http)
        self.assertEqual(http.calls[0][0], detail)
        self.assertEqual(result['outcome'], 'enriched')

    def test_workable_account_api_checks_code_and_keeps_benefits(self):
        url = 'https://apply.workable.com/acme/j/5F42029A85/apply'
        api = 'https://apply.workable.com/api/v2/accounts/acme/jobs/5F42029A85/'
        http = HTTP(Response(api, dict(shortcode='5F42029A85', title='Mechanical intern',
            description='<p>Mission</p>', requirements='CAD', benefits='FINAL',
            url=url[:-6], application_url=url)))
        result = retrieve(row(url), http)
        self.assertEqual(http.calls[0][0], api)
        self.assertEqual(result['outcome'], 'enriched')
        self.assertIn('FINAL', result['description'])

    def test_workable_redirect_discovers_account_only_for_same_code(self):
        url = 'https://apply.workable.com/j/5F42029A85/apply'
        detail = 'https://apply.workable.com/withings/j/5F42029A85/'
        http = HTTP(Response(detail, text='JS shell'), Response(detail, dict(
            shortcode='5F42029A85', title='Mechanical intern', description='FINAL')))
        result = retrieve(row(url), http)
        self.assertEqual(result['outcome'], 'enriched')
        self.assertIn('/accounts/withings/', http.calls[1][0])

    def test_official_apply_link_is_preferred_to_aggregator(self):
        url = 'https://fr.indeed.com/viewjob?jk=123'
        official = 'https://jobs.lever.co/acme/uuid/apply'
        http = HTTP(Response(official, dict(id='uuid', text='Mechanical intern',
            hostedUrl=official[:-6], descriptionPlain='FINAL')))
        result = retrieve(row(url, apply_url=official), http)
        self.assertEqual(result['outcome'], 'enriched')
        self.assertTrue(http.calls[0][0].startswith('https://api.lever.co/'))

    def test_icims_synthetic_tenant_alias_is_not_company_mismatch(self):
        url = 'https://expleo-jobs-fr-fr.icims.com/jobs/56055/mechanical-intern/job'
        result = retrieve(dict(row(url), company='expleo-jobs-fr-fr'),
            HTTP(Response(url, text=html_job(url).replace('ACME', 'Expleo'))))
        self.assertEqual(result['outcome'], 'enriched')
        result = retrieve(dict(row(url), company='Other'),
            HTTP(Response(url, text=html_job(url).replace('ACME', 'Expleo'))))
        self.assertEqual(result['outcome'], 'mismatch')

    def test_successfactors_verified_title_description_fallback(self):
        url = 'https://careers.acme.test/job/Paris-Mechanical-intern/1446165433/'
        html = '<span itemprop="title">Mechanical intern</span><span itemprop="description">FINAL</span>'
        html += '<a href="/talentcommunity/apply/1446165433/">Postuler à</a>'
        result = retrieve(row(url), HTTP(Response(url, text=html)))
        self.assertEqual(result['outcome'], 'enriched')
        self.assertEqual(result['description_status'], 'partial')
        self.assertEqual(result['description'], 'FINAL')
        self.assertTrue(result['apply_url'].endswith('/1446165433/'))
        result = retrieve(dict(row(url), company='Other'), HTTP(Response(url, text=html)))
        self.assertEqual(result['outcome'], 'mismatch')

    def test_jsonld_separate_sections_and_structured_facts_retained(self):
        url = 'https://careers.acme.test/jobs/123'
        result = retrieve(row(url), HTTP(Response(url, text=html_job(url,
            qualifications='<p>CAD</p>', responsibilities='Simulation', skills='FEA',
            inLanguage='fr', employmentType='INTERN', workHours='35h'))))
        for text in ['Full text', 'CAD', 'Simulation', 'FEA']:
            self.assertIn(text, result['description'])
        self.assertEqual(result['structured']['employmentType'], 'INTERN')
        self.assertEqual(result['structured']['inLanguage'], 'fr')

    def test_jsonld_graph_and_safe_apply_anchor(self):
        url = 'https://careers.acme.test/jobs/123'
        html = html_job(url) + '<a href="/jobs/123/apply">Apply now</a>'
        result = retrieve(row(url), HTTP(Response(url, text=html)))
        self.assertEqual(result['outcome'], 'enriched')
        self.assertEqual(result['apply_url'], 'https://careers.acme.test/jobs/123/apply')

    def test_successfactors_identifier_without_jsonld_url(self):
        url = 'https://jobs.acme.test/job/Mechanical-intern/12345/'
        data = {'@graph': [{'@type': 'JobPosting', 'title': 'Mechanical intern',
            'identifier': {'value': '12345'}, 'hiringOrganization': {'name': 'ACME'},
            'description': '<p>FINAL</p>'}]}
        result = retrieve(row(url), HTTP(Response(url, text='<script type="application/ld+json">'
            + json.dumps(data) + '</script>')))
        self.assertEqual(result['outcome'], 'enriched')

    def test_jsonld_similar_job_is_never_accepted(self):
        url = 'https://careers.acme.test/jobs/123'
        result = retrieve(row(url), HTTP(Response(url, text=html_job(url.replace('123', '124')))))
        self.assertEqual(result['outcome'], 'mismatch')
        self.assertEqual(result['description'], '')

    def test_jsonld_title_mismatch(self):
        url = 'https://careers.acme.test/jobs/123'
        result = retrieve(dict(row(url), title='Electrical intern'), HTTP(Response(url, text=html_job(url))))
        self.assertEqual(result['outcome'], 'mismatch')

    def test_jsonld_company_mismatch(self):
        url = 'https://careers.acme.test/jobs/123'
        result = retrieve(dict(row(url), company='Another'), HTTP(Response(url, text=html_job(url))))
        self.assertEqual(result['outcome'], 'mismatch')

    def test_jsonld_explicit_expiration_retains_complete_archived_body(self):
        url = 'https://careers.acme.test/jobs/123'
        result = retrieve(row(url), HTTP(Response(url, text=html_job(url, validThrough='2020-01-01'))))
        self.assertEqual(result['outcome'], 'expired')
        self.assertEqual(result['availability'], 'expired')
        self.assertEqual(result['description_status'], 'complete')
        self.assertEqual(result['description'], 'Full text')

    def test_redirect_to_search_or_application_is_refused(self):
        url = 'https://careers.acme.test/jobs/123'
        for destination in ['https://careers.acme.test/jobs', url + '/apply']:
            result = retrieve(row(url), HTTP(Response(destination, text=html_job(url))))
            self.assertNotEqual(result['outcome'], 'enriched')

    def test_missing_description_uses_verified_targeted_container_only(self):
        url = 'https://careers.acme.test/jobs/123'
        html = html_job(url).replace('"<p>Full text</p>"', '""')
        html += '<nav>Navigation noise</nav><div itemprop="description"><p>FINAL</p></div>'
        result = retrieve(row(url), HTTP(Response(url, text=html)))
        self.assertEqual(result['description'], 'FINAL')
        self.assertEqual(result['description_status'], 'partial')

    def test_status_is_not_inferred_from_missing_page(self):
        url = 'https://careers.acme.test/jobs/123'
        for status, outcome, availability in [(404, 'not_found', 'unknown'),
                (410, 'expired', 'expired'), (403, 'inaccessible', 'unknown'),
                (429, 'inaccessible', 'unknown')]:
            result = retrieve(row(url), HTTP(Response(url, status=status)))
            self.assertEqual(result['outcome'], outcome)
            self.assertEqual(result['availability'], availability)

    def test_timeout_propagates_to_controller(self):
        with self.assertRaises(requests.Timeout):
            retrieve(row('https://careers.acme.test/jobs/123'), HTTP(requests.Timeout()))

    def test_unsafe_url_no_request(self):
        http = HTTP()
        result = retrieve(row('javascript:alert(1)'), http)
        self.assertEqual(result['outcome'], 'unsupported')
        self.assertFalse(http.calls)


if __name__ == '__main__':
    unittest.main()
