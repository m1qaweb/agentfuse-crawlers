#!/usr/bin/env python3
"""Download and archive one Zyte Scrapy Cloud job without writing to AgentFuse.

Set ZYTE_SCRAPY_CLOUD_API_KEY in the environment, then:
python -m scripts.download_zyte --job-id 883514/1/9 --out-dir output/archive

Credentials are not printed or added to Git. No arbitrary URLs are accepted.
"""

import argparse
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

JOB_ID = re.compile(r'^\d+/\d+/\d+$')
MAX_BYTES = 80_000_000


def download_job(job_id, out_dir, api_key=None):
    if not JOB_ID.fullmatch(job_id):
        raise ValueError('job-id must look like 883514/1/9')
    key = api_key if api_key is not None else os.environ.get('ZYTE_SCRAPY_CLOUD_API_KEY')
    if not key:
        raise ValueError('Set ZYTE_SCRAPY_CLOUD_API_KEY (Scrapy Cloud key) before downloading')
    # Official Zyte Storage endpoint: query API key cannot be logged or echoed.
    url = ('https://storage.zyte.com/items/' + job_id + '?' +
           urllib.parse.urlencode({'apikey': key, 'format': 'jl'}))
    destination = Path(out_dir)
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / ('zyte_' + job_id.replace('/', '_') + '.jsonl')
    temp = target.with_suffix('.jsonl.part')
    try:
        request = urllib.request.Request(url, headers={'Accept': 'application/json'})
        with urllib.request.urlopen(request, timeout=90) as response, temp.open('wb') as writer:
            downloaded = 0
            while True:
                block = response.read(64 * 1024)
                if not block:
                    break
                downloaded += len(block)
                if downloaded > MAX_BYTES:
                    raise ValueError('Export larger than 80 MB; investigate before retrying')
                writer.write(block)
        count = 0
        with temp.open(encoding='utf-8') as handle:
            for line in handle:
                if line.strip():
                    obj = json.loads(line)
                    if not isinstance(obj, dict) or 'source_id' not in obj:
                        raise ValueError('Invalid Zyte item: missing source_id')
                    count += 1
        if count == 0:
            raise ValueError('Empty job export; check Items tab before archiving')
        temp.replace(target)
        return target, count
    finally:
        temp.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job-id', required=True)
    parser.add_argument('--out-dir', default='output/archive', type=Path)
    args = parser.parse_args()
    dest, count = download_job(args.job_id, args.out_dir)
    print(f'Saved {count} source records to {dest}')


if __name__ == '__main__':
    main()
