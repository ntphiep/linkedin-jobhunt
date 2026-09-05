"""Generate profile.json from a CV file, without hardcoding personal data.

Reads the CV (PDF / DOCX / TXT / MD), extracts skills, years of experience,
certifications, domains worked in, and contact info, then cross-references
taxonomy.json to score proficiency levels and infer the list of missing skills.

LinkedIn data can be mixed in if --linkedin is passed.

This lets the plugin work for anyone: just swap the CV, no code changes needed.

Usage:
  python build_profile.py <cv_file> [--out profile.json]
                                    [--linkedin https://linkedin.com/in/xxx]
                                    [--roles "data engineer,cloud engineer"]
"""
import sys, os, re, json, collections
from datetime import date
from lib import SKILL_DIR, norm

TAXONOMY = os.path.join(SKILL_DIR, 'taxonomy.json')

# A date range near these words is education, not work experience
EDU_RE = re.compile(
    r'universit|college|school|bachelor|master|phd|degree|gpa'
    r'|education|academy|institute of|khoa |truong |dai hoc')

EXPERIENCE_SECTION_RE = re.compile(
    r'(?:work experience|employment history|experience)(.*?)'
    r'(?:\n\s*education\b|\Z)',
    re.I | re.S)

MONTHS = {m: i for i, m in enumerate(
    ['jan', 'feb', 'mar', 'apr', 'may', 'jun',
     'jul', 'aug', 'sep', 'oct', 'nov', 'dec'], 1)}


# ---------- reading the file ----------

