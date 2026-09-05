"""Export a 2-sheet Excel workbook: a job-opportunities table and an overview page.

Default sort order: time bucket -> kind -> region -> work mode -> score.

Usage: python export.py <scored_jobs.json> <scored_posts.json> <out.xlsx> [--min-score 45]
"""
import sys, json
from collections import Counter
from datetime import datetime
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# Link and Posted-at kept near the front for quick clicking
COLS = [
    ('Điểm', 7), ('Nên làm gì', 15), ('Đăng lúc', 13), ('Link', 13),
    ('Vị trí tuyển', 42), ('Công ty', 24), ('Nhóm nghề', 21),
    ('Khu vực', 20), ('Với tới được', 22),
    ('Kỹ năng khớp', 50), ('Cần bổ sung', 20),
    ('Lưu ý', 44),
]
WRAP_COLS = (5, 10, 12)

PASTEL = {
    'Ứng tuyển ngay': 'C8E6C9',   # light green
    'Nên xem':        'BBDEFB',   # light blue
    'Cân nhắc':       'FFE0B2',   # light orange
    'Bỏ qua':         'ECEFF1',   # light gray
}
INK = {
    'Ứng tuyển ngay': '1B5E20', 'Nên xem': '0D47A1',
    'Cân nhắc': 'E65100', 'Bỏ qua': '607D8B',
}
BAND = ['FFFFFF', 'F7F9FC']       # light row striping to make rows easier to follow
HDR_FILL = PatternFill('solid', fgColor='37474F')
HDR_FONT = Font(bold=True, color='FFFFFF', size=11)
LINK_FONT = Font(color='1565C0', underline='single', size=10)
BODY_FONT = Font(size=10)
GRID = Side(style='thin', color='CFD8DC')

# priority order used for sorting
TIME_BUCKETS = [(6, 'Dưới 6 giờ'), (24, 'Hôm nay'), (48, 'Hôm qua'), (10**9, 'Cũ hơn')]
REGION_ORDER = ['Hà Nội', 'TP.HCM', 'Việt Nam', 'Úc', 'Singapore', 'APAC',
                'Châu Âu', 'Toàn cầu', 'Khác']
MODE_ORDER = ['Remote', 'Hybrid', 'Onsite', '']


def time_bucket(h):
    if h is None:
        return 'Cũ hơn'
    for lim, label in TIME_BUCKETS:
        if h <= lim:
            return label
    return 'Cũ hơn'


US_STATES = {
    'al','ak','az','ar','ca','co','ct','de','fl','ga','hi','id','il','in','ia',
    'ks','ky','la','me','md','ma','mi','mn','ms','mo','mt','ne','nv','nh','nj',
    'nm','ny','nc','nd','oh','ok','or','pa','ri','sc','sd','tn','tx','ut','vt',
    'va','wa','wv','wi','wy','dc',
}

# Displayed in order of relevance to the candidate first, the rest alphabetically
REGION_PRIORITY = ['Hà Nội', 'TP.HCM', 'Việt Nam', 'Úc', 'Singapore',
                   'APAC', 'Toàn cầu']

COUNTRY_VI = {
    'united states': 'Mỹ', 'usa': 'Mỹ', 'us': 'Mỹ',
    'united kingdom': 'Anh', 'uk': 'Anh', 'england': 'Anh',
    'india': 'Ấn Độ', 'canada': 'Canada', 'germany': 'Đức',
    'france': 'Pháp', 'spain': 'Tây Ban Nha', 'portugal': 'Bồ Đào Nha',
    'poland': 'Ba Lan', 'netherlands': 'Hà Lan', 'belgium': 'Bỉ',
    'hungary': 'Hungary', 'bulgaria': 'Bulgaria', 'romania': 'Romania',
    'argentina': 'Argentina', 'brazil': 'Brazil', 'mexico': 'Mexico',
    'colombia': 'Colombia', 'uruguay': 'Uruguay', 'chile': 'Chile',
    'malaysia': 'Malaysia', 'indonesia': 'Indonesia', 'thailand': 'Thái Lan',
    'philippines': 'Philippines', 'japan': 'Nhật Bản', 'korea': 'Hàn Quốc',
    'china': 'Trung Quốc', 'taiwan': 'Đài Loan', 'hong kong': 'Hong Kong',
    'south africa': 'Nam Phi', 'egypt': 'Ai Cập', 'nigeria': 'Nigeria',
    'ireland': 'Ireland', 'switzerland': 'Thuỵ Sĩ', 'sweden': 'Thuỵ Điển',
    'norway': 'Na Uy', 'denmark': 'Đan Mạch', 'finland': 'Phần Lan',
    'italy': 'Ý', 'greece': 'Hy Lạp', 'turkey': 'Thổ Nhĩ Kỳ',
    'israel': 'Israel', 'uae': 'UAE', 'pakistan': 'Pakistan',
    'new zealand': 'New Zealand', 'czechia': 'Séc', 'austria': 'Áo',
}


