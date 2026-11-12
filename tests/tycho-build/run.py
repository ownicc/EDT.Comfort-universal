"""Native Tycho integration on synthetic sources only; never builds the Comfort plugin."""
from pathlib import Path
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'scripts'))
import build_tycho

output = ROOT / '.tmp/tycho-tests'
output.mkdir(parents=True, exist_ok=True)
# An ordinary CLI launch must not create Python caches beside repository scripts.
probe = subprocess.run([sys.executable, str(ROOT / 'scripts/build_tycho.py'), '--version'],
                       cwd=ROOT, capture_output=True, text=True)
assert probe.returncode == 0, probe.stdout + probe.stderr
assert not list((ROOT / 'scripts/__pycache__').glob('build_local.*.pyc')), 'CLI wrote cache outside .tmp'

with tempfile.TemporaryDirectory(dir=output) as temporary:
    fixture = Path(temporary)
    # Copy production Maven configuration; only source/target contents are synthetic.
    shutil.copy2(ROOT / 'pom.xml', fixture / 'pom.xml')
    (fixture / '.mvn').mkdir()
    for name in ('plugin', 'plugin.early', 'plugin.checks', 'feature', 'site', 'target'):
        (fixture / name).mkdir()
        shutil.copy2(ROOT / name / 'pom.xml', fixture / name / 'pom.xml')
    (fixture / 'target/tp.target').write_text('<target name="Fixture"><locations/></target>')
    shutil.copy2(ROOT / 'site/category.xml', fixture / 'site/category.xml')
    # Compile against an optional bundle while retaining its optional runtime requirement.
    projects = [
        ('plugin.early', 'tormozit.comfort.early', '1.0.1.qualifier', 'early', '',
         'public static int n() { return 42; }'),
        ('plugin', 'tormozit.comfort', '1.0.9.qualifier', 'main', 'tormozit.comfort.early;resolution:=optional',
         'public static int n() { return early.Probe.n(); }'),
        ('plugin.checks', 'tormozit.comfort.checks', '1.0.67', 'checks', 'tormozit.comfort',
         'public static int n() { return main.Probe.n(); }'),
    ]
    plugins = []
    for folder, name, version, package, required, body in projects:
        project = fixture / folder
        (project / 'META-INF').mkdir()
        text = ('Manifest-Version: 1.0\nBundle-ManifestVersion: 2\nBundle-SymbolicName: ' + name
                + '\nBundle-Version: ' + version + '\nBundle-RequiredExecutionEnvironment: JavaSE-17\n'
                + 'Export-Package: ' + package + '\n')
        if required:
            text += 'Require-Bundle: ' + required + '\n'
        (project / 'META-INF/MANIFEST.MF').write_text(text + '\n')
        (project / 'build.properties').write_text('source.. = src/\nbin.includes = META-INF/, .\n')
        source = project / 'src' / package
        source.mkdir(parents=True)
        # ECJ must support the leading BOM that previously broke javac.
        (source / 'Probe.java').write_bytes(('\ufeffpackage ' + package + '; public class Probe { ' + body + ' }\n').encode())
        (source / 'data.txt').write_bytes(b'fixture source resource\r\n')
        plugins.append('<plugin id="' + name + '" version="0.0.0" unpack="false"/>')
    (fixture / 'feature/feature.xml').write_text('<feature id="tormozit.comfort.feature" label="Fixture" version="1.0.9.qualifier">' + ''.join(plugins) + '</feature>')
    (fixture / 'feature/build.properties').write_text('bin.includes = feature.xml\n')
    code = build_tycho.run_maven(['verify'], project=fixture, work=output / 'latest')
    assert code == 0, 'Synthetic Tycho build failed: .tmp/tycho-tests/latest/build.log'
    archive = fixture / 'build/comfort.site/tormozit.comfort.zip'
    assert archive.is_file(), 'Missing p2 archive: ' + str(archive)
    with zipfile.ZipFile(archive) as repository:
        assert {'content.jar', 'artifacts.jar'} <= set(repository.namelist())
        names = repository.namelist()
        for _, name, version, package, _, _ in projects:
            jar_name = next(n for n in names if n.startswith('plugins/' + name + '_') and n.endswith('.jar'))
            import io
            with zipfile.ZipFile(io.BytesIO(repository.read(jar_name))) as bundle:
                bytecode = bundle.read(package + '/Probe.class')
                assert int.from_bytes(bytecode[6:8], 'big') == 61
                assert bundle.read(package + '/data.txt') == b'fixture source resource\r\n'
                if name == 'tormozit.comfort':
                    assert b'tormozit.comfort.early;resolution:=optional' in bundle.read('META-INF/MANIFEST.MF')
                if name == 'tormozit.comfort.checks':
                    assert b'Bundle-Version: 1.0.67' in bundle.read('META-INF/MANIFEST.MF')
print('PASS native Tycho: three synthetic bundles, optional compile dependency with optional runtime metadata, dependency order, BOM, Java17, resources, fixed checks version and p2 ZIP')
