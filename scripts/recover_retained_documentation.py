"""Recover page-scoped, review-only statements from historical documentation Items."""
import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

SHA = re.compile(r'[0-9a-f]{64}')
# Bounded selectors for actual historical failure clusters. No generic keyword
# matches, child-link inference, code execution, or reconstructed HTML.
RULE_TEXT = r'''google_antigravity_docs|Google Antigravity|workspace_scope|Agents operate within Projects
 google_antigravity_docs|Google Antigravity local mode|runtime|Local mode: The agent operates directly
 gemini_cli_docs|Gemini CLI|product_role|Gemini CLI brings the power
 lovable_docs|Lovable|product_role|Lovable lets individuals and teams build
 lovable_docs|Lovable|application_architecture|You describe what you want to build
 devin_docs|Devin|product_role|Devin is an autonomous AI software engineer
 devin_docs|Devin|constraint|In some cases Devin may not function
 devin_docs|Devin|access_path|Devin is also available via the Devin API
 deepseek_docs|DeepSeek API|api_compatibility|The DeepSeek API uses an API format
 xai_docs|Grok API|modalities|Build with the Grok API:
 perplexity_docs|Orchestrator API|model_inference|Orchestrator API\nFrontier and open-weight models
 perplexity_docs|Agent API|agent_tools|Agent API\nGet web-grounded answers with citations\. Use frontier
 perplexity_docs|Search API|data_format|Search API\nGet ranked web results as JSON
 together_ai_docs|Together AI inference API|model_inference|Call an AI model\nRun leading open-weight models
 together_ai_docs|Together AI GPU clusters|deployment|Launch a GPU cluster\nSpin up GPU clusters
 groqcloud_docs|GroqCloud API|api_compatibility|Welcome\nFast LLM inference, OpenAI-compatible
 ollama_docs|Ollama|product_role|Use open models in your desktop apps
 ollama_docs|Ollama cloud models|deployment|Cloud models\nRun models without a local GPU
 ollama_docs|Ollama API|api_compatibility|Build an application\nCall cloud models with Ollama
 ibm_watsonx_ai_docs|watsonx.ai POST /ml/v1/text/generation|lifecycle_notice|Infer text\nPOST /ml/v1/text/generation\nInfer the next tokens[^\n]*\.\nThis API is legacy
 oracle_oci_generative_ai_docs|OCI Generative AI|product_role|Generative AI is Oracle.s Enterprise AI Platform
 oracle_oci_generative_ai_docs|OCI Generative AI|deployment|Access pretrained models or import your own
 oracle_oci_generative_ai_docs|OCI Generative AI|agent_tools|Combine tools, memory, retrieval
 nebius_ai_cloud_docs|Nebius AI Cloud|deployment|Everything you need to deploy, scale and manage
 nvidia_dgx_cloud_lepton_docs|DGX Cloud Lepton|product_role|DGX Cloud Lepton is a fully managed AI platform
 nvidia_dgx_cloud_lepton_docs|DGX Cloud Lepton endpoints|deployment|Endpoints: Deploy AI models as endpoints
 digitalocean_gradient_ai_docs|DigitalOcean Inference|deployment|Inference provides a single control plane[^\n]*?\. It includes a Model Catalog
 reka_ai_docs|Reka API|api_compatibility|The Reka API serves Reka models
 arcee_ai_docs|Arcee Platform|model_inference|Arcee Platform offers a variety of open models
 chutes_ai_docs|Chutes|product_role|Chutes is a decentralized, serverless inference platform
 chutes_ai_docs|Chutes|sdk|These docs help you build, deploy, and operate chutes
 stability_ai_docs|Stability AI Platform API|modalities|The Stability AI Platform API lets developers
 typesafe_ai_docs|TypeSafe Jev|data_format|Jev evaluates typed questions
 typesafe_ai_docs|TypeSafe Jev|constraint|Some question types also return confidence
 weaviate_docs|Weaviate Database|product_role|Weaviate \(we-vee-eight\) is an open-source, AI vector database
 redis_vector_search_docs|Redis|data_management|Redis stores and indexes vector embeddings
 singlestore_docs|SingleStore Helios|lifecycle_notice|Helios features are now enabled during weekly update windows
 mixedbread_ai_docs|Mixedbread Search API|product_role|Mixedbread is an API for integrating fast, multimodal search
 mixedbread_ai_docs|Mixedbread Search API|modalities|Upload PDFs, images, documents, code, or video
 deepset_haystack_docs|Haystack|product_role|Haystack is an open-source AI framework
 deepset_haystack_docs|Haystack|workflow|Build pipelines using reusable components
 tavily_docs|Tavily|product_role|Tavily is the web layer for AI agents:
 tavily_docs|Tavily MCP server|agent_integrations|To use the MCP server in Codex instead
 weights_biases_weave_docs|W&B Weave|observability|W&B Weave is an observability and evaluation platform
 weights_biases_weave_docs|W&B Weave / CoreWeave Agent Lens|lifecycle_notice|Weave.s agent tracing workflows are also available in CoreWeave Agent Lens
 temporal_docs|Temporal|product_role|Temporal is an open-source platform
 inngest_docs|Inngest|workflow|Inngest is the platform for building durable workflows
 inngest_docs|Inngest|runtime|Inngest runs each step, saves its result
 inngest_docs|Inngest SDK|sdk|TypeScript, Python, and Go SDKs, plus the REST API
 laminar_docs|Laminar|observability|Laminar is an open-source observability platform
 laminar_docs|Laminar|deployment|Get started with Laminar Cloud or self-host Laminar
 letta_docs|Letta Code|product_role|Use Letta Code to create coding agents
 letta_docs|Letta Code|licensing|The Letta Code harness is fully open source
 coderabbit_docs|CodeRabbit|product_role|CodeRabbit helps you decide which changes to trust:
 coderabbit_docs|CodeRabbit Verify|runtime|CodeRabbit Verify\nTest pull requests and user journeys
 coderabbit_docs|CodeRabbit Secure|security|CodeRabbit Secure\nScan repositories for code vulnerabilities
 aider_docs|Aider|product_role|Aider is AI pair programming in your terminal
 warp_docs|Warp|product_role|Warp combines a modern terminal
 warp_docs|Warp Agent|deployment|With Warp, you can run commands in a desktop terminal
 gitlab_duo_docs|GitLab Duo|agent_tools|GitLab Duo includes agentic capabilities[^\n]*\n\(AI assistance
 gitlab_duo_docs|GitLab Duo|access_path|GitLab Duo features are available in IDE extensions
 docker_ai_docs|Docker Agent|product_role|Docker Agent is an open-source framework\s+for building teams
 flutterflow_docs|FlutterFlow Studio|product_role|FlutterFlow Studio is a visual development environment
 bubble_docs|Bubble|product_role|Bubble lets you turn your ideas into apps
 figma_developer_platform_docs|Figma API|data_management|The Figma API supports access[^\n]*?\. This gives you the ability to do things such as view and extract
 figma_developer_platform_docs|Figma API|access_auth|The Figma API is based on the REST structure\. We support authentication via access tokens and OAuth2
 canva_developers_docs|Canva REST APIs|data_management|You can use the REST APIs to build web apps
 bria_ai_docs|Bria Fibo|modalities|Bria.s Fibo models generate and edit images and video
 bria_ai_docs|Bria Build|sdk|This site documents Bria Build, the developer platform:
 photoroom_api_docs|Photoroom API|modalities|The Photoroom API enables you[^\n]*?\.\nIt allows you to separate a subject from its background
 hyper3d_rodin_docs|Rodin API|modalities|Rodin is an HTTP API for creating 3D assets
 hyper3d_rodin_docs|Rodin API|access_auth|Protected endpoints use Bearer authentication
 hyper3d_rodin_docs|Rodin API|runtime|Rodin generation is asynchronous
 krea_ai_docs|Krea developer API|product_role|Guides for every creative tool in Krea, and an API
 remove_bg_api_docs|remove.bg background removal|lifecycle_notice|Starting December 1, 2026, background removal moves
 apify_docs|Apify Actors|deployment|Actors\nDevelop, run, and share web scraping and automation tools
 apify_docs|Apify MCP server|agent_integrations|MCP\nDiscover and use Actors with AI agents
 apify_docs|Apify API|access_path|Apify API\nInteract with the Apify platform
 zyte_docs|Scrapy Cloud|deployment|Run your code on Scrapy Cloud
 zyte_docs|Zyte API|agent_tools|Get powerful browser automation with Zyte API
 oxylabs_docs|Oxylabs|product_role|Oxylabs provides tools and infrastructure for accessing publicly available web data
 scrapingbee_docs|ScrapingBee HTML API|access_auth|All requests are authenticated using your private API key
 scrapingbee_docs|ScrapingBee HTML API|lifecycle_notice|Deprecation notice: passing your API key through the api_key query string parameter is deprecated\. It still works[^\n]*?\. The query parameter may be removed
 scrapingbee_docs|ScrapingBee HTML API|runtime|By default, ScrapingBee fetches the URL[^\n]*?\. This is the default behavior and costs
 scraperapi_docs|ScraperAPI|access_auth|All ScraperAPI requests must be authenticated
 scraperapi_docs|ScraperAPI|constraint|Note: there is a 50MB request size limit
 serpapi_docs|SerpApi Google Search API|product_role|Our Google Search API allows you to scrape results
 prime_intellect_docs|Prime Inference|api_compatibility|Inference\nUse hosted models through an OpenAI-compatible API'''


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def rules():
    result = defaultdict(list)
    for line in RULE_TEXT.splitlines():
        sid, subject, topic, prefix = line.strip().split('|', 3)
        # The prefix may explicitly span a wrapped sentence or a section label.
        # Otherwise stop at a complete sentence on the same physical line.
        pattern = re.compile(r'(?:^|(?<=\. ))(' + prefix + r'[^\n]{0,600}?[.!?](?=\s|$))', re.M)
        result[sid].append((subject, topic, pattern))
    return result


