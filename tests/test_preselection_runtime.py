"""Run the preselection UI contract against its real JavaScript runtime."""
from pathlib import Path
import shutil
import subprocess
import unittest


class PreselectionRuntimeTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node.js is needed for dashboard runtime tests')
    def test_preselection_filters_and_tracking(self):
        script = Path(__file__).with_name('preselection.test.cjs')
        result = subprocess.run(['node', '--test', str(script)], capture_output=True,
                                text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
