"""Install the pinned navigation adapter into the separate OnlyOffice lab checkout."""
import argparse
import hashlib
import json
import re
from pathlib import Path

parser=argparse.ArgumentParser()
parser.add_argument('--lab-root',type=Path,required=True)
parser.add_argument('--apply',action='store_true',help='Write the reviewed adapter and refresh manifest hashes')
args=parser.parse_args()
root=args.lab_root.resolve()
bridge=Path(__file__).with_name('navigation-bridge.js').read_bytes()
bridge_hash=hashlib.sha256(bridge).hexdigest()[:16]
match=re.search(rb'\bnavigationVersion:(\d+)\b',bridge)
if not match:raise SystemExit('Missing bridge navigation version')
navigation_version=int(match[1])
bridge_url=f'resources/integration-bridge.js?navigation={navigation_version}&v={bridge_hash}'
worker=Path(__file__).with_name('editor-service-worker.js').read_bytes()
relative='apps/documenteditor/main/resources/integration-bridge.js'
index='apps/documenteditor/main/index.html'
release=root/'deploy/releases/10.0.0-labesign9'
targets=[(root/'upstream-build/visual/web-apps',root/'upstream-build/visual-manifest.json',''),(release,release/'manifest.json','web-apps/')]
updates={root/'visual-source/integration-bridge.js':bridge,root/'visual-source/editor-service-worker.js':worker}
worker_route='''location = /10.0.0-labesign9/document_editor_service_worker.js {
  alias /var/www/onlyoffice/documentserver/ui-lab-build/web-apps-visual/editor-service-worker.js;
  default_type application/javascript;
  add_header Cache-Control "no-store" always;
  add_header Service-Worker-Allowed "/10.0.0-labesign9/" always;
}

'''
nginx_source=root/'visual-source/nginx.conf'
nginx=nginx_source.read_text()
if 'location = /10.0.0-labesign9/document_editor_service_worker.js' not in nginx:
    nginx=worker_route+nginx
updates[nginx_source]=nginx.encode()
for base,manifest,prefix in targets:
    data=json.loads(manifest.read_text())
    # Fail before modifying any file when the installed release is already inconsistent.
    for name,digest in data['files'].items():
        if hashlib.sha256((base/name).read_bytes()).hexdigest()!=digest:
            raise SystemExit('Manifest mismatch: '+str(base/name))
    html=(base/(prefix+index)).read_text()
    html,count=re.subn(r'resources/integration-bridge\.js(?:\?[^\"\'<>\s]*)?',
                      bridge_url,html)
    if count!=1:raise SystemExit('Expected one bridge script in '+str(base/(prefix+index)))
    for name,content in [(prefix+relative,bridge),(prefix+index,html.encode()),(prefix+'editor-service-worker.js',worker)]+([('nginx.conf',nginx.encode())] if prefix else []):
        updates[base/name]=content
        data['files'][name]=hashlib.sha256(content).hexdigest()
    updates[manifest]=(json.dumps(data,indent=2)).encode()
build=root/'visual-source/build.py'
source=build.read_text()
# The next full build must derive the URL from its input, not today's hash.
source,count=re.subn(r'resources/integration-bridge\.js(?:\?[^\"\'<>\s]*)?',
                    f'resources/integration-bridge.js?navigation={navigation_version}&v={{bridge_hash}}',source)
if count!=1:raise SystemExit('Unknown build.py bridge declaration')
source=source.replace("entry=entry.replace('</head>','", "entry=entry.replace('</head>',f'")
if "bridge_hash=hashlib.sha256" not in source:
    source=source.replace("# Derive the entry", "bridge_hash=hashlib.sha256((ROOT/'visual-source/integration-bridge.js').read_bytes()).hexdigest()[:16]\n# Derive the entry")
if "shutil.copyfile(ROOT/'visual-source/editor-service-worker.js'" not in source:
    source=source.replace("api=out/", "shutil.copyfile(ROOT/'visual-source/editor-service-worker.js',out/'editor-service-worker.js')\napi=out/")
updates[build]=source.encode()
changed=[str(p) for p,b in updates.items() if not p.exists() or p.read_bytes()!=b]
if args.apply:
    for path,content in updates.items():
        if not path.exists() or path.read_bytes()!=content:
            if path==release/'nginx.conf':
                # Docker bind-mounts this file's inode; retain it before nginx reload.
                path.write_bytes(content)
            else:
                temporary=path.with_name(path.name+'.navigation-tmp')
                temporary.write_bytes(content);temporary.replace(path)
print(json.dumps({'applied':args.apply,'changed_files':changed,'navigation_version':navigation_version},ensure_ascii=False))