def region_of(place, reach):
    """Returns a human-readable region name. Countries near the candidate get priority,
    the rest just get their proper country name."""
    p = (place or '').strip()
    low = p.lower()

    if any(k in low for k in ('ha noi', 'hanoi', 'hà nội')):
        return 'Hà Nội'
    if any(k in low for k in ('ho chi minh', 'hcmc', 'saigon')):
        return 'TP.HCM'
    if 'vietnam' in low or 'viet nam' in low or 'da nang' in low:
        return 'Việt Nam'
    if any(k in low for k in ('australia', 'sydney', 'melbourne', 'brisbane', 'perth')):
        return 'Úc'
    if 'singapore' in low:
        return 'Singapore'
    if 'apac' in low or 'asia pacific' in low or 'southeast asia' in low:
        return 'APAC'

    # the part after the last comma is usually the country
    tail = low.split(',')[-1].strip()
    for k, vi in COUNTRY_VI.items():
        if tail == k or tail.endswith(' ' + k) or k == tail:
            return vi
    for k, vi in COUNTRY_VI.items():
        if k in low:
            return vi
    # "Bismarck, ND" -> the US country label
    if tail.upper().lower() in US_STATES and len(tail) == 2:
        return 'Mỹ'

    if not p or low in ('remote', 'worldwide', 'global', 'anywhere'):
        if 'toàn cầu' in (reach or '').lower():
            return 'Toàn cầu'
        return 'Không rõ'
    return p.split(',')[-1].strip().title() or 'Không rõ'


def region_rank(name):
    if name in REGION_PRIORITY:
        return (0, REGION_PRIORITY.index(name), '')
    if name == 'Không rõ':
        return (2, 0, '')
    return (1, 0, name)


def title_case_reach(r):
    """Normalize the label: mixed casing gets folded into one style."""
    if not r:
        return 'Không rõ'
    return r[0].upper() + r[1:]


def sort_key(it):
    # Score is column A, so it must descend top to bottom, otherwise Excel's
    # auto-filter looks broken. Region and work mode already have their own
    # filter in the header.
    return (-it['score'], region_rank(it['_region']))


def can_apply(it):
    """Drop postings the candidate cannot realistically take.

    A low score is not enough: a posting that says "US citizenship" has no
    business sitting in the sheet, because the user then has to re-read every
    row by hand, which is exactly what this tool exists to avoid.
    """
    reach = it.get('reach') or ''
    sen = it.get('seniority') or ''
    if reach in ('khoá trong Mỹ', 'cần quyền lao động sở tại'):
        return False
    if 'quá tầm' in sen or 'quá xa' in sen:
        return False
    if 'cần chuyển chỗ' in reach:      # onsite/hybrid abroad means relocating
        return False
    return True


def prepare(items):
    for it in items:
        it['_bucket'] = time_bucket(it.get('age_h'))
        it['_region'] = region_of(it.get('place'), it.get('reach'))
    return sorted(items, key=sort_key)


