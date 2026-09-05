"""Shared helpers for the linkedin-jobhunt pipeline.

Includes: loading config, normalizing time, normalizing text, and splitting
work mode and location out of a LinkedIn location string.
"""
import json, os, re, sys, hashlib
from datetime import datetime, timezone, timedelta

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(SKILL_DIR, 'config.json')


def load_config(path=None):
    with open(path or CONFIG_PATH, encoding='utf-8') as f:
        return json.load(f)

PROFILE_PATH = os.path.join(SKILL_DIR, 'profile.json')
TAXONOMY_PATH = os.path.join(SKILL_DIR, 'taxonomy.json')


def load_profile(path=None):
    """Load the candidate profile (digitized CV).

    Falls back to profile.example.json so a fresh clone still imports and can be
    tested. Scoring against example data is meaningless, hence the warning.
    """
    target = path or PROFILE_PATH
    if not os.path.exists(target):
        example = os.path.join(SKILL_DIR, 'profile.example.json')
        if os.path.exists(example):
            print('WARNING: profile.json not found, using example data. '
                  'Run scripts/build_profile.py <your cv> first.', file=sys.stderr)
            target = example
    with open(target, encoding='utf-8') as f:
        return json.load(f)


def load_taxonomy(path=None):
    """Shared dictionary: tech_vocab, seniority_bands, market_signals, scoring."""
    with open(path or TAXONOMY_PATH, encoding='utf-8') as f:
        return json.load(f)


def flat_skills(profile):
    """Merge core/strong/familiar into a {skill: weight} dict, drop _comment keys."""
    out = {}
    for group in ('core', 'strong', 'familiar'):
        for k, v in (profile['skills'].get(group) or {}).items():
            if not k.startswith('_'):
                out[k] = v
    return out



# ---------- time ----------

_AGO_UNITS = {'second': 1 / 3600, 'minute': 1 / 60, 'hour': 1,
              'day': 24, 'week': 24 * 7, 'month': 24 * 30, 'year': 24 * 365}


def parse_ago(s):
    """'5 hours ago' -> 5.0 hours. Returns None if it cannot be parsed."""
    s = (s or '').lower()
    if not s:
        return None
    if 'just now' in s or 'moments ago' in s:
        return 0.0
    m = re.search(r'(\d+)\s*(second|minute|hour|day|week|month|year)s?', s)
    if not m:
        return None
    return int(m.group(1)) * _AGO_UNITS[m.group(2)]


def parse_iso(s):
    """ISO UTC -> aware datetime. None if malformed."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace('Z', '+00:00'))
    except Exception:
        return None


def age_hours(item, now=None):
    """Age of the item in hours. Prefers postedDate (exact) then postedAgo.

    Returns None when there is no time information.
    """
    now = now or datetime.now(timezone.utc)
    dt = parse_iso(item.get('postedDate'))
    if dt:
        return (now - dt).total_seconds() / 3600
    return parse_ago(item.get('postedAgo'))


def iso_utc(item, now=None):
    """Returns an ISO UTC timestamp for every item, even a post that only has postedAgo.

    A post back-computed from postedAgo is therefore an approximate value.
    """
    now = now or datetime.now(timezone.utc)
    dt = parse_iso(item.get('postedDate'))
    if dt:
        return dt.astimezone(timezone.utc).isoformat(timespec='seconds')
    ago = parse_ago(item.get('postedAgo'))
    if ago is not None:
        return (now - timedelta(hours=ago)).isoformat(timespec='seconds')
    return ''


def human_age(hours):
    """3.5 -> '3 giờ trước'."""
    if hours is None:
        return ''
    if hours < 1:
        return f'{int(round(hours * 60))} phút trước'
    if hours < 24:
        return f'{int(hours)} giờ trước'
    return f'{int(hours // 24)} ngày trước'


# ---------- text ----------

def norm(s):
    """Lowercase, collapse whitespace, strip decorative punctuation."""
    s = (s or '').lower()
    s = re.sub(r'[\u2018\u2019\u201c\u201d]', "'", s)
    s = re.sub(r'\s+', ' ', s)
    return s.strip()


def content_hash(item):
    """Hash first 200 alnum chars to catch duplicate-content posts at different URLs."""
    base = item.get('content') or f"{item.get('title', '')}|{item.get('company', '')}"
    slug = re.sub(r'[^a-z0-9]', '', norm(base))[:200]
    if len(slug) < 24:
        return None
    return hashlib.sha1(slug.encode()).hexdigest()


_KW_CACHE = {}


def _kw_re(kw):
    """Whole-word matching regex, blocks 'gc' matching inside 'gcp' or 'opt' inside 'option'.

    A keyword that starts or ends with a non-alphanumeric character (.net, c#, ci/cd)
    drops the boundary anchor on that side, otherwise '.net' would never match inside
    'asp.net'.
    """
    if kw not in _KW_CACHE:
        head = r'(?<![a-z0-9])' if kw[:1].isalnum() else ''
        tail = r'(?![a-z0-9])' if kw[-1:].isalnum() else ''
        _KW_CACHE[kw] = re.compile(head + re.escape(kw) + tail)
    return _KW_CACHE[kw]


# Multiple spellings of the same technology. Grouped so we don't double-count
# 'node' and 'node.js', or triple-count java / spring / spring boot.
KW_FAMILY = {
    'nodejs': 'node.js', 'node': 'node.js',
    'spring boot': 'java', 'spring': 'java',
    '.net core': '.net', 'c#': '.net', 'vb.net': '.net',
    'k8s': 'kubernetes', 'postgres': 'postgresql',
    'golang': 'go', 'adf': 'azure data factory',
}


def canon(kw):
    return KW_FAMILY.get(kw, kw)


def any_kw(text, keywords):
    """Returns the list of keywords that match whole words in text."""
    t = norm(text)
    return [k for k in keywords if _kw_re(k).search(t)]


def any_kw_family(text, keywords):
    """Like any_kw but collapses variants of the same technology to one representative."""
    seen, out = set(), []
    for k in any_kw(text, keywords):
        c = canon(k)
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


# ---------- location ----------


_WORK_MODE_RE = re.compile(r'\((remote|hybrid|on-?site)\)\s*$', re.I)


def split_location(raw):
    """'Hanoi, Vietnam (On-site)' -> ('Hanoi, Vietnam', 'Onsite').

    Returns (place, mode) where mode is one of {Remote, Hybrid, Onsite, ''}.
    """
    raw = (raw or '').strip()
    if not raw:
        return '', ''
    m = _WORK_MODE_RE.search(raw)
    if not m:
        return raw, ''
    mode = m.group(1).lower().replace('-', '')
    mode = {'remote': 'Remote', 'hybrid': 'Hybrid', 'onsite': 'Onsite'}[mode]
    return raw[:m.start()].strip().rstrip(',').strip(), mode


_VN = ['vietnam', 'viet nam', 'hanoi', 'ha noi', 'ho chi minh', 'hcmc', 'da nang', 'danang']
