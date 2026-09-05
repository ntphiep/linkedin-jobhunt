"""Score jobs/posts against the candidate's real CV (profile.json).

Four scoring pillars, each corresponding to a different point of view:

  1. Skill match     (0-30)  technical hiring manager's view:
                              does the job's stack overlap what I can do
  2. Right level      (0-25)  recruiter's view:
                              would 3.4 years of experience get shortlisted
  3. Reachable        (0-30)  view of someone based in Vietnam:
                              could this job actually be gotten in practice
  4. Right profession (0-15)  career-direction view

Bonus for AWS certifications, domain match, low competition.
Heavy penalty for jobs locked to the US, out-of-reach seniority, missing
required skills, language barriers.

Usage: python score.py <input.json> <output.json> [--kind job|post]
"""
import sys, json, re
from collections import Counter
from datetime import datetime, timezone
from lib import (load_profile, load_taxonomy, norm, any_kw, any_kw_family,
                 age_hours, iso_utc, human_age, split_location, flat_skills, _VN)

P = load_profile()          # personal, generated from the CV
T = load_taxonomy()         # shared, safe to commit to git
SKILLS = flat_skills(P)
GAPS = P['skills']['gaps']['hard']
CERTS_KW = ['aws certified', 'aws certification', 'solutions architect',
            'data engineer associate', 'cloudops', 'aws cert']
MS = T['market_signals']
BANDS = T['seniority_bands']
ROLES = P['target_roles']
DOMAINS = P['domains']['experienced']
YOE = P['seniority']['years_experience']

# longer titles get matched first, so 'engineer' doesn't swallow 'data engineer'
SKILL_KEYS = sorted(SKILLS, key=len, reverse=True)
VOCAB = T['tech_vocab']

VERDICTS = [(75, 'Ứng tuyển ngay'), (60, 'Nên xem'), (45, 'Cân nhắc'), (0, 'Bỏ qua')]

# Feasible timezone regions, extra variants added so whole-word matching doesn't miss any
TZ_REGIONS = sorted(set(MS['timezone_friendly_regions'] + [
    'european', 'asia-pacific', 'asia pacific', 'apac', 'anz', 'oceania',
    'gmt', 'cet', 'aest', 'sgt', 'ict', 'utc']))

# Work-authorization constraints: JDs phrase this in countless ways, so a regex is
# needed instead of fixed phrases
US_LOCK_RE = re.compile(
    r'(?:'
    r'\bnot?\s+(?:able\s+to\s+|going\s+to\s+)?sponsor'
    r'|\bwill\s+not\s+sponsor'
    r'|\bsponsorship\s+(?:is\s+)?(?:not|un)available'
    r'|\bno\s+sponsorship'
    r'|\bwithout\s+(?:visa\s+)?sponsorship'
    r'|\bus\s+citizen(?:ship|s)?\b(?![^.]{0,40}\bnot\s+required)'
    r'|\bmust\s+be\s+a\s+us\s+person'
    r'|\bgreen\s+card\s+holders?\s+only'
    r'|\b(?:currently\s+)?authorized\s+to\s+work\s+in\s+the\s+(?:us|united\s+states)'
    r'|\bphysically\s+located\s+in\s+the\s+us'
    r'|\bsecurity\s+clearance|\bts/sci\b|\bpublic\s+trust'
    r'|\blocals?\s+only\b|\blocal\s+candidates?\s+only'
    r'|\bno\s+c2c\b|\bw2\s+only\b'
    r'|\b(?:us|pst|est|cst)\s+time\s*zone\s+(?:required|overlap)'
    r')')

# Required to reside in a specific place: a real obstacle but DIFFERENT from a
# US work-authorization lock
RESIDENCY_RE = re.compile(
    r'must\s+(?:be\s+)?(?:based|located|residing|reside)\s+in\s+([a-z ]{3,24})')