RULES = rules()


def exclusion(item):
    if item.get('source_product_title_conflict') or item.get('documentation_scope_review_reason') or item.get('error') == 'documentation_product_scope_ambiguous':
        return 'product_scope_review_required'
    if item.get('freshness_warnings') or item.get('error') == 'server_cached_response_over_one_day':
        return 'freshness_review_required'
    if item.get('documentation_canonical_relation') not in {'equivalent_path', 'missing'}:
        return 'canonical_review_required'
    if (item.get('quality_axes', {}).get('content_capture_status') != 'text_observed_unverified'
            or item.get('documentation_scope_status') in {'index_only', 'insufficient_content'}):
        return 'insufficient_or_index_only'
    if item.get('source_id') == 'browserless_docs':
        return 'embedded_setup_prompt_not_fact_evidence'
    return None


def recover_item(item):
    """Return exact evidence statements, not affirmative capability flags."""
    reason = exclusion(item)
    if reason:
        return reason, []
    field = 'text' if item.get('text') else 'text_sample'
    text = item.get(field, '')
    if not isinstance(text, str):
        raise ValueError('Invalid retained text field')
    if not text and not item.get('sections'):
        return 'no_retained_text', []
    candidates, seen = [], set()
    sid = item['source_id']
    for subject, topic, pattern in RULES.get(sid, ()):
        matches = list(pattern.finditer(text[:32000]))
        # Multiple occurrences are ambiguous in flattened evidence. Do not
        # select the first or assume both are equally authoritative.
        if len(matches) > 1:
            continue
        if matches:
            m = matches[0]
            raw = m[1]
            start, end = m.span(1)
            if end == 32000 and len(text) > end:
                continue
            locator = {'field': field, 'start': start, 'end': end}
            matching_sections = [s for s in item.get('sections', [])
                                 if s.get('section_id') and raw in s.get('excerpt', '')]
            if len(matching_sections) == 1:
                locator['section_id'] = matching_sections[0]['section_id']
                locator['section_heading'] = matching_sections[0].get('heading')
        else:
            # An omitted text body can still have retained section evidence.
            # Require an exact, unique match with a complete boundary.
            section_matches = []
            for index, section in enumerate(item.get('sections', [])):
                excerpt = section.get('excerpt', '')
                if not section.get('section_id') or not isinstance(excerpt, str):
                    continue
                for m in pattern.finditer(excerpt):
                    if section.get('excerpt_truncated') and m.end(1) == len(excerpt):
                        continue
                    section_matches.append((index, section, m))
            if len(section_matches) != 1:
                continue
            index, section, m = section_matches[0]
            raw = m[1]
            start, end = m.span(1)
            locator = {'field': 'sections.excerpt', 'section_index': index, 'section_id': section['section_id'],
                       'section_heading': section.get('heading'), 'start': start, 'end': end}
        if len(raw) > 900 or len(raw.split()) < 4 or raw in seen:
            continue
        seen.add(raw)
        blockers = ['independent_fact_review_required', 'publisher_reuse_review_required',
                    'canonical_product_mapping_review_required', 'single_page_not_full_corpus']
        if item.get('documentation_scope_status') == 'scope_not_established':
            blockers.append('original_documentation_scope_unresolved')
        if item.get('documentation_canonical_relation') == 'missing':
            blockers.append('canonical_metadata_missing')
        if locator['field'] in {'text_sample', 'sections.excerpt'} or item.get('text_truncated') or item.get('documentation_item_budget_truncated'):
            blockers.append('reduced_retained_evidence')
        if topic == 'lifecycle_notice':
            blockers.append('effective_date_and_lifecycle_review_required')
        candidate = {'source_id': sid, 'subject_label': subject, 'topic': topic,
                     'statement_kind': 'page_statement_review_candidate', 'evidence_text': raw,
                     'evidence_locator': locator, 'evidence_sha256': digest(raw),
                     'source_content_sha256': item.get('content_sha256'),
                     'source_title': item.get('title'),
                     'expected_product_id': item.get('source_expected_product_id'),
                     'original_scope_status': item.get('documentation_scope_status'),
                     'review_status': 'unverified', 'approved_for_advisor': False,
                     'product_identity_verified': False, 'all_capabilities_verified': False,
                     'normalization_blockers': blockers}
        candidate['candidate_id'] = digest({'source_id': sid, 'topic': topic, 'subject_label': subject,
                                            'evidence_sha256': candidate['evidence_sha256'], 'locator': locator})
        candidates.append(candidate)
    return ('review_candidates' if candidates else 'unresolved_no_scoped_statement'), candidates


