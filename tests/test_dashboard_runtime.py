"""Include dependency-free JavaScript runtime tests in the normal Python suite."""
from pathlib import Path
import shutil
import subprocess
import unittest


class DashboardRuntimeTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node.js is needed for dashboard runtime tests')
    def test_dashboard_content_and_tracking(self):
        script = Path(__file__).with_name('dashboard_content.test.cjs')
        result = subprocess.run(['node', '--test', str(script)], capture_output=True, text=True,
                                encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
