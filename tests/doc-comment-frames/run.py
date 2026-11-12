"""Проверка реального EDT bytecode в отдельном Equinox без запуска UI и сборки плагина."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
POOL = Path(os.environ.get("EDT_BUNDLE_POOL", str(Path.home() / ".p2/pool/plugins")))
OUT = ROOT / ".tmp/doc-comment-frames"
OUT.mkdir(parents=True, exist_ok=True)
EXE = ".exe" if os.name == "nt" else ""
javac = Path(os.environ.get("JAVA_HOME", "")) / "bin" / ("javac" + EXE)
if not javac.is_file():
    found = shutil.which("javac")
    candidates = sorted(Path("/opt/1C/1CE/components").glob("axiom-jdk-full-*/bin/javac"))
    if not found and not candidates:
        raise SystemExit("Укажите JAVA_HOME с JDK 17 или новее")
    javac = Path(found) if found else candidates[-1]
asm = sorted(POOL.glob("org.objectweb.asm_[0-9]*.jar"))
osgi = sorted(POOL.glob("org.eclipse.osgi_[0-9]*.jar"))
if not asm or not osgi or not list(POOL.glob("com._1c.g5.v8.dt.bsl.comment_*.jar")):
    raise SystemExit("Укажите EDT_BUNDLE_POOL с бандлами EDT")

# Исполняем непосредственно код transformer и двух его точек входа.
# Остальная часть класса требует работающие сервисы EDT и здесь не используется.
source = (ROOT / "plugin/src/tormozit/BslDocCommentDescriptionFix.java").read_text(encoding="utf-8")
constants = source[source.index("    static final String PROP_AFTER_PARSE"):
                   source.index("    private static final AtomicBoolean installed")]
transform = source[source.index("    static byte[] transformClass("):]
harness = OUT / "src/tormozit/BslDocCommentDescriptionFix.java"
harness.parent.mkdir(parents=True, exist_ok=True)
harness.write_text("""package tormozit;
import java.lang.instrument.*;
import java.security.ProtectionDomain;
import java.util.concurrent.atomic.AtomicBoolean;
import org.objectweb.asm.*;
import org.osgi.framework.hooks.weaving.*;
public final class BslDocCommentDescriptionFix {
""" + constants + transform, encoding="utf-8")
cp = os.pathsep.join(map(str, [asm[-1], osgi[-1]]))
classes = OUT / "classes"
classes.mkdir(exist_ok=True)
subprocess.run([str(javac), "--release", "17", "-encoding", "UTF-8", "-cp", cp,
                "-d", str(classes), str(harness),
                str(Path(__file__).with_name("DocCommentFramesTest.java"))], check=True)
java = javac.with_name("java" + EXE)
for mode in ("stock", "woven", "instrumentation"):
    with tempfile.TemporaryDirectory(prefix="osgi-", dir=OUT) as state:
        subprocess.run([str(java), "-Xverify:all", "-cp", str(classes) + os.pathsep + cp,
                        "tormozit.DocCommentFramesTest", str(POOL), state, mode], check=True, timeout=90)
