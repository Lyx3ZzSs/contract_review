"""Install the pinned single-row toolbar stylesheet; validate releases before writing."""
import argparse
import hashlib
import json
import re
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--lab-root', type=Path, required=True)
parser.add_argument('--apply', action='store_true')
args = parser.parse_args()
root = args.lab_root.resolve()
css = Path(__file__).with_name('contract-editor.css').read_bytes()
revision = hashlib.sha256(css).hexdigest()[:12]
asset = 'apps/documenteditor/main/resources/css/contract-editor.css'
entry = 'apps/documenteditor/main/index.html'
release = root / 'deploy/releases/10.0.0-labesign9'
updates = {root / 'visual-source/editor.css': css}

def version_link(text):
    text, count = re.subn(r'resources/css/contract-editor\.css(?:\?layout=[a-f0-9]+)?',
                         'resources/css/contract-editor.css?layout=' + revision, text)
    if count != 1:
        raise SystemExit('Expected exactly one toolbar stylesheet link')
    return text

for base, manifest, prefix in [
    (root / 'upstream-build/visual/web-apps', root / 'upstream-build/visual-manifest.json', ''),
    (release, release / 'manifest.json', 'web-apps/'),
]:
    data = json.loads(manifest.read_text())
    for name, digest in data['files'].items():
        if hashlib.sha256((base / name).read_bytes()).hexdigest() != digest:
            raise SystemExit('Manifest mismatch: ' + str(base / name))
    for name, content in [(prefix + asset, css),
                          (prefix + entry, version_link((base / (prefix + entry)).read_text()).encode())]:
        updates[base / name] = content
        data['files'][name] = hashlib.sha256(content).hexdigest()
    updates[manifest] = (json.dumps(data, indent=2) + '\n').encode()
build = root / 'visual-source/build.py'
updates[build] = version_link(build.read_text()).encode()
changed = [str(p) for p, content in updates.items() if p.read_bytes() != content]
if args.apply:
    for path, content in updates.items():
        if path.read_bytes() != content:
            temporary = path.with_name(path.name + '.toolbar-tmp')
            temporary.write_bytes(content)
            temporary.replace(path)
print(json.dumps({'applied': args.apply, 'layout_revision': revision, 'changed_files': changed}))