# A JD written in a language other than English is also a real barrier
FOREIGN_RE = re.compile(
    r'\b(?:und|oder|nicht|wir|sie|einen?|für|mit|zdalna|praca|oraz|jest'
    r'|para|con|los|las|una|nuestro|experiencia|capacidad|equipo'
    r'|nous|votre|vous|avec|pour|des|est)\b')


def required_years(desc):
    """Extract the years of experience the job ACTUALLY requires.

    JDs often list one primary figure and several secondary ones. min() would
    always grab the easiest figure, so a number next to the word 'experience'
    is preferred; if there is none, the largest figure is used.
    """
    near = [int(m.group(1)) for m in re.finditer(
        r'(\d{1,2})\s*\+?\s*(?:-\s*\d{1,2}\s*)?years?[^.\n]{0,40}?experience', desc)]
    if near:
        return max(near)
    allyrs = [int(m) for m in re.findall(r'(\d{1,2})\s*\+?\s*years?', desc)]
    allyrs = [y for y in allyrs if 0 < y <= 20]
    return max(allyrs) if allyrs else None


def verdict_of(score):
    for cut, label in VERDICTS:
        if score >= cut:
            return label
    return 'Bỏ qua'


# ---------- pillar 1: skill match ----------

def match_skills(text):
    """Returns (matched skills, total weight, missing skills, total tech the job asks for).

    Also measures the fulfillment ratio: a job that asks for 20 things and
    matches 10 is worse than one that asks for 8 and matches 7.
    """
    t = norm(text)
    hit, seen = [], set()
    for k in SKILL_KEYS:
        if k in seen:
            continue
        if re.search(r'(?<![a-z0-9])' + re.escape(k) + r'(?![a-z0-9])', t):
            hit.append(k)
            seen.add(k)
    missing = any_kw_family(t, GAPS)
    demanded = set(any_kw(t, VOCAB))
    weight = sum(SKILLS[k] for k in hit)
    return hit, weight, missing, len(demanded)


def score_skills(matched, weight, demanded, has_desc):
    """Combines coverage (how much of what the job asks for is matched) and depth
    (how proficient the match is)."""
    if not has_desc:
        return 0, 'chưa có mô tả job'
    if not demanded:
        return 0, 'mô tả không nêu công nghệ cụ thể'

    coverage = len(matched) / demanded           # 0..1
    depth = weight / max(len(matched), 1)        # 1..3
    breadth = min(1.0, len(matched) / 10)        # need enough matches to be credible

    raw = (coverage * 0.55 + (depth / 3) * 0.25 + breadth * 0.20)
    pts = round(min(30, raw * 30))
    note = (str(len(matched)) + '/' + str(demanded) + ' công nghệ ('
            + str(round(coverage * 100)) + '%), độ sâu ' + str(round(depth, 1)) + '/3')
    return pts, note


# ---------- pillar 2: right level ----------

def score_seniority(title, desc, exp_level):
    t = norm(title)
    d = norm(desc)

    if any_kw(t, BANDS['over']):
        return 0, 'quá tầm', ['quá tầm: tiêu đề cấp lead/architect trở lên']
    if any_kw(t, BANDS['under']):
        return 10, 'dưới tầm', ['dưới tầm: vị trí intern/fresher']

    # years required, as stated in the description
    req = required_years(d)
    flags = []
    if req is not None:
        if req > YOE + 2:
            return 4, str(req) + '+ năm (quá xa)', ['đòi ' + str(req) + '+ năm, bạn có ' + str(YOE)]
        if req > YOE:
            flags.append('đòi ' + str(req) + '+ năm, bạn có ' + str(YOE) + ' (với tay được)')
            base = 16
        else:
            base = 25
    else:
        base = 20

    if any_kw(t, BANDS['stretch_senior']):
        base = min(base, 17)
        flags.append('vị trí Senior, hơi với tay')
    if exp_level:
        el = norm(exp_level)
        if el in ('entry level', 'associate'):
            base = max(base, 24)
        elif el in ('mid-senior level', 'mid senior level'):
            base = max(base, 20)
        elif el in ('director', 'executive'):
            return 0, exp_level, ['quá tầm: ' + exp_level]

    label = str(req) + '+ năm' if req else 'không ghi rõ'
    return base, label, flags


