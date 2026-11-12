"""Publish the exact verified p2 archive and its documentation to GitHub Pages."""
from pathlib import Path, PurePosixPath
import hashlib
import importlib.util
import json
import shutil
import sys
import xml.etree.ElementTree as ET
import zipfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
FEATURE = "tormozit.comfort.feature"
GROUP = FEATURE + ".feature.group"
BUNDLES = ("tormozit.comfort", "tormozit.comfort.early", "tormozit.comfort.checks")


def metadata(root, name):
    with zipfile.ZipFile(root / (name + ".jar")) as archive:
        return ET.fromstring(archive.read(name + ".xml"))


def validate_repository(root, site_url):
    content = metadata(root, "content")
    artifacts = metadata(root, "artifacts")
    versions = {}
    for identifier in BUNDLES:
        unit = content.find(f"./units/unit[@id='{identifier}']")
        if unit is None:
            raise ValueError("Missing p2 unit: " + identifier)
        versions[identifier] = unit.attrib["version"]
    version = versions[BUNDLES[0]]
    group = content.find(f"./units/unit[@id='{GROUP}'][@version='{version}']")
    if group is None:
        raise ValueError("Mismatched feature group version")
    update = group.find(f"./update[@id='{GROUP}']")
    if update is None or update.get("range") != f"[0.0.0,{version})":
        raise ValueError("Missing feature group update chain")
    payloads = [("osgi.bundle", name, v, "plugins") for name, v in versions.items()]
    payloads.append(("org.eclipse.update.feature", FEATURE, version, "features"))
    for classifier, name, payload_version, directory in payloads:
        descriptor = artifacts.find(f"./artifacts/artifact[@classifier='{classifier}'][@id='{name}'][@version='{payload_version}']")
        if descriptor is None:
            raise ValueError("Missing p2 artifact: " + name)
        payload = root / directory / f"{name}_{payload_version}.jar"
        with zipfile.ZipFile(payload) as archive:
            if archive.testzip() is not None:
                raise ValueError("Corrupt payload: " + name)
    with zipfile.ZipFile(root / "features" / f"{FEATURE}_{version}.jar") as archive:
        feature = ET.fromstring(archive.read("feature.xml"))
    if feature.get("id") != FEATURE or feature.get("version") != version:
        raise ValueError("Mismatched feature payload")
    for tag in ("update", "discovery"):
        url = feature.find("./url/" + tag)
        if url is None or url.get("url", "").rstrip("/") != site_url.rstrip("/"):
            raise ValueError("Feature " + tag + " site does not match this update site")
    return version


def prepare(artifact, output, commit, site_url):
    if (artifact / "commit.txt").read_text().strip() != commit:
        raise ValueError("Artifact commit differs from this build")
    archive = artifact / "tormozit.comfort.zip"
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    if checksum != (artifact / "SHA256SUMS").read_text().split()[0]:
        raise ValueError("Archive checksum mismatch")
    output.mkdir(parents=True)
    with zipfile.ZipFile(archive) as payload:
        for name in payload.namelist():
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("Unsafe archive path: " + name)
        payload.extractall(output)
    version = validate_repository(output, site_url)
    for name in ("tormozit.comfort.zip", "SHA256SUMS", "commit.txt"):
        shutil.copy2(artifact / name, output / name)
    info = {"version": version, "commit": commit, "sha256": checksum}
    (output / "build-info.json").write_text(json.dumps(info, indent=2) + "\n")
    template = (ROOT / "site/index.html").read_text(encoding="utf-8")
    template = template.replace("{{SITE_BASE_URL}}", site_url).replace("{{BUILD_VERSION}}", version)
    (output / "index.html").write_text(template, encoding="utf-8")
    # Reuse the existing Docsify publisher without rewriting p2 metadata or payloads.
    spec = importlib.util.spec_from_file_location("comfort_site", ROOT / ".github/workflows/generate_composite.py")
    docs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(docs)
    docs.deploy_dir = str(output)
    docs.publish_help_site(str(ROOT))
    (output / ".nojekyll").touch()
    print(f"Validated update site {version}, commit {commit}, SHA256 {checksum}")
    return version


if __name__ == "__main__":
    prepare(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4])
