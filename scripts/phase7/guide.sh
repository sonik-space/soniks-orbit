#!/usr/bin/env bash
# `tle-making-guide.txt` целиком, по HTTP.
#
#     make up && make migrate && bash scripts/phase7/guide.sh
#
# Гайд — ежедневный рабочий процесс оператора в `rffit` плюс `ikhnos`
# и `propagate`. До фазы 7 он воспроизводился примерно на 70%: не хватало
# пошагового фита с явной маской параметров, дописывания наблюдений
# в существующую сессию и проверки эксцентриситета.
#
# Соответствие шагов:
#
#   гайд                                        здесь
#   ------------------------------------------  -----------------------------
#   ./satnogs_waterfall_tabulation_helper.py    1. POST /sessions (авто)
#   cat obs1.dat obs2.dat > all.dat             2. POST .../observations
#   rffit -d ... -c l11.tle -i 98423            3. затравка
#   z→s→f→m→f→r→ctrl+h, только argp (4)         4. фит free=0001000
#   фит по 2-raan, 4-argp, 6-rev/day            5. фит free=0101010
#   (нашего умолчания в гайде нет)              6. фит с приорами
#   w — записать TLE                            7-9. reepoch + publish
#   ./ikhnos.py -t l12.tle ... 1039405          8. модельная кривая
#   propagate -c l12.tle -i 98423 -e 26005...   7. reepoch
#   проверить, что эксцентриситет не ноль       9. порог публикации
#
# В боевой каталог СОНИКС не пишет: публикация идёт режимом `propose`,
# который до Django не доходит вовсе.
set -euo pipefail