def row_of(it):
    sen = it.get('seniority') or ''
    if sen in ('không ghi rõ', 'Không rõ'):
        sen = ''                       # left blank to reduce visual clutter
    return [
        it['score'],
        it['verdict'],
        it.get('posted_human') or '',
        it.get('linkedinUrl') or it.get('url') or '',
        ((it.get('title') or it.get('content') or '')[:140]
         .replace('\n', ' ').strip() or '(không tiêu đề)'),
        it.get('company') or '',
        it.get('role_group') or '',
        it['_region'],
        title_case_reach(it.get('reach')),
        ', '.join(it.get('matched_skills') or [])[:200],
        ', '.join(it.get('missing_skills') or [])[:60],
        ' · '.join(it.get('flags') or [])[:200],
    ]


def sheet_jobs(wb, items):
    ws = wb.active
    ws.title = 'Cơ hội việc làm'
    ws.append([c for c, _ in COLS])

    band = 0
    for it in items:
        ws.append(row_of(it))
        r, v = ws.max_row, it['verdict']
        band ^= 1
        stripe = PatternFill('solid', fgColor=BAND[band])
        for ci in range(1, len(COLS) + 1):
            cell = ws.cell(r, ci)
            cell.font = BODY_FONT
            cell.fill = stripe
            cell.border = Border(bottom=GRID, left=GRID, right=GRID)
            cell.alignment = Alignment(
                vertical='top', wrap_text=ci in WRAP_COLS,
                horizontal='center' if ci in (1, 3) else 'left')
        ws.cell(r, 1).fill = PatternFill('solid', fgColor=PASTEL[v])
        ws.cell(r, 1).font = Font(bold=True, size=11, color=INK[v])
        ws.cell(r, 2).fill = PatternFill('solid', fgColor=PASTEL[v])
        ws.cell(r, 2).font = Font(bold=True, size=10, color=INK[v])
        link = ws.cell(r, 4)
        if isinstance(link.value, str) and link.value.startswith('http'):
            link.hyperlink = link.value
            link.value = 'Mở tin ↗'
            link.font = LINK_FONT
            link.alignment = Alignment(horizontal='center', vertical='top')
        ws.row_dimensions[r].height = 30

    for c in ws[1]:
        c.font = HDR_FONT
        c.fill = HDR_FILL
        c.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
    ws.row_dimensions[1].height = 30
    for i, (_, w) in enumerate(COLS, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = 'E2'
    ws.auto_filter.ref = 'A1:' + get_column_letter(len(COLS)) + str(ws.max_row)
    ws.sheet_view.showGridLines = False


def sheet_summary(wb, items, meta):
    ws = wb.create_sheet('Tổng quan')
    ws.sheet_view.showGridLines = False
    ws.column_dimensions['A'].width = 3
    ws.column_dimensions['B'].width = 34
    ws.column_dimensions['C'].width = 12
    ws.column_dimensions['D'].width = 3
    ws.column_dimensions['E'].width = 34
    ws.column_dimensions['F'].width = 12

    def hdr(row, col, text, color='37474F'):
        c = ws.cell(row, col, text)
        c.font = Font(bold=True, size=12, color='FFFFFF')
        c.fill = PatternFill('solid', fgColor=color)
        c.alignment = Alignment(indent=1, vertical='center')
        ws.cell(row, col + 1).fill = PatternFill('solid', fgColor=color)
        ws.row_dimensions[row].height = 22

    def kv(row, col, k, v, fill=None, bold=False):
        a = ws.cell(row, col, '   ' + str(k))
        b = ws.cell(row, col + 1, v)
        a.font = Font(size=10, bold=bold)
        b.font = Font(size=10, bold=True)
        b.alignment = Alignment(horizontal='center')
        if fill:
            b.fill = PatternFill('solid', fgColor=fill)
        a.border = Border(bottom=GRID)
        b.border = Border(bottom=GRID)

    t = ws.cell(2, 2, 'KẾT QUẢ TÌM VIỆC')
    t.font = Font(bold=True, size=16, color='37474F')
    ws.cell(3, 2, meta['run_at'] + '  ·  ' + meta['profile_name']
            + '  ·  ' + str(meta['yoe']) + ' năm kinh nghiệm').font = Font(size=10, color='78909C')

    # left column: what to do
    hdr(5, 2, 'NÊN LÀM GÌ')
    vc = Counter(i['verdict'] for i in items)
    r = 6
    for label in ['Ứng tuyển ngay', 'Nên xem', 'Cân nhắc', 'Bỏ qua']:
        if vc.get(label):
            kv(r, 2, label, vc[label], PASTEL[label], bold=(label == 'Ứng tuyển ngay'))
            r += 1
    kv(r, 2, 'Tổng cộng', len(items), 'CFD8DC', bold=True)
    chart_anchor = r + 2

    # left column: region
    hdr(chart_anchor, 2, 'THEO KHU VỰC')
    rc = Counter(i['_region'] for i in items)
    r = chart_anchor + 1
    reg_start = r
    for k in sorted(rc, key=lambda x: (region_rank(x), -rc[x])):
        kv(r, 2, k, rc[k])
        r += 1
    reg_end = r - 1

    # right column: role group, work mode, time bucket
    hdr(5, 5, 'THEO NHÓM NGHỀ')
    r2 = 6
    for k, v in Counter(i.get('role_group') or 'Khác' for i in items).most_common():
        kv(r2, 5, k, v)
        r2 += 1
    r2 += 1
    hdr(r2, 5, 'THEO HÌNH THỨC LÀM VIỆC')
    r2 += 1
    for k in MODE_ORDER:
        n = sum(1 for i in items if (i.get('work_mode') or '') == k)
        if n:
            kv(r2, 5, k or 'Không rõ', n)
            r2 += 1
    r2 += 1
    hdr(r2, 5, 'THEO THỜI GIAN ĐĂNG')
    r2 += 1
    bc = Counter(i['_bucket'] for i in items)
    for _, k in TIME_BUCKETS:
        if bc.get(k):
            kv(r2, 5, k, bc[k])
            r2 += 1

    # bar chart by region
    base = max(r2, reg_end + 2)
    hdr(base, 5, 'KỸ NĂNG CỦA BẠN ĐƯỢC HỎI NHIỀU NHẤT')
    sk = Counter()
    for i in items:
        sk.update(i.get('matched_skills') or [])
    rr = base + 1
    for k, n in sk.most_common(12):
        kv(rr, 5, k, n)
        rr += 1

    rr += 1
    hdr(rr, 5, 'TOP 10 ĐÁNG NỘP NHẤT')
    rr += 1
    for i in sorted(items, key=lambda x: -x['score'])[:10]:
        label = ((i.get('title') or i.get('content') or '')[:38]).replace('\n', ' ')
        kv(rr, 5, label, i['score'], PASTEL[i['verdict']])
        rr += 1


def main(jobs_file, posts_file, outfile, min_score=45):
    jobs = json.load(open(jobs_file, encoding='utf-8'))
    posts = json.load(open(posts_file, encoding='utf-8'))
    items = [i for i in jobs + posts
             if i.get('on_target') and i.get('score', 0) >= min_score
             and can_apply(i)]
    items = prepare(items)

    try:
        from lib import load_profile
        pf = load_profile()
        meta = {'profile_name': pf['identity']['name'],
                'yoe': pf['seniority']['years_experience']}
    except Exception:
        meta = {'profile_name': '?', 'yoe': '?'}
    meta['run_at'] = datetime.now().strftime('%d/%m/%Y %H:%M')

    wb = Workbook()
    sheet_jobs(wb, items)
    sheet_summary(wb, items, meta)
    wb.save(outfile)

    vc = Counter(i['verdict'] for i in items)
    print('[export] ' + str(len(items)) + ' cơ hội -> ' + outfile)
    print('   ' + ' | '.join(l + ' ' + str(vc[l]) for l in
                             ['Ứng tuyển ngay', 'Nên xem', 'Cân nhắc'] if vc.get(l)))
    print('   khu vực: ' + ', '.join(k + ' ' + str(v) for k, v in
                                     Counter(i['_region'] for i in items).most_common(5)))


if __name__ == '__main__':
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)
    ms = int(sys.argv[sys.argv.index('--min-score') + 1]) if '--min-score' in sys.argv else 45
    main(sys.argv[1], sys.argv[2], sys.argv[3], ms)
