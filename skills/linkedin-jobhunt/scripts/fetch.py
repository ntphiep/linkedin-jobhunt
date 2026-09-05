"""Fallback path: call HarvestAPI directly when the linkedin MCP fails to load.

Reads the query matrix from config.json and writes the same format the MCP
produces ({"data": [...], "pagination": {...}}), so later steps can use it
the same way.

The API key comes from the HARVESTAPI_API_KEY env var; failing that, it's
read from mcpServers.linkedin.env in the project's .claude/settings.local.json.

Usage:
  python fetch.py jobs  <out_dir> [--posted-limit 24h] [--max 25]
  python fetch.py posts <out_dir> [--posted-limit 24h] [--max 20] [--pages 2]
"""
import sys, os, json, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from lib import load_config, SKILL_DIR

BASE = 'https://api.harvest-api.com/linkedin'
CFG = load_config()


def api_key():
    k = os.environ.get('HARVESTAPI_API_KEY')
    if k:
        return k
    # walk up from .claude/skills/<name> to the project directory
    proj = os.path.dirname(os.path.dirname(os.path.dirname(SKILL_DIR)))
    p = os.path.join(proj, '.claude', 'settings.local.json')
    try:
        with open(p, encoding='utf-8') as f:
            return json.load(f)['mcpServers']['linkedin']['env']['HARVESTAPI_API_KEY']
    except Exception as e:
        raise SystemExit('Không tìm được HARVESTAPI_API_KEY: ' + str(e))


def call(endpoint, params, key):
    url = BASE + endpoint + '?' + urllib.parse.urlencode(
        {k: v for k, v in params.items() if v not in (None, '')})
    # HarvestAPI returns 403 with urllib's default User-Agent, so it must be set manually
    req = urllib.request.Request(url, headers={
        'X-API-Key': key,
        'User-Agent': 'linkedin-jobhunt/2.0',
        'Accept': 'application/json',
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode('utf-8'))


def clean_job(raw):
    return {
        'id': raw.get('id'), 'title': raw.get('title'), 'url': raw.get('url'),
        'postedDate': raw.get('postedDate'),
        'company': (raw.get('company') or {}).get('name'),
        'location': (raw.get('location') or {}).get('linkedinText'),
        'easyApply': raw.get('easyApply'),
    }


def clean_post(raw):
    eng = raw.get('engagement') or {}
    at = raw.get('postedAt') or {}
    return {
        'id': raw.get('id'), 'linkedinUrl': raw.get('linkedinUrl'),
        'content': raw.get('content'),
        'authorName': (raw.get('author') or {}).get('name'),
        'authorType': (raw.get('author') or {}).get('type'),
        'postedAgo': at.get('postedAgoText') or at.get('postedAgoShort'),
        'likes': eng.get('likes'), 'comments': eng.get('comments'),
        'shares': eng.get('shares'),
    }


def save(out_dir, tool, payload):
    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H-%M-%S-%f')[:-3]
    path = os.path.join(out_dir, tool + '_' + ts + 'Z.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    return path


def run(kind, out_dir, posted_limit, max_items, pages):
    key = api_key()
    matrix = CFG['search_matrix'][kind]
    endpoint = '/job-search' if kind == 'jobs' else '/post-search'
    cleaner = clean_job if kind == 'jobs' else clean_post
    tool = 'search_jobs' if kind == 'jobs' else 'search_posts'

    total = 0
    for q in matrix:
        for page in range(1, pages + 1):
            params = {k: v for k, v in q.items() if not k.startswith('_') and k != 'bucket'}
            params['postedLimit'] = posted_limit
            params['page'] = page
            label = q.get('bucket', '') + ' ' + q.get('search', '')
            try:
                data = call(endpoint, params, key)
            except Exception as e:
                print('  LỖI [' + label.strip() + ' p' + str(page) + ']: ' + str(e),
                      file=sys.stderr)
                continue
            els = (data.get('elements') or [])[:max_items]
            cleaned = [cleaner(e) for e in els]
            save(out_dir, tool, {'data': cleaned, 'pagination': data.get('pagination')})
            total += len(cleaned)
            print('  [' + label.strip() + ' p' + str(page) + '] ' + str(len(cleaned)) + ' item')
            time.sleep(0.3)

    print('[fetch:' + kind + '] tổng ' + str(total) + ' item -> ' + out_dir)


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    kind, out_dir = sys.argv[1], sys.argv[2]
    if kind not in ('jobs', 'posts'):
        print(__doc__)
        sys.exit(1)

    def arg(name, default):
        return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default

    run(kind, out_dir,
        arg('--posted-limit', '24h'),
        int(arg('--max', '25' if kind == 'jobs' else '20')),
        int(arg('--pages', '1' if kind == 'jobs' else '2')))
