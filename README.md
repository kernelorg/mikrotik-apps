# mikrotik-apps

Собственный магазин приложений (custom app store) для меню `/app` в RouterOS.
Роутер получает по одному URL YAML-массив приложений и показывает их в WebFig
рядом со штатным каталогом MikroTik. Документация:
<https://manual.mikrotik.com/docs/containers/apps/#custom-apps>.

## Подключение к роутеру

Требуется RouterOS 7.22 или новее, пакет `container`, включённый режим
контейнеров (`/system/device-mode`), архитектура arm64 или x86.

```
/app/settings set app-store-urls="https://raw.githubusercontent.com/kernelorg/mikrotik-apps/main/apps.yaml"
/app/print
```

После этого приложения из `apps.yaml` появятся в `/app` и в WebFig.

## Приложения

| Имя | Образ | Архитектуры | Порты |
|-----|-------|-------------|-------|
| `mosquitto-go-auth` | `ghcr.io/kernelorg/mosquitto-go-auth-radius:<последний релиз>` | arm64 | 1883 MQTT, 9001 MQTT/WebSockets, 8883 MQTT/TLS (выключен по умолчанию) |

### mosquitto-go-auth

Брокер Mosquitto с плагином [mosquitto-go-auth](https://github.com/kernelorg/mosquitto-go-auth)
и RADIUS-бэкендом (MikroTik User Manager, FreeRADIUS). Версия образа совпадает
с тегом последнего релиза `kernelorg/mosquitto-go-auth`.

Перед запуском откройте YAML приложения (`/app/edit mosquitto-go-auth yaml`
или WebFig) и в блоке `go_auth_conf` поменяйте:

* `auth_opt_radius_servers` — адрес и порт RADIUS-сервера;
* `auth_opt_radius_secret` — shared secret.

На стороне User Manager нужно добавить брокер как RADIUS-клиент с адресом,
с которого приходят запросы контейнера (IP контейнера или адрес роутера при NAT):

```
/user-manager set enabled=yes
/user-manager/router add name=mosquitto address=<ip контейнера> shared-secret=<secret>
/user-manager/user-group add name=mqtt-sensors outer-auths=pap \
    attributes=Mikrotik-Group:sensors,Filter-Id:readwrite:sensors/%u/#,Filter-Id:read:status/#
/user-manager/user add name=sensor1 password=secret group=mqtt-sensors
```

Подробности по атрибутам, ACL и RadSec: README репозитория mosquitto-go-auth,
раздел «RADIUS».

Для TLS на 8883 положите `ca.crt`, `server.crt`, `server.key` в том `certs`
приложения и раскомментируйте блок `listener 8883` в конфиге `listeners_conf`.

## Устройство репозитория

```
apps.yaml               главный файл магазина (собирается скриптом, не править руками)
apps/<app>.yaml         по одному приложению на файл; {{version}} = тег образа
sources.yaml            откуда брать последний релиз для каждого приложения
scripts/build.py        сборка apps.yaml
.github/workflows/build.yml   пересборка только вручную (workflow_dispatch)
```

Формат RouterOS не поддерживает include, поэтому `apps.yaml` собирается:
скрипт берёт последний релиз из GitHub Releases каждого репозитория, проверяет,
что в registry есть образ с этим тегом и что в манифесте присутствуют нужные
архитектуры (`archs` в `sources.yaml`), подставляет тег вместо `{{version}}`
и склеивает файлы из `apps/` в один массив.

## Пересборка apps.yaml

Автоматической сборки нет: ни по расписанию, ни по push. Обновить файл можно
двумя способами.

**Кнопкой в GitHub:** Actions → «Build app store» → «Run workflow». Поле `pin`
позволяет зафиксировать версию (`mosquitto-go-auth=3.6.0`), флаг `commit`
управляет тем, будет ли результат закоммичен в `main`.

**Локально:**

```
pip install pyyaml
GITHUB_TOKEN=$(gh auth token) python3 scripts/build.py          # последний релиз
python3 scripts/build.py --pin mosquitto-go-auth=3.6.0          # фиксированная версия
python3 scripts/build.py --check                                # только проверка
git commit -am "Rebuild apps.yaml" && git push
```

## Добавление приложения

1. Создайте `apps/<имя>.yaml` — один YAML-документ с полями из
   [справочника MikroTik](https://manual.mikrotik.com/docs/containers/apps/#yaml-field-reference)
   (`name`, `descr`, `services`, …). В `image` используйте `{{version}}`.
2. Добавьте запись в `sources.yaml` (`file`, `release`, `image`, `tag`, `archs`).
3. Пересоберите `apps.yaml` и закоммитьте.