# ---------- pillar 3: reachable ----------

def score_reach(place, mode, desc, title, remote_flag=None):
    """The pillar that matters most for someone in Vietnam: can they actually get hired."""
    blob = norm(place + ' ' + title + ' ' + desc)
    p = norm(place)
    flags = []

    us_lock = US_LOCK_RE.search(blob)
    us_lock = [us_lock.group(0)] if us_lock else []
    glob = any_kw(blob, MS['hires_globally'])
    contractor = any_kw(blob, MS['contractor_friendly'])
    tz_ok = bool(any_kw(blob, TZ_REGIONS))
    in_vn = bool(any_kw(p, _VN))

    if us_lock and not in_vn:
        hit = us_lock[0]
        # Distinguish: locked to the US market specifically, or just requiring
        # general local work authorization
        if re.search(r'\bus\b|united states|w2|c2c|pst|est|cst|clearance', hit):
            return 0, 'khoá trong Mỹ', ['khoá trong Mỹ: ' + hit]
        return 2, 'cần quyền lao động sở tại', ['không bảo lãnh visa: ' + hit]

    res = RESIDENCY_RE.search(blob)
    if res and not in_vn:
        where = res.group(1).strip()
        if not any_kw(where, _VN):
            return 4, 'buộc cư trú tại ' + where[:18], ['buộc cư trú tại ' + where[:24]]

    if in_vn:
        return 30, 'Việt Nam', []
    if remote_flag and mode != 'Remote':
        mode = 'Remote'   # LinkedIn's structured flag is more reliable than the regex
    if mode == 'Remote' and glob:
        return 28, 'remote toàn cầu', []
    if mode == 'Remote' and tz_ok:
        return 25, 'remote, múi giờ hợp', []
    if mode == 'Remote':
        flags.append('remote nhưng chưa rõ có nhận người ngoài nước không')
        return 14, 'remote, chưa rõ phạm vi', flags
    if mode in ('Hybrid', 'Onsite') and tz_ok:
        flags.append('cần có mặt tại chỗ, phải chuyển nơi ở')
        return 10, mode + ', cần chuyển chỗ', flags
    if contractor:
        return 12, 'dạng contractor', []
    flags.append('làm tại chỗ ngoài vùng khả thi')
    return 0, mode or 'không rõ', flags


# ---------- role groups, spelled out in full ----------

# ONLY these three role groups. Everything else is rejected outright, not scored.
# Python Developer is the loosest group and only ever a "last resort" fit.
ROLE_GROUPS = [
    ('Data Engineer', ['data engineer', 'data engineering', 'analytics engineer',
                       'etl developer', 'etl engineer', 'elt developer',
                       'big data engineer', 'data platform engineer',
                       'data infrastructure engineer', 'data warehouse engineer',
                       'data pipeline engineer', 'databricks engineer',
                       'snowflake engineer', 'spark engineer', 'data ops',
                       'dataops engineer']),
    ('Cloud / DevOps Engineer', ['cloud engineer', 'cloud data engineer',
                                 'devops engineer', 'devsecops engineer',
                                 'platform engineer', 'site reliability engineer',
                                 'sre', 'infrastructure engineer',
                                 'cloud infrastructure engineer',
                                 'kubernetes engineer', 'cloud operations']),
    ('Python Developer', ['python developer', 'python engineer',
                          'python backend', 'backend python',
                          'python software engineer', 'python full stack']),
]

