#!/usr/bin/env python3
"""Сборка apps.yaml (custom app store для RouterOS /app) из apps/*.yaml.

Для каждого приложения из sources.yaml:
  1. запрашивается последний релиз репозитория GitHub (releases/latest);
  2. проверяется, что в registry есть образ с таким тегом и что его манифест
     содержит все архитектуры из списка archs;
  3. плейсхолдер {{version}} в файле приложения заменяется на тег образа;
  4. полученный документ проверяется как YAML и добавляется в массив.

Результат (apps.yaml) пишется только при явном запуске скрипта, никакой
автоматической сборки по расписанию нет.

Запуск:
  scripts/build.py                     # собрать apps.yaml
  scripts/build.py --pin mosquitto-go-auth=3.6.0   # зафиксировать версию
  scripts/build.py --check             # только проверить, не писать файл
Переменная GITHUB_TOKEN (необязательно) повышает лимит GitHub API.
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
PLACEHOLDER = "{{version}}"
OCI_INDEX = "application/vnd.oci.image.index.v1+json"
DOCKER_LIST = "application/vnd.docker.distribution.manifest.list.v2+json"
RAW_URL = "https://raw.githubusercontent.com/kernelorg/mikrotik-apps/main/apps.yaml"


def http_json(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def latest_release(repo):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "mikrotik-apps-build"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = http_json(f"https://api.github.com/repos/{repo}/releases/latest", headers)
    return data["tag_name"]


def registry_archs(image, tag):
    """Список архитектур в манифесте image:tag (анонимный pull из registry)."""
    host, _, path = image.partition("/")
    token_url = f"https://{host}/token?scope=repository:{path}:pull&service={host}"
    try:
        token = http_json(token_url)["token"]
    except (urllib.error.HTTPError, KeyError):
        token = None
    headers = {"Accept": f"{OCI_INDEX},{DOCKER_LIST}"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    manifest = http_json(f"https://{host}/v2/{path}/manifests/{urllib.parse.quote(tag)}", headers)
    archs = set()
    for m in manifest.get("manifests", []):
        p = m.get("platform") or {}
        if p.get("os") == "linux" and p.get("architecture") != "unknown":
            archs.add(p["architecture"] + (p.get("variant") or ""))
    if not archs and manifest.get("config"):
        archs.add("single-arch")  # одиночный манифест без списка платформ
    return archs


def app_name(path):
    doc = yaml.safe_load(path.read_text(encoding="utf-8").replace(PLACEHOLDER, "0"))
    return doc["name"]


def indent_as_list_item(text):
    """Превращает документ одного приложения в элемент YAML-массива.

    Комментарии в начале файла (до первого ключа) отбрасываются: это заметки
    для редактирующих apps/*.yaml, а не часть описания приложения.
    """
    lines = text.rstrip("\n").split("\n")
    while lines and (not lines[0].strip() or lines[0].lstrip().startswith("#")):
        lines.pop(0)
    out = ["- " + lines[0]]
    for line in lines[1:]:
        out.append(("  " + line) if line.strip() else "")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pin", action="append", default=[], metavar="NAME=TAG",
                    help="использовать заданный тег образа вместо последнего релиза")
    ap.add_argument("--check", action="store_true", help="только проверить, apps.yaml не писать")
    ap.add_argument("--output", default=str(ROOT / "apps.yaml"))
    args = ap.parse_args()
    pins = dict(p.split("=", 1) for p in args.pin)

    sources = yaml.safe_load((ROOT / "sources.yaml").read_text(encoding="utf-8"))
    items = []
    summary = []
    for src in sources["apps"]:
        path = ROOT / src["file"]
        text = path.read_text(encoding="utf-8")
        name = app_name(path)

        if name in pins:
            tag = pins[name]
            origin = "pin"
        else:
            release = latest_release(src["release"])
            tag = src.get("tag", "{version}").format(version=re.sub(r"^v", "", release))
            origin = f"release {release} of {src['release']}"

        archs = registry_archs(src["image"], tag)
        missing = set(src.get("archs", [])) - archs
        if missing:
            sys.exit(f"{name}: image {src['image']}:{tag} lacks {sorted(missing)}; has {sorted(archs)}")

        rendered = text.replace(PLACEHOLDER, tag)
        doc = yaml.safe_load(rendered)
        if not isinstance(doc, dict) or "name" not in doc or "services" not in doc:
            sys.exit(f"{name}: {src['file']} must be one app document with name and services")
        if PLACEHOLDER in rendered:
            sys.exit(f"{name}: unreplaced placeholder")
        items.append(indent_as_list_item(rendered))
        summary.append((name, f"{src['image']}:{tag}", origin, ",".join(sorted(archs))))

    header = (
        "# Файл собран автоматически скриптом scripts/build.py. Не редактируйте вручную:\n"
        "# правьте apps/*.yaml и sources.yaml, затем запустите сборку.\n"
        f"# URL для роутера: /app/settings set app-store-urls=\"{RAW_URL}\"\n"
    )
    output = header + "\n" + "\n\n".join(items) + "\n"
    yaml.safe_load(output)  # итоговый массив обязан быть валидным YAML

    for name, image, origin, archs in summary:
        print(f"{name}: {image} ({origin}; archs: {archs})")
    if args.check:
        print("check only, apps.yaml not written")
        return
    Path(args.output).write_text(output, encoding="utf-8")
    print(f"written {args.output}")


if __name__ == "__main__":
    main()
