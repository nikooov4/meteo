"""Local progress observation only; never modifies input data or benchmark checkpoints."""
import json
import sys
from pathlib import Path

import psutil

root = Path(__file__).resolve().parent
report = json.loads((root / 'scale_report.json').read_text())
manifest = json.loads(Path('data/scale/synthetic-200gb/manifest.json').read_text())
state = json.loads((root / '200000000000-bytes-checkpoint.json').read_text())
completed = set(state['completed'])
data_bytes = sum(s['bytes'] for s in manifest['shards'] if s['sha256'] in completed)
status = {
    'profiles': [[p['target_bytes'], p['status']] for p in report['profiles']],
    '200GB_completed_files': len(completed),
    '200GB_completed_bytes': data_bytes,
    'percent': round(100 * data_bytes / manifest['data_bytes'], 2),
    'rows': state['rows'],
    'scan_wall_s': round(state['scan_wall_s'], 2),
    'peak_RSS_MiB': round(state.get('peak_process_tree_rss', 0) / 2**20, 1),
    'resume_count': state['resume_count'],
    'errors': report['errors'],
}
try:
    proc = psutil.Process(int(sys.argv[1]))
    status['process_read_GB_this_invocation'] = round(proc.io_counters().read_bytes / 1e9, 2)
    status['current_RSS_MiB'] = round(proc.memory_info().rss / 2**20, 1)
except (psutil.Error, IndexError):
    status['process'] = 'not_running_or_not_supplied'
print(json.dumps(status))