def recover(observations):
    candidates, coverage, seen = [], [], set()
    for entry in observations:
        item, evidence = entry['item'], entry['evidence']
        if item.get('category') != 'documentation' or item.get('http_status') != 200:
            continue
        sid = item['source_id']
        if (sid in seen or entry.get('source_id') != sid or entry.get('approved_for_advisor') is not False
                or item.get('approved_for_advisor') is not False or item.get('review_status') != 'unverified'
                or item.get('public_diagnostic_publisher_rights_independently_verified') is not False
                or item.get('documentation_all_capabilities_verified') is not False
                or (not SHA.fullmatch(str(item.get('content_sha256', '')))
                    and item.get('quality_axes', {}).get('content_capture_status') == 'text_observed_unverified')
                or evidence.get('http_status') != 200 or evidence.get('job_id') != item.get('zyte_job_id')
                or any(not SHA.fullmatch(str(evidence.get(k, ''))) for k in ['items_sha256', 'requests_sha256'])
                or any(type(evidence.get(k)) is not int or evidence[k] < 0 for k in ['item_index', 'request_index'])):
            raise ValueError('Invalid or duplicate historical documentation evidence')
        seen.add(sid)
        state, rr = recover_item(item)
        for c in rr:
            c.update(source_url=item['source_url'], observed_at_utc=item['fetched_at_utc'], primary_evidence=evidence)
        candidates.extend(rr)
        coverage.append({'source_id': sid, 'original_error': item.get('error'),
                         'original_scope_status': item.get('documentation_scope_status'),
                         'existing_topic_candidates': item.get('documentation_topic_candidate_count', 0),
                         'navigation_candidates_detected': item.get('documentation_nav_candidate_total_detected', 0),
                         'candidate_count': len(rr), 'state': state, 'approved_for_advisor': False})
    if len({x['candidate_id'] for x in candidates}) != len(candidates):
        raise ValueError('Duplicate recovered candidate identity')
    report = {'kind': 'retained_documentation_recovery_NOT_VERIFIED', 'source_count': len(coverage),
              'candidate_count': len(candidates), 'sources_with_candidates': sum(bool(x['candidate_count']) for x in coverage),
              'scope_unresolved_sources_with_candidates': sum(bool(x['candidate_count']) and x['original_scope_status'] == 'scope_not_established' for x in coverage),
              'topics': dict(Counter(x['topic'] for x in candidates)),
              'coverage_states': dict(Counter(x['state'] for x in coverage)), 'coverage': coverage,
              'approved_for_advisor': False, 'independently_verified_facts': 0, 'navigation_links_promoted': 0}
    return report, candidates


def main():
    from scripts.consolidate_diagnostic_campaign import consolidate, write_private
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir', type=Path, required=True)
    parser.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args()
    _, _, observations = consolidate(args.input_dir)
    report, candidates = recover(observations)
    write_private(args.out_dir, report, report['coverage'], candidates)
    print(json.dumps({k: v for k, v in report.items() if k != 'coverage'}, sort_keys=True))


if __name__ == '__main__':
    main()
