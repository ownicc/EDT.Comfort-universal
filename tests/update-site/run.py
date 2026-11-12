"""Exercise publication with real p2 archives; never build or launch EDT."""
from pathlib import Path
import hashlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]
SITE = "https://ownicc.github.io/EDT.Comfort-universal/"
SHA = "a" * 40
VERSION = "1.0.9.202611130900"
FEATURE = "tormozit.comfort.feature"
GROUP = FEATURE + ".feature.group"


def jar(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, value in files.items():
            archive.writestr(name, value)
    return buffer.getvalue()


def artifact(root, *, missing=False, group_version=VERSION, update=True, site=SITE):
    versions = {"tormozit.comfort": VERSION,
                "tormozit.comfort.early": "1.0.1.202611130900",
                "tormozit.comfort.checks": "1.0.67"}
    units = "".join(f"<unit id='{name}' version='{version}'/>" for name, version in versions.items())
    update_xml = f"<update id='{GROUP}' range='[0.0.0,{VERSION})'/>" if update else ""
    units += f"<unit id='{GROUP}' version='{group_version}'>{update_xml}</unit>"
    files = {"content.jar": jar({"content.xml": f"<repository><units>{units}</units></repository>"})}
    descriptors = []
    for name, version in versions.items():
        descriptors.append(f"<artifact classifier='osgi.bundle' id='{name}' version='{version}'/>")
        if not missing or name != "tormozit.comfort.early":
            files[f"plugins/{name}_{version}.jar"] = jar({"META-INF/MANIFEST.MF": "Manifest-Version: 1.0"})
    descriptors.append(f"<artifact classifier='org.eclipse.update.feature' id='{FEATURE}' version='{VERSION}'/>")
    files[f"features/{FEATURE}_{VERSION}.jar"] = jar({"feature.xml":
        f"<feature id='{FEATURE}' version='{VERSION}'><url><update url='{site}'/><discovery url='{site}'/></url></feature>"})
    files["artifacts.jar"] = jar({"artifacts.xml": "<repository><artifacts>" + "".join(descriptors) + "</artifacts></repository>"})
    files["p2.index"] = "version=1\nmetadata.repository.factory.order=content.jar,!\nartifact.repository.factory.order=artifacts.jar,!\n"
    root.mkdir()
    payload = jar(files)
    (root / "tormozit.comfort.zip").write_bytes(payload)
    (root / "SHA256SUMS").write_text(hashlib.sha256(payload).hexdigest() + "  tormozit.comfort.zip\n")
    (root / "commit.txt").write_text(SHA + "\n")
    return files


class PublicationTest(unittest.TestCase):
    def setUp(self):
        output = ROOT / ".tmp/update-site-tests"
        output.mkdir(parents=True, exist_ok=True)
        self.work = tempfile.TemporaryDirectory(dir=output)
        self.addCleanup(self.work.cleanup)
        self.root = Path(self.work.name)
        self.input = self.root / "artifact"
        self.output = self.root / "site"

    def run_cli(self, commit=SHA):
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run([sys.executable, str(ROOT / "scripts/prepare_update_site.py"),
            str(self.input), str(self.output), commit, SITE], capture_output=True, text=True, env=environment)

    def test_publish_same_p2_payload_with_installation_page_and_help(self):
        files = artifact(self.input)
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for name, data in files.items():
            expected = data.encode() if isinstance(data, str) else data
            self.assertEqual((self.output / name).read_bytes(), expected)
        self.assertEqual((self.output / "tormozit.comfort.zip").read_bytes(),
                         (self.input / "tormozit.comfort.zip").read_bytes())
        self.assertIn(SITE, (self.output / "index.html").read_text())
        self.assertNotIn("{{", (self.output / "index.html").read_text())
        self.assertTrue((self.output / "help/index.html").is_file())
        self.assertTrue((self.output / ".nojekyll").exists())

    def test_reject_tampered_archive(self):
        artifact(self.input)
        with (self.input / "tormozit.comfort.zip").open("ab") as stream:
            stream.write(b"tampered")
        result = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("checksum", result.stdout + result.stderr)

    def test_reject_other_commit(self):
        artifact(self.input)
        result = self.run_cli("b" * 40)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("commit", result.stdout + result.stderr)

    def test_reject_missing_bundle_payload(self):
        artifact(self.input, missing=True)
        result = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("tormozit.comfort.early", result.stdout + result.stderr)

    def test_reject_mismatched_feature_group(self):
        artifact(self.input, group_version="1.0.8")
        result = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("feature group", result.stdout + result.stderr)

    def test_reject_missing_update_chain(self):
        artifact(self.input, update=False)
        result = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("update", result.stdout + result.stderr)

    def test_reject_upstream_update_site(self):
        artifact(self.input, site="https://tormozit.github.io/EDT.Comfort/")
        result = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("update site", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