# Rejected outright even if the title matches a group. Uses regex because a raw
# substring match kills wrongly: the keyword 'hr ' once killed
# "Data Engineer | $90/hr Remote".
HARD_EXCLUDE_RE = re.compile(
    r'\b(?:data\s+scientist|machine\s+learning|\bml\s+engineer|mlops'
    r'|ai\s*/\s*ml|genai\s+engineer|llm\s+engineer'
    r'|data\s+analyst|business\s+analyst|bi\s+(?:developer|analyst)'
    r'|front[\s-]?end|web\s+developer|ui\s+developer'
    r'|full[\s-]?stack|mobile\s+(?:developer|engineer)|ios|android'
    r'|qa\s+engineer|tester|test\s+engineer'
    r'|network\s+engineer|security\s+engineer|field\s+service'
    r'|data\s+cent(?:er|re)|solution\s+delivery|sales|recruiter'
    r'|human\s+resources|hr\s+(?:manager|specialist|generalist)'
    r'|intern(?:ship)?\b|volunteer|fresher|trainee'
    r'|\bphp\b|java\s+developer|dot\s*net|\.net\s+developer|salesforce'
    r'|servicenow|\bsap\b|oracle\s+developer|forward\s+deployed'
    r'|support\s+engineer|helpdesk|system\s+administrator'
    r'|fire\s+protection|facilities|sales\s+engineer)')

# Recognizes the 3 target role groups. The regex tolerates variants and even
# dropped-letter typos.
ROLE_PATTERNS = [
    ('Data Engineer', re.compile(
        r'\b(?:data\s+engin\w*|data\s+engineering|analytics\s+engineer'
        r'|(?:etl|elt)\s+(?:developer|engineer)|big\s+data\s+engineer'
        r'|data\s+(?:platform|infrastructure|warehouse|pipeline)\s+engineer'
        r'|databricks\s+engineer|snowflake\s+engineer|spark\s+engineer'
        r'|data\s*ops\s+engineer)')),
    ('Cloud / DevOps Engineer', re.compile(
        r'\b(?:cloud\s+engin\w*|cloud\s+data\s+engin\w*|dev\s*sec\s*ops'
        r'|dev\s*ops\s+engin\w*|platform\s+engineer'
        r'|site\s+reliability\s+engineer|\bsre\b'
        r'|(?:cloud\s+)?infrastructure\s+engineer|kubernetes\s+engineer'
        r'|cloud\s+operations)')),
    ('Python Developer', re.compile(
        r'\bpython\b[^|]{0,40}?\b(?:developer|engineer|dev)\b'
        r'|\b(?:developer|engineer)\b[^|]{0,40}?\bpython\b'
        r'|\bbackend\s+(?:developer|engineer)\b')),
]


def role_group_of(title):
    """Returns the role group name, or None if it's not one of the 3 target roles."""
    t = norm(title)
    if HARD_EXCLUDE_RE.search(t):
        return None
    for label, pat in ROLE_PATTERNS:
        if pat.search(t):
            return label
    return None


# ---------- pillar 4: right profession ----------

def score_role(title, group):
    """A hard gate. Outside the 3 target role groups it's rejected, not scored low.

    Returns (score, label, flags, keep_or_not).
    """
    if group is None:
        return 0, 'ngoài phạm vi tìm kiếm', [], False
    if group == 'Data Engineer':
        return 15, 'Data Engineer', [], True
    if group == 'Cloud / DevOps Engineer':
        return 13, 'Cloud / DevOps Engineer', [], True
    return 10, 'Python Developer', ['nghề phụ, chỉ xét khi thiếu lựa chọn'], True


# ---------- reading the location from a post ----------

PLACE_WORDS = sorted(set(
    _VN + ['singapore', 'australia', 'sydney', 'melbourne', 'brisbane',
           'new zealand', 'malaysia', 'indonesia', 'thailand', 'philippines',
           'india', 'japan', 'tokyo', 'korea', 'hong kong', 'taiwan',
           'apac', 'asia pacific', 'asia-pacific', 'southeast asia',
           'europe', 'european', 'uk', 'united kingdom', 'germany', 'poland',
           'portugal', 'spain', 'netherlands', 'canada', 'usa',
           'united states', 'latam', 'latin america', 'worldwide', 'global',
           'anywhere', 'remote']), key=len, reverse=True)


