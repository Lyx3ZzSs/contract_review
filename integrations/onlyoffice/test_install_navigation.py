"""Exercise upgrades against a small isolated lab release, never the live editor."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent

class InstallerTest(unittest.TestCase):
    def test_content_changes_invalidate_url_and_repeated_install_is_empty(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            installer = root / 'installer'
            installer.mkdir()
            for name in ('install-navigation.py', 'navigation-bridge.js', 'editor-service-worker.js'):
                shutil.copyfile(HERE / name, installer / name)
            source = root / 'visual-source'
            source.mkdir()
            (source / 'nginx.conf').write_text('# existing routes\n')
            (source / 'integration-bridge.js').write_text('old')
            (source / 'build.py').write_text("import hashlib\n# Derive the entry\nentry=entry.replace('</head>','<script src=\"resources/integration-bridge.js?navigation=31\"></script>')\napi=out/'api.js'\n")
            release = root / 'deploy/releases/10.0.0-labesign9'
            output = root / 'upstream-build/visual/web-apps'
            index = 'apps/documenteditor/main/index.html'
            bridge = 'apps/documenteditor/main/resources/integration-bridge.js'
            for base, manifest, prefix in ((output, root/'upstream-build/visual-manifest.json', ''), (release, release/'manifest.json', 'web-apps/')):
                files = {prefix+index: '<script src="resources/integration-bridge.js?navigation=31"></script>', prefix+bridge: 'old'}
                if prefix:
                    files['nginx.conf'] = '# existing routes\n'
                for name, content in files.items():
                    path = base/name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content)
                manifest.write_text(json.dumps({'files': {name: hashlib.sha256(content.encode()).hexdigest() for name, content in files.items()}}))
            def run(apply=False):
                return json.loads(subprocess.check_output([sys.executable, str(installer/'install-navigation.py'), '--lab-root', str(root), *(['--apply'] if apply else [])], text=True))
            inode = (release/'nginx.conf').stat().st_ino
            run(True)
            old_html = (output/index).read_text()
            self.assertIn('&v=', old_html)
            self.assertEqual((release/'nginx.conf').stat().st_ino, inode)
            self.assertEqual(run()['changed_files'], [])
            with (installer/'navigation-bridge.js').open('a') as file:
                file.write('\n// next release\n')
            run(True)
            self.assertNotEqual((output/index).read_text(), old_html)
            self.assertEqual(run()['changed_files'], [])
            self.assertIn('v={bridge_hash}', (source/'build.py').read_text())
            compile((source/'build.py').read_text(), 'build.py', 'exec')

if __name__ == '__main__':
    unittest.main()
