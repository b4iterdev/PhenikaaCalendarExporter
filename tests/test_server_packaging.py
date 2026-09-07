import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


class PackagingArtifactTests(unittest.TestCase):
    def test_built_distribution_includes_server_static_stylesheet(self):
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            wheel_dir = Path(directory)
            _ = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "wheel",
                    "--no-deps",
                    "--wheel-dir",
                    str(wheel_dir),
                    str(project_root),
                ],
                check=True,
                cwd=project_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            wheels = sorted(wheel_dir.glob("*.whl"))
            self.assertEqual(len(wheels), 1)
            with zipfile.ZipFile(wheels[0]) as archive:
                self.assertIn("server/static/styles.css", archive.namelist())


if __name__ == "__main__":
    _ = unittest.main()