def guess_place_post(desc):
    """Guesses the location mentioned in a post.

    LinkedIn posts use 📍 for every bullet point (salary, deadline, experience),
    so taking the first match is wrong. A line containing the word 'location'
    is preferred; failing that, the full text is scanned for a real place name.
    """
    d = norm(desc)
    for m in re.finditer(r'location\s*[:\-–]?\s*([^\n]{3,60})', d):
        seg = m.group(1)
        found = [w for w in PLACE_WORDS if _kw_hit(seg, w)]
        if found:
            return ', '.join(dict.fromkeys(found[:3])).title()
    for m in re.finditer(r'📍\s*([^\n]{3,60})', desc):
        seg = norm(m.group(1))
        found = [w for w in PLACE_WORDS if _kw_hit(seg, w)]
        if found:
            return ', '.join(dict.fromkeys(found[:3])).title()
    found = [w for w in PLACE_WORDS if _kw_hit(d, w)]
    return ', '.join(dict.fromkeys(found[:3])).title() if found else ''


def _kw_hit(text, kw):
    return re.search(r'(?<![a-z0-9])' + re.escape(kw) + r'(?![a-z0-9])', text) is not None


def post_mode(desc):
    """Work mode of the post. Only accepts Remote when the context is clear."""
    d = norm(desc)
    if re.search(r'\b(?:100%|fully|completely)\s+remote|\bremote\s*(?:only|role|position|opportunit|job|work)'
                 r'|\bwork\s+from\s+(?:home|anywhere)|\(remote\)|\bremote\s*[|\-–:]', d):
        return 'Remote'
    if 'hybrid' in d:
        return 'Hybrid'
    if re.search(r'\bon-?site\b|\bin\s+office\b|\bday\s*1\s*onsite\b', d):
        return 'Onsite'
    return ''


# ---------- aggregation ----------