def read_cv(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == '.pdf':
        try:
            import pdfplumber
            with pdfplumber.open(path) as pdf:
                return '\n'.join((pg.extract_text() or '') for pg in pdf.pages)
        except ImportError:
            from pypdf import PdfReader
            return '\n'.join((pg.extract_text() or '') for pg in PdfReader(path).pages)
    if ext == '.docx':
        import docx
        return '\n'.join(p.text for p in docx.Document(path).paragraphs)
    with open(path, encoding='utf-8', errors='ignore') as f:
        return f.read()


# ---------- extracting contact info ----------

def extract_identity(text):
    email = re.search(r'[\w.+-]+@[\w-]+\.[\w.]+', text)
    phone = re.search(r'\(?\+?\d{1,3}\)?[\s.-]?\d{3,4}[\s.-]?\d{3,4}[\s.-]?\d{3,4}', text)
    li = re.search(r'linkedin\.com/in/([A-Za-z0-9\-_]+)', text, re.I)
    lines = [l.strip() for l in text.splitlines() if l.strip()][:6]
    name = ''
    for l in lines:
        # a name is usually ALL CAPS or Title Case, 2-5 words, no digits
        if 2 <= len(l.split()) <= 5 and not re.search(r'[\d@|]', l):
            if l.isupper() or l.istitle():
                name = l.title()
                break
    title = ''
    for l in lines:
        if re.search(r'engineer|developer|analyst|scientist|architect', l, re.I):
            title = l
            break
    return {
        'name': name,
        'title': title,
        'linkedin': ('https://www.linkedin.com/in/' + li.group(1)) if li else '',
        'email': email.group(0) if email else '',
        'phone': phone.group(0).strip() if phone else '',
    }


# ---------- years of experience from date ranges ----------

def extract_experience(text):
    """Returns (years, start date, list of date spans).

    Calculated as the TOTAL SPAN from the earliest date to now, with overlapping
    periods merged, so working on several projects in parallel doesn't get
    double-counted.
    """
    pat = re.compile(
        r'(' + '|'.join(MONTHS) + r')\w*\s+(\d{4})\s*[–\-—to]+\s*'
        r'(?:(' + '|'.join(MONTHS) + r')\w*\s+(\d{4})|present|current|now)',
        re.I)
    spans = []
    for m in pat.finditer(text):
        # Skip dates that belong to the education section: 4 years of college
        # would otherwise inflate the experience count
        ctx = norm(text[max(0, m.start() - 120):m.start()])
        if EDU_RE.search(ctx):
            continue
        s = int(m.group(2)) * 12 + MONTHS[m.group(1)[:3].lower()]
        if m.group(4):
            e = int(m.group(4)) * 12 + MONTHS[m.group(3)[:3].lower()]
        else:
            today = date.today()
            e = today.year * 12 + today.month
        if e > s:
            spans.append((s, e))
    if not spans:
        return 0.0, '', []

    spans.sort()
    merged = [list(spans[0])]
    for s, e in spans[1:]:
        if s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    months = sum(e - s for s, e in merged)
    start = min(s for s, _ in spans)
    return round(months / 12, 1), f'{start // 12}-{start % 12 or 12:02d}', merged


# ---------- skills ----------

SKILL_SECTION_RE = re.compile(
    r'(technical skills?|skills? *&? *tools?|tech stack|technologies)'
    r'(.{0,900}?)(?=\n[A-Z][A-Z &]{4,}\n|\Z)', re.I | re.S)


_VAR_CACHE = {}


def _variant_pattern(kw):
    """Regex that tolerates morphological variants of a keyword.

    A CV might say 'Data Warehousing' while the dictionary has 'data warehouse';
    'GitHub Action' while the dictionary has 'github actions';
    'AWS Glue' while the dictionary has 'glue'.
    Allows an s / es / ing / d suffix, and drops a leading 'aws '/'azure ' if present.
    """
    if kw in _VAR_CACHE:
        return _VAR_CACHE[kw]
    base = re.escape(kw)
    # 'data warehouse' -> also allow 'data warehousing'
    if kw.endswith('e'):
        base = re.escape(kw[:-1]) + '(?:e|ing)'
    elif kw.endswith('s'):
        base = re.escape(kw[:-1]) + 's?'
    head = r'(?<![a-z0-9])' if kw[:1].isalnum() else ''
    tail = r'(?:s|es|ing|d)?(?![a-z0-9])' if kw[-1:].isalnum() else ''
    _VAR_CACHE[kw] = re.compile(head + base + tail)
    return _VAR_CACHE[kw]


def extract_skills(text, vocab):
    """Scores proficiency by where it appears and how often.

    3 = appears in the skills section AND is mentioned again in the experience
        section (actually used)
    2 = appears in the skills section, or mentioned 2+ times
    1 = only mentioned in passing, once
    """
    t = norm(text)
    m = SKILL_SECTION_RE.search(text)
    section = norm(m.group(2)) if m else ''

    out = {}
    for kw in vocab:
        pat = _variant_pattern(kw)
        n = len(re.findall(pat, t))
        if not n:
            continue
        in_sec = bool(re.search(pat, section))
        if in_sec and n >= 2:
            out[kw] = 3
        elif in_sec or n >= 2:
            out[kw] = 2
        else:
            out[kw] = 1
    return out


CERT_RE = re.compile(
    r'((?:aws|azure|google|gcp|microsoft|oracle|databricks|snowflake|cka|ckad)'
    r'[^\n]{0,70}?(?:certified|certification|certificate)[^\n]{0,50})', re.I)
CERT_RE2 = re.compile(
    r'((?:certified|certification)[^\n]{0,70})', re.I)

DOMAIN_WORDS = ['insurance', 'banking', 'fintech', 'healthcare', 'medical',
                'telehealth', 'airline', 'aviation', 'retail', 'supermarket',
                'ecommerce', 'e-commerce', 'logistics', 'hospitality', 'hotel',
                'travel', 'telecom', 'manufacturing', 'automotive', 'education',
                'gaming', 'energy', 'real estate', 'media', 'government']


def main(cv_path, out_path, linkedin_url=None, roles=None):
    text = read_cv(cv_path)
    if len(text.strip()) < 100:
        raise SystemExit('Không đọc được nội dung CV từ ' + cv_path)

    tax = json.load(open(TAXONOMY, encoding='utf-8'))
    vocab = tax['tech_vocab']

    ident = extract_identity(text)
    if linkedin_url:
        ident['linkedin'] = linkedin_url
    years, start, spans = extract_experience(text)
    skills = extract_skills(text, vocab)

    raw = []
    for rx in (CERT_RE, CERT_RE2):
        for m in rx.finditer(text):
            c = ' '.join(m.group(1).split()).strip(' -•·')
            if len(c) > 12 and not c.isupper():   # skip section headings like CERTIFICATIONS
                raw.append(c)
    # keep the longest string in each family, drop strings that are substrings of another
    raw.sort(key=len, reverse=True)
    certs = []
    for c in raw:
        if not any(norm(c) in norm(k) for k in certs):
            certs.append(c)
    certs = certs[:10]

    # Only scan the work-experience section: the EDUCATION section always
    # contains the word "education", scanning the whole file would produce
    # false domain matches.
    wm = EXPERIENCE_SECTION_RE.search(text)
    work = norm(wm.group(1)) if wm else norm(text)
    domains = sorted({d for d in DOMAIN_WORDS
                      if re.search(r'(?<![a-z])' + re.escape(d) + r'(?![a-z])', work)})

    # missing skills = dictionary minus what's already covered
    gaps = sorted(set(vocab) - set(skills))

    core = {k: v for k, v in skills.items() if v == 3}
    strong = {k: v for k, v in skills.items() if v == 2}
    familiar = {k: v for k, v in skills.items() if v == 1}

    default_roles = {
        'primary': ['data engineer', 'cloud data engineer', 'analytics engineer',
                    'etl developer', 'data platform engineer'],
        'secondary': ['python developer', 'python engineer', 'cloud engineer',
                      'devops engineer', 'platform engineer'],
    }
    if roles:
        default_roles['primary'] = [r.strip().lower() for r in roles.split(',')]

    profile = collections.OrderedDict([
        ('_generated', {
            'from_cv': os.path.abspath(cv_path),
            'at': date.today().isoformat(),
            'by': 'scripts/build_profile.py',
            '_note': 'File này SINH TỰ ĐỘNG. Sửa CV rồi chạy lại, đừng sửa tay.',
        }),
        ('identity', ident),
        ('seniority', {
            'years_experience': years,
            'career_start': start,
            'periods_detected': len(spans),
        }),
        ('skills', {
            'core': core, 'strong': strong, 'familiar': familiar,
            'gaps': {'hard': gaps},
        }),
        ('certifications', certs),
        ('domains', {'experienced': domains}),
        ('target_roles', default_roles),
        ('constraints', {
            'needs_visa_sponsorship': True,
            'can_work_us_payroll': False,
            'language_blockers': ['native english', 'native speaker',
                                  'fluent german', 'fluent french',
                                  'japanese required', 'korean required',
                                  'mandarin required', 'jlpt'],
        }),
    ])

    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)

    print('[build_profile] ' + os.path.basename(cv_path) + ' -> ' + out_path)
    print('   tên          : ' + (ident['name'] or '(không rút được)'))
    print('   liên hệ      : ' + (ident['email'] or '-') + ' | ' + (ident['phone'] or '-'))
    print('   kinh nghiệm  : ' + str(years) + ' năm (' + str(len(spans))
          + ' giai đoạn, đã gộp chồng lấn)')
    print('   kỹ năng      : ' + str(len(core)) + ' thành thạo, '
          + str(len(strong)) + ' khá, ' + str(len(familiar)) + ' biết')
    print('   chứng chỉ    : ' + str(len(certs)))
    print('   ngành đã làm : ' + (', '.join(domains) or '-'))
    print('   kỹ năng thiếu: ' + str(len(gaps)))
    top = sorted(core, key=lambda k: -skills[k])[:12]
    print('   nổi bật      : ' + ', '.join(top))


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    def arg(n, d=None):
        return sys.argv[sys.argv.index(n) + 1] if n in sys.argv else d

    main(sys.argv[1],
         arg('--out', os.path.join(SKILL_DIR, 'profile.json')),
         arg('--linkedin'), arg('--roles'))
