"""Merge the JSON files written by the linkedin MCP, dedupe them, filter by time.

Two-tier deduplication:
  1. by linkedinUrl or id  (catches exact duplicates)
  2. by content hash       (catches the same post reappearing at a different URL)

Time filtering is based on postedDate for jobs (exact) and postedAgo for
posts (approximate). An item with no time info is kept.

Usage:
  python merge_dedup.py <input_dir> <output_file> [hours]

Example:
  python merge_dedup.py tmp/jobs merged_jobs.json 2
  python merge_dedup.py tmp/posts merged_posts.json      # no time filtering
"""
import sys, json, glob, os
from datetime import datetime, timezone
from lib import age_hours, content_hash


def main(indir, outfile, hours=None):
    hours = float(hours) if hours is not None and str(hours).strip() != '' else None
    now = datetime.now(timezone.utc)

    files = sorted(glob.glob(os.path.join(indir, '*.json')))
    if not files:
        print(f'CẢNH BÁO: không có file JSON nào trong {indir}', file=sys.stderr)

    by_key, seen_hash = {}, {}
    stat = {'đọc': 0, 'trùng_url': 0, 'trùng_nội_dung': 0, 'quá_hạn': 0, 'không_có_id': 0}

    for f in files:
        try:
            payload = json.load(open(f, encoding='utf-8'))
        except Exception as e:
            print(f'LỖI đọc {f}: {e}', file=sys.stderr)
            continue

        for it in payload.get('data', []):
            stat['đọc'] += 1

            if hours is not None:
                age = age_hours(it, now)
                if age is not None and age > hours:
                    stat['quá_hạn'] += 1
                    continue

            key = it.get('linkedinUrl') or it.get('url') or it.get('id')
            if not key:
                stat['không_có_id'] += 1
                continue
            if key in by_key:
                stat['trùng_url'] += 1
                continue

            h = content_hash(it)
            if h and h in seen_hash:
                stat['trùng_nội_dung'] += 1
                continue

            by_key[key] = it
            if h:
                seen_hash[h] = key

    items = list(by_key.values())
    with open(outfile, 'w', encoding='utf-8') as out:
        json.dump(items, out, ensure_ascii=False, indent=1)

    win = f'{hours}h' if hours is not None else 'không lọc'
    print(f'[merge] {len(files)} file, đọc {stat["đọc"]} item, cửa sổ {win} '
          f'-> giữ {len(items)}')
    print(f'        loại: quá hạn {stat["quá_hạn"]}, trùng URL {stat["trùng_url"]}, '
          f'trùng nội dung {stat["trùng_nội_dung"]}, thiếu id {stat["không_có_id"]}')
    return items


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) >= 4 else None)
