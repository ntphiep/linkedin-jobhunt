"""Remember items seen in previous runs, so the next run only shows new postings.

History is stored at <skill_dir>/seen_history.json as { key: first_seen_ISO }.
The key is linkedinUrl / url / id, same as merge_dedup's dedup key.

Usage:
  python history.py mark <classified.json>            record the keys into history
  python history.py filter <in.json> <out.json>       keep only items NOT seen before
  python history.py stats                             show what's currently in history
  python history.py prune [days]                      delete entries older than N days (default 30)
"""
import sys, json, os
from datetime import datetime, timezone, timedelta
from lib import SKILL_DIR, load_config

CFG = load_config()
HIST_PATH = os.path.join(SKILL_DIR, CFG['output'].get('history_file', 'seen_history.json'))


def load_hist():
    if not os.path.exists(HIST_PATH):
        return {}
    try:
        with open(HIST_PATH, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def save_hist(h):
    with open(HIST_PATH, 'w', encoding='utf-8') as f:
        json.dump(h, f, ensure_ascii=False, indent=0, sort_keys=True)


def key_of(it):
    return it.get('linkedinUrl') or it.get('url') or it.get('id')


def cmd_mark(infile):
    items = json.load(open(infile, encoding='utf-8'))
    h = load_hist()
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    added = 0
    for it in items:
        k = key_of(it)
        if k and k not in h:
            h[k] = now
            added += 1
    save_hist(h)
    print('[history] ghi thêm ' + str(added) + ' key, tổng ' + str(len(h)))


def cmd_filter(infile, outfile):
    items = json.load(open(infile, encoding='utf-8'))
    h = load_hist()
    fresh = [it for it in items if key_of(it) not in h]
    with open(outfile, 'w', encoding='utf-8') as f:
        json.dump(fresh, f, ensure_ascii=False, indent=1)
    print('[history] ' + str(len(items)) + ' item -> mới ' + str(len(fresh))
          + ', đã từng thấy ' + str(len(items) - len(fresh)))


def cmd_stats():
    h = load_hist()
    if not h:
        print('[history] chưa có lịch sử tại ' + HIST_PATH)
        return
    days = {}
    for v in h.values():
        days[v[:10]] = days.get(v[:10], 0) + 1
    print('[history] ' + str(len(h)) + ' key tại ' + HIST_PATH)
    for d in sorted(days)[-10:]:
        print('   ' + d + ' : ' + str(days[d]))


def cmd_prune(days=30):
    h = load_hist()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=int(days))).isoformat()
    kept = {k: v for k, v in h.items() if v >= cutoff}
    save_hist(kept)
    print('[history] xoá ' + str(len(h) - len(kept)) + ' mục cũ hơn '
          + str(days) + ' ngày, còn ' + str(len(kept)))


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == 'mark':
        cmd_mark(sys.argv[2])
    elif cmd == 'filter':
        cmd_filter(sys.argv[2], sys.argv[3])
    elif cmd == 'stats':
        cmd_stats()
    elif cmd == 'prune':
        cmd_prune(sys.argv[2] if len(sys.argv) > 2 else 30)
    else:
        print(__doc__)
        sys.exit(1)
