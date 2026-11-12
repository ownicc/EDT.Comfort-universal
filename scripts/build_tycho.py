#!/usr/bin/env python3
"""Запуск сборки Tycho в build; кэш, временные файлы и журналы находятся в .tmp."""
from pathlib import Path
import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]


def default_java_home():
    if os.environ.get('JAVA_HOME'):
        return Path(os.environ['JAVA_HOME'])
    javac = shutil.which('javac')
    if javac:
        return Path(javac).resolve().parents[1]
    candidates = sorted(Path('/opt/1C/1CE/components').glob('axiom-jdk-full-*/bin/javac'))
    return candidates[-1].parents[1] if candidates else None


def run_maven(arguments, *, project=ROOT, work=None, java_home=None):
    project = Path(project).resolve()
    jdk = Path(java_home or default_java_home() or '').resolve()
    java = jdk / 'bin' / ('java.exe' if os.name == 'nt' else 'java')
    if not java.is_file():
        raise RuntimeError('Укажите JAVA_HOME или --java-home с JDK 21 или новее для Tycho 5')
    work = work or ROOT / '.tmp/tycho-runs' / datetime.datetime.now().strftime('%Y%m%d%H%M%S%f')
    work.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment['JAVA_HOME'] = str(jdk)
    environment['MAVEN_USER_HOME'] = str(ROOT / '.tmp/maven/home')
    temporary = project / '.tmp/maven/tmp'
    temporary.mkdir(parents=True, exist_ok=True)
    for name in ('TMPDIR', 'TMP', 'TEMP'):
        environment[name] = str(temporary)
    environment['MAVEN_OPTS'] = (environment.get('MAVEN_OPTS', '')
        + ' -Xmx2g -Djava.awt.headless=true -Dfile.encoding=UTF-8 -Djava.io.tmpdir=.tmp/maven/tmp')
    version = subprocess.run([str(java), '-XshowSettings:properties', '-version'],
                             capture_output=True, text=True, errors='replace', env=environment)
    (work / 'java-version.log').write_text(version.stdout + version.stderr, encoding='utf-8')
    match = re.search(r'java.specification.version\s*=\s*(\d+)', version.stderr)
    if version.returncode or not match or int(match[1]) < 21:
        raise RuntimeError('Tycho 5 требует JDK 21 или новее; классы плагина по-прежнему Java 17')
    wrapper = ROOT / ('mvnw.cmd' if os.name == 'nt' else 'mvnw')
    command = [str(wrapper), '--batch-mode', '--no-transfer-progress',
               '-Dmaven.repo.local=' + str(ROOT / '.tmp/maven/repository'),
               '-Dtycho.localArtifacts=ignore', '-Declipse.p2.mirrors=false', *arguments]
    (work / 'command.json').write_text(json.dumps(command, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'JDK: {jdk}\nTycho: 5.0.4; Java плагина: 17\nЖурнал: {work / "build.log"}', flush=True)
    with (work / 'build.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen(command, cwd=project, env=environment, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')
        for line in process.stdout:
            print(line, end='', flush=True)
            log.write(line)
            log.flush()
        return process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Maven validate без компиляции плагина')
    parser.add_argument('--version', action='store_true', help='Проверить Maven Wrapper и JDK')
    parser.add_argument('--java-home', type=Path)
    args, extra = parser.parse_known_args()
    goal = '--version' if args.version else 'validate' if args.check else 'verify'
    if args.check:
        extra.insert(0, '-Dtycho.target.eager=true')
    code = run_maven([goal, *extra], java_home=args.java_home)
    if code:
        raise SystemExit(code)
    if goal == 'verify':
        print('Установочный архив: ' + str(ROOT / 'build/comfort.site/tormozit.comfort.zip'))


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError) as error:
        print('Ошибка: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