def score_item(it, kind, now):
    if kind == 'job':
        title = it.get('title') or ''
        desc = it.get('description') or ''
        place, mode = split_location(it.get('location') or '')
        if it.get('workplaceType'):
            mode = {'remote': 'Remote', 'hybrid': 'Hybrid',
                    'on_site': 'Onsite', 'office': 'Onsite'}.get(
                        norm(it['workplaceType']), mode)
        exp_level = it.get('experienceLevel')
        company = it.get('company') or ''
    else:
        desc = it.get('content') or ''
        title = desc[:160]
        place = guess_place_post(desc)
        _, mode2 = split_location(place)
        mode = mode2 or post_mode(desc)
        exp_level = None
        company = it.get('authorName') or ''

    blob = title + ' ' + desc + ' ' + place + ' ' + company
    flags = []

    matched, weight, missing, demanded = match_skills(desc if desc else title)
    s_skill, skill_note = score_skills(matched, weight, demanded, bool(desc.strip()))
    s_sen, sen_label, f2 = score_seniority(title, desc, exp_level)
    s_reach, reach_label, f3 = score_reach(place, mode, desc, title,
                                           it.get('workRemoteAllowed'))
    group = role_group_of(title)
    s_role, role_label, f4, on_target = score_role(title, group)
    flags += f2 + f3 + f4

    parts = {'kỹ năng': s_skill, 'vừa tầm': s_sen,
             'với tới': s_reach, 'đúng nghề': s_role}

    # bonus
    bonus = 0
    if any(c in norm(desc) for c in CERTS_KW):
        bonus += 5
        flags.append('job nhắc chứng chỉ AWS, bạn có 3 cái')
    dom = [d for d in DOMAINS if d in norm(blob)]
    if dom:
        bonus += 3
        flags.append('khớp ngành đã làm: ' + dom[0])
    if it.get('easyApply') or it.get('easyApplyUrl'):
        bonus += 4
        flags.append('Easy Apply, nộp thẳng không cần portal riêng')
    app = it.get('applicants')
    # LinkedIn rounds down to 25 and caps at 200, so those two thresholds aren't real signals
    if isinstance(app, int) and 0 < app < 25:
        bonus += 3
        flags.append('mới ' + str(app) + ' ứng viên, ít cạnh tranh')
    elif isinstance(app, int) and app >= 150:
        bonus -= 5
        flags.append(str(app) + '+ ứng viên, cạnh tranh cao')
    if any(e in norm(company) for e in MS['known_global_employers']):
        bonus += 4
        flags.append('công ty được biết là tuyển toàn cầu')
    parts['cộng thêm'] = bonus

    # penalties
    pen = 0
    missing_in_title = any_kw_family(title, GAPS)
    if missing_in_title:
        pen -= 15
        flags.append('yêu cầu lõi chưa có: ' + ', '.join(missing_in_title[:2]))
    if len(missing) >= 3:
        pen -= 12
        flags.append('đòi nhiều thứ chưa có: ' + ', '.join(missing[:3]))
    elif len(missing) == 2:
        pen -= 6
        flags.append('đòi thêm: ' + ', '.join(missing))
    if len(desc) > 300 and len(FOREIGN_RE.findall(norm(desc))) >= 6:
        pen -= 18
        flags.append('mô tả không viết bằng tiếng Anh')
    lang = any_kw(blob, P['constraints']['language_blockers'])
    if lang:
        pen -= 20
        flags.append('rào ngôn ngữ: ' + lang[0])
    if kind == 'post':
        spam = any_kw(desc, ['comment interested', 'hotlist', 'bench sales',
                             'share your resume along with', 'multiple openings',
                             'multiple positions'])
        if spam:
            pen -= 25
            flags.append('post spam môi giới: ' + spam[0])
    parts['trừ điểm'] = pen

    total = max(0, min(100, sum(parts.values())))
    # A job with no description can't be scored on the skill pillar (30 points).
    # It gets scored out of 70 and then rescaled, otherwise the ranking would
    # just reflect 'which job got enriched'.
    incomplete = kind == 'job' and not desc.strip()
    if incomplete:
        # DO NOT rescale. Missing description means the skills couldn't be
        # verified, and boosting the score would rank an unknown job above one
        # already confirmed to be a good fit. The right fix is to enrich the
        # data further, not to compensate with points.
        flags.append('chưa có mô tả job, chưa chấm được kỹ năng')
    age = age_hours(it, now)

    return {
        'score': total, 'verdict': verdict_of(total), 'breakdown': parts,
        'matched_skills': matched, 'missing_skills': missing,
        'skill_note': skill_note, 'demanded': demanded,
        'seniority': sen_label, 'reach': reach_label, 'role_fit': role_label,
        'role_group': group, 'on_target': on_target,
        'place': place, 'work_mode': mode, 'company': company,
        'flags': flags,
        'age_h': round(age, 2) if age is not None else None,
        'posted_iso': iso_utc(it, now), 'posted_human': human_age(age),
        'kind': kind, 'incomplete': incomplete,
    }


def main(infile, outfile, kind=None):
    items = json.load(open(infile, encoding='utf-8'))
    if kind is None:
        kind = 'post' if any(i.get('content') for i in items[:20]) else 'job'
    now = datetime.now(timezone.utc)
    for it in items:
        it.update(score_item(it, kind, now))
    with open(outfile, 'w', encoding='utf-8') as f:
        json.dump(items, f, ensure_ascii=False, indent=1)

    on = [i for i in items if i.get('on_target')]
    v = Counter(i['verdict'] for i in on)
    print('[score:' + kind + '] ' + str(len(items)) + ' item -> đúng nghề '
          + str(len(on)) + ', loại ngoài phạm vi ' + str(len(items) - len(on)))
    for _, label in VERDICTS:
        if v.get(label):
            print('   ' + label.ljust(16) + str(v[label]))
    print('   nhóm nghề:', dict(Counter(i['role_group'] for i in on)))
    top = sorted(on, key=lambda x: -x['score'])[:3]
    for t in top:
        print('   * ' + str(t['score']) + ' | ' + (t.get('title') or '')[:46]
              + ' | ' + t['reach'])


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    k = sys.argv[sys.argv.index('--kind') + 1] if '--kind' in sys.argv else None
    main(sys.argv[1], sys.argv[2], k)
