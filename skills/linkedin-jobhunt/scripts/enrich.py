"""Fetch the full description for each job via the /job endpoint.

Search results only have a title and location, not enough to match skills
against the CV. The /job endpoint returns descriptionText, experienceLevel,
applicant count, and industries.

Each call costs API credit, so the script does a rough pre-filter first: only
jobs whose title is related to a target role get enriched. The rest are kept
as-is and can still be scored, but the skill score will be low due to missing
data.

Usage:
  python enrich.py <merged_jobs.json> <enriched_jobs.json> [--limit 60] [--all]
"""
import sys, json, time, urllib.parse, urllib.request
from lib import load_profile, load_taxonomy, norm
from fetch import api_key, BASE

PROFILE = load_profile()
TARGETS = (PROFILE['target_roles']['primary']
           + PROFILE['target_roles']['secondary'])
AVOID = PROFILE['target_roles'].get('avoid', [])

# Title keywords worth spending credit to read the description for. Broader than
# the old list, which used to miss gcp, infrastructure, snowflake, kafka,
# streaming, warehouse, analytics...
BROAD = ['data', 'python', 'cloud', 'etl', 'elt', 'spark', 'airflow',
         'databricks', 'aws', 'azure', 'gcp', 'devops', 'platform', 'backend',
         'pipeline', 'infrastructure', 'snowflake', 'kafka', 'streaming',
         'warehouse', 'analytics', 'bi ', 'terraform', 'kubernetes', 'sre',
         'reliability', 'engineer', 'developer']


def rank_key(job):
    """Prioritizes the best-fitting jobs when the list has to be cut by --limit."""
    t = norm(job.get('title'))
    loc = norm(job.get('location'))
    score = 0
    if any(g in t for g in PROFILE['target_roles']['primary']):
        score += 10
    elif any(g in t for g in PROFILE['target_roles']['secondary']):
        score += 6
    if 'remote' in loc:
        score += 4
    if any(v in loc for v in ['vietnam', 'hanoi', 'ho chi minh']):
        score += 8
    if any(o in t for o in load_taxonomy()['seniority_bands']['over']):
        score -= 6
    return -score


def worth_enriching(job):
    """Rough title-based filter, to avoid burning credit on jobs that are clearly not a fit."""
    if job.get('description'):
        return False          # already has a description, no need to spend credit again
    t = norm(job.get('title'))
    if not t:
        return False
    if any(a in t for a in AVOID) and not any(g in t for g in TARGETS):
        return False
    return any(g in t for g in TARGETS) or any(k in t for k in BROAD)


def fetch_job(job_id, key):
    url = BASE + '/job?' + urllib.parse.urlencode({'jobId': job_id})
    req = urllib.request.Request(url, headers={
        'X-API-Key': key,
        'User-Agent': 'linkedin-jobhunt/3.0',
        'Accept': 'application/json',
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode('utf-8')).get('element') or {}


def merge_detail(job, el):
    """Merges the useful fields from /job into the job record."""
    if not el:
        return job
    job['description'] = el.get('descriptionText') or ''
    job['employmentType'] = el.get('employmentType')
    job['workplaceType'] = el.get('workplaceType')
    job['experienceLevel'] = el.get('experienceLevel')
    job['workRemoteAllowed'] = el.get('workRemoteAllowed')
    job['applicants'] = el.get('applicants')
    job['views'] = el.get('views')
    job['industries'] = el.get('industries')
    job['jobFunctions'] = el.get('jobFunctions')
    job['easyApplyUrl'] = el.get('easyApplyUrl')
    job['ats'] = el.get('applicantTrackingSystem')
    sal = el.get('salary') or {}
    job['salary_text'] = sal.get('text')
    job['salary_min'] = sal.get('min')
    job['salary_max'] = sal.get('max')
    comp = el.get('company') or {}
    if isinstance(comp, dict):
        job['company_url'] = comp.get('linkedinUrl')
        job['company_size'] = comp.get('employeeCount') or comp.get('staffCount')
    job['enriched'] = True
    return job


def main(infile, outfile, limit=60, do_all=False):
    jobs = json.load(open(infile, encoding='utf-8'))
    key = api_key()

    targets = jobs if do_all else [j for j in jobs if worth_enriching(j)]
    targets = sorted(targets, key=rank_key)[:limit]   # rank BEFORE truncating
    ids = {id(j) for j in targets}

    ok = fail = 0
    for i, j in enumerate(targets, 1):
        jid = j.get('id')
        if not jid:
            continue
        try:
            merge_detail(j, fetch_job(jid, key))
            ok += 1
        except Exception as e:
            j['enriched'] = False
            fail += 1
            print('  LỖI job ' + str(jid) + ': ' + str(e), file=sys.stderr)
        if i % 10 == 0:
            print('  ... ' + str(i) + '/' + str(len(targets)))
        time.sleep(0.25)

    for j in jobs:
        if id(j) not in ids:
            j.setdefault('enriched', False)

    with open(outfile, 'w', encoding='utf-8') as f:
        json.dump(jobs, f, ensure_ascii=False, indent=1)

    avg = 0
    got = [len(j.get('description') or '') for j in jobs if j.get('enriched')]
    if got:
        avg = sum(got) // len(got)
    print('[enrich] ' + str(len(jobs)) + ' job, làm giàu ' + str(ok)
          + ' (lỗi ' + str(fail) + ', bỏ qua ' + str(len(jobs) - len(targets)) + ')')
    print('         mô tả trung bình ' + str(avg) + ' ký tự -> ' + outfile)


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    def arg(name, default):
        return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default

    main(sys.argv[1], sys.argv[2],
         int(arg('--limit', '60')), '--all' in sys.argv)
