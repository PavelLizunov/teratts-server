"""Read-only primary registry snapshot; no package downloads or installs."""
import concurrent.futures
import datetime
import json
import pathlib
import tomllib
import urllib.error
import urllib.request

root = pathlib.Path(__file__).resolve().parents[3]
manifest = tomllib.loads((root / 'Cargo.toml').read_text())
lock = tomllib.loads((root / 'Cargo.lock').read_text())
names = sorted(set(manifest['dependencies']) | set(manifest.get('dev-dependencies', {})))
locked = {}
for package in lock['package']:
    if package['name'] in names:
        locked.setdefault(package['name'], []).append(package['version'])

def inspect(name):
    url = 'https://crates.io/api/v1/crates/' + name
    request = urllib.request.Request(url, headers={'User-Agent': 'teratts-readonly-audit/1.0', 'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read(2 * 1024 * 1024))
        crate = data['crate']
        versions = data.get('versions', [])
        declaration = manifest['dependencies'].get(name, manifest.get('dev-dependencies', {}).get(name))
        requirement = declaration if isinstance(declaration, str) else declaration.get('version')
        return {'crate': name, 'source_url': url, 'requirement': requirement, 'locked': locked.get(name, []),
                'max_stable_version': crate.get('max_stable_version'), 'max_version': crate.get('max_version'),
                'newest_version': crate.get('newest_version'), 'updated_at': crate.get('updated_at'),
                'recent_versions': [{'version': v['num'], 'created_at': v['created_at'],
                                     'yanked': v['yanked'], 'rust_version': v.get('rust_version')}
                                    for v in versions[:5]]}
    except (OSError, ValueError, urllib.error.URLError) as error:
        return {'crate': name, 'source_url': url, 'locked': locked.get(name, []), 'error': str(error)}

with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
    results = list(executor.map(inspect, names))
print(json.dumps({'observed_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  'source': 'crates.io public registry API', 'dependencies': results}, indent=2))