BASE=${BASE:-http://localhost:8000/api/v1}
# Два прохода объекта 64880 — те же, что в демонстрации фазы 2.
FIRST=${FIRST:-1527888}
SECOND=${SECOND:-1526972}

py() { python3 -c "$1"; }

wait_extraction() {
    for _ in $(seq 60); do
        BUSY=$(curl -fsS "${BASE}/sessions/$1" | py '
import json, sys
obs = json.load(sys.stdin)["observations"]
print(any(o["extraction_status"] in ("pending", "running") for o in obs))
')
        [ "${BUSY}" = "True" ] || return 0
        sleep 2
    done
    echo "   извлечение не завершилось за две минуты" >&2
    return 1
}

fit() {  # $1 сессия, $2 тело запроса, $3 подпись
    echo "   ${3}"
    curl -fsS -X POST "${BASE}/sessions/$1/fits" \
        -H 'Content-Type: application/json' -d "$2" | py '
import json, sys

f = json.load(sys.stdin)
c = f["config"]
mask = c.get("free", "1111111")
print("     маска {}  приоры {}".format(mask, "выключены" if c.get("priors_off") else "включены"))
print("     статус {}, RMS {:.4f} → {:.4f} кГц на {} точках".format(
    f["status"], f["rms_pre_khz"], f["rms_khz"], f["n_points"]))

names = ("inclination_deg", "raan_deg", "eccentricity", "argp_deg",
         "mean_anomaly_deg", "mean_motion_rev_day", "bstar")
a, b = f["elements_in"], f["elements_out"]
for i, name in enumerate(names):
    moved = abs(b[name] - a[name])
    if mask[i] == "0":
        assert moved == 0.0, "{} зажат маской, но сдвинулся на {}".format(name, moved)
    print("     {:<22}{:>14.7f} → {:>14.7f}{}".format(
        name, a[name], b[name], "   (зажат)" if mask[i] == "0" else ""))
print("     удержаны приором:", ", ".join(f["prior_dominated"]) or "ничего")
'
}

echo "1. POST ${BASE}/sessions  (наблюдение ${FIRST})"
UUID=$(curl -fsS -X POST "${BASE}/sessions" \
    -H 'Content-Type: application/json' \
    -d "{\"name\": \"гайд\", \"observation_ids\": [${FIRST}]}" \
    | py 'import json,sys; print(json.load(sys.stdin)["uuid"])')
echo "   сессия ${UUID}"
wait_extraction "${UUID}"

echo
echo "2. POST ${BASE}/sessions/{uuid}/observations  (дописываем ${SECOND})"
echo "   в гайде это \`cat obs1.dat obs2.dat > all.dat\`"
curl -fsS -X POST "${BASE}/sessions/${UUID}/observations" \
    -H 'Content-Type: application/json' \
    -d "{\"observation_ids\": [${SECOND}]}" | py '
import json, sys
s = json.load(sys.stdin)
print("   наблюдений в сессии:", len(s["observations"]))
assert len(s["observations"]) == 2
'
wait_extraction "${UUID}"

echo "   2a. повтор тем же списком обязан быть безвредным"
curl -fsS -X POST "${BASE}/sessions/${UUID}/observations" \
    -H 'Content-Type: application/json' \
    -d "{\"observation_ids\": [${SECOND}]}" | py '
import json, sys
assert len(json.load(sys.stdin)["observations"]) == 2, "наблюдение задвоилось"
print("   наблюдений по-прежнему 2 ✓")
'

echo
echo "3. PUT ${BASE}/sessions/{uuid}/seed  — затравка (меню \`c\` и клавиша \`t\`)"
curl -fsS "${BASE}/sessions/${UUID}" | py '
import json, sys
s = json.load(sys.stdin)
print("   источник затравки:", s["seed_source"])
print("  ", s["seed"]["tle1"])
'

echo "   3a. правка одного элемента поверх текущей затравки"
curl -fsS -X PUT "${BASE}/sessions/${UUID}/seed" \
    -H 'Content-Type: application/json' \
    -d '{"elements": {"eccentricity": 0.0016}}' | py '
import json, sys
s = json.load(sys.stdin)
print("   источник:", s["seed_source"])
print("  ", s["seed"]["tle2"])
assert s["seed_source"] == "manual"
'

echo "   3b. два способа сразу — 422, а не «который-то победит»"
curl -sS -X PUT "${BASE}/sessions/${UUID}/seed" \
    -H 'Content-Type: application/json' \
    -d '{"template": "leo", "elements": {"raan_deg": 1.0}}' \
    -o /dev/null -w '   код %{http_code}\n'

echo "   3c. битые строки отвергаются здесь, а не на фите"
curl -sS -X PUT "${BASE}/sessions/${UUID}/seed" \
    -H 'Content-Type: application/json' \
    -d '{"tle": {"tle0": "", "tle1": "1 мусор", "tle2": "2 мусор"}}' \
    -o /tmp/orbit-guide-bad-tle.json -w '   код %{http_code} — '
py 'import json; print(json.load(open("/tmp/orbit-guide-bad-tle.json"))["detail"])'

echo
echo "4. POST ${BASE}/sessions/{uuid}/fits  — шаги 3-5 гайда"
fit "${UUID}" '{"free": "0001000"}' \
    '4a. только аргумент перигея (клавиша 4) — сдвиг точек на частоту спутника'
fit "${UUID}" '{"free": "0101010"}' \
    '4b. три параметра: RAAN (2), аргумент перигея (4), среднее движение (6)'
fit "${UUID}" '{}' \
    '4c. наше умолчание: все семь свободны, слабо определённые держит приор'
fit "${UUID}" '{"priors_off": true}' \
    '4d. приоры выключены — так виден переобученный фит, к которому склонен rffit'

echo
echo "   4e. взаимоисключающие поля — 422"
for BODY in '{"priors_off": true, "prior_sigmas": {"raan_deg": 0.5}}' \
            '{"free": "0000000"}'; do
    curl -sS -X POST "${BASE}/sessions/${UUID}/fits" \
        -H 'Content-Type: application/json' -d "${BODY}" \
        -o /dev/null -w "   ${BODY} → %{http_code}\n"
done

echo
echo "5. GET .../observations/${FIRST}/track  — модельная кривая (замена ikhnos)"
curl -fsS "${BASE}/sessions/${UUID}/observations/${FIRST}/track" | py '
import json, sys
m = json.load(sys.stdin)["model"]
assert m, "кривую считает сервер, фронт SGP4 не гоняет (правило 9)"
print("   точек кривой: {}, смещение {:+.1f} .. {:+.1f} Гц".format(
    len(m["mjd"]), min(m["f_offset_hz"]), max(m["f_offset_hz"])))
'

FIT_RUN_ID=$(curl -fsS "${BASE}/sessions/${UUID}/fits" \
    | py 'import json,sys; print(json.load(sys.stdin)[0]["fit_run_id"])')

echo
echo "6. POST ${BASE}/fits/{id}/reepoch  — \`propagate -e\` из гайда"
curl -fsS -X POST "${BASE}/fits/${FIT_RUN_ID}/reepoch" \
    -H 'Content-Type: application/json' -d '{"epoch": "latest_observation"}' | py '
import json, sys
r = json.load(sys.stdin)
print("   эпоха", r["epoch"])
for line in (r["tle"]["tle1"], r["tle"]["tle2"]):
    print("  ", line)
    assert len(line) == 69, "длина {}".format(len(line))
# Шаг 7 гайда: эксцентриситет не должен схлопнуться в ноль.
ecc = float("0." + r["tle"]["tle2"][26:33])
print("   эксцентриситет после переноса: {:.7f}".format(ecc))
assert ecc > 1e-6, "эксцентриситет схлопнулся — rv2el зажимает отрицательный в ноль"
print("   эксцентриситет не ноль ✓")
'

echo
echo "7. POST ${BASE}/fits/{id}/publish  — порог качества (decisions/007)"
curl -sS -X POST "${BASE}/fits/${FIT_RUN_ID}/publish" \
    -H 'Content-Type: application/json' \
    -d '{"mode": "propose", "reepoch_to": {"epoch": "latest_observation"}}' \
    -o /tmp/orbit-guide-publish.json -w '   код %{http_code}\n'
py '
import json
p = json.load(open("/tmp/orbit-guide-publish.json"))
if "detail" in p:
    print("   порог не пройден:", p["detail"])
else:
    print("   режим {}, id в каталоге {}".format(p["mode"], p["published_tle_id"]))
    assert p["published_tle_id"] is None, "propose не должен ходить в Django"
    print("   в боевой каталог не ходили ✓")
'

echo
echo "8. Удаление: DELETE наблюдения и сессии"
curl -sS -X DELETE "${BASE}/sessions/${UUID}/observations/${SECOND}" \
    -o /dev/null -w '   удалено наблюдение, код %{http_code}\n'
echo "   8a. последнее наблюдение убрать нельзя"
curl -sS -X DELETE "${BASE}/sessions/${UUID}/observations/${FIRST}" \
    -o /tmp/orbit-guide-last-obs.json -w '   код %{http_code} — '
py 'import json; print(json.load(open("/tmp/orbit-guide-last-obs.json"))["detail"])'

curl -sS -X DELETE "${BASE}/sessions/${UUID}" \
    -o /dev/null -w '   удалена сессия, код %{http_code}\n'
curl -sS "${BASE}/sessions/${UUID}" -o /dev/null -w '   её больше нет, код %{http_code}\n'

echo
echo "Гайд пройден целиком."
