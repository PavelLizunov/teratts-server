"""Read-only OSV queries for exact registry packages from Cargo.lock; no installs."""
import datetime
import json
import pathlib
import tomllib
import urllib.request

root=pathlib.Path(__file__).resolve().parents[3]
lock=tomllib.loads((root/'Cargo.lock').read_text())
packages=[p for p in lock['package'] if p.get('source','').startswith('registry+')]
checked=[];errors=[]
for offset in range(0,len(packages),50):
    batch=packages[offset:offset+50]
    payload={'queries':[{'package':{'name':p['name'],'ecosystem':'crates.io'},'version':p['version']} for p in batch]}
    request=urllib.request.Request('https://api.osv.dev/v1/querybatch',data=json.dumps(payload).encode(),
          headers={'Content-Type':'application/json','User-Agent':'teratts-readonly-audit/1.0'},method='POST')
    try:
        with urllib.request.urlopen(request,timeout=45) as response: data=json.loads(response.read(2*1024*1024))
        for package,result in zip(batch,data.get('results',[])):
            checked.append({'name':package['name'],'version':package['version'],'advisories':[v['id'] for v in result.get('vulns',[])]})
    except (OSError,ValueError) as error:
        errors.append({'batch_offset':offset,'package_count':len(batch),'error':str(error)})
print(json.dumps({'observed_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
      'source_url':'https://api.osv.dev/v1/querybatch','planned_registry_packages':len(packages),
      'checked_packages':len(checked),'errors':errors,'results':checked,
      'limits':'Database coverage only, not exploitability or proof of no vulnerabilities; no OS packages, model files, private packages or runtime configuration scanned.'},indent=2))
