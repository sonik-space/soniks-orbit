#!/usr/bin/env bash
# Демонстрация: curl создаёт сессию, получает откалиброванные точки,
# правит их руками и перезапускает извлечение.
#
#     make up && make migrate && make demo
#
# Шаги 1-3 — фаза 2. Ожидаемый результат на наблюдении 1527888 — 362 точки
# и RMS 0.0250 кГц, то же число, что даёт стенд `scripts/phase0/end_to_end.py`,
# но полученное через HTTP: это и есть проверка, что цепочка доехала
# до сервиса целиком.
#
# Шаги 4-5 — фаза 3. Проверяют два свойства, которые иначе всплыли бы
# только в бою: `f_abs_hz` считает сервер, а не клиент (правило 9),
# и ручная точка переживает повторное извлечение.
set -euo pipefail

BASE=${BASE:-http://localhost:8000/api/v1}
OBS=${1:-1527888}

echo "1. POST ${BASE}/sessions  (наблюдение ${OBS})"
UUID=$(curl -fsS -X POST "${BASE}/sessions" \
    -H 'Content-Type: application/json' \
    -d "{\"name\": \"демонстрация фазы 2\", \"observation_ids\": [${OBS}]}" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["uuid"])')
echo "   сессия ${UUID}"

echo
echo "2. GET ${BASE}/sessions/${UUID}  — ждём, пока задача извлечения отработает"
for _ in $(seq 30); do
    STATUS=$(curl -fsS "${BASE}/sessions/${UUID}" \
        | python3 -c 'import json,sys; print(json.load(sys.stdin)["observations"][0]["extraction_status"])')
    [ "${STATUS}" = "pending" ] || [ "${STATUS}" = "running" ] || break
    sleep 2
done
curl -fsS "${BASE}/sessions/${UUID}" | python3 -m json.tool --no-ensure-ascii

echo
echo "3. GET ${BASE}/sessions/${UUID}/observations/${OBS}/track"
curl -fsS "${BASE}/sessions/${UUID}/observations/${OBS}/track" | python3 -c '
import json, sys
t = json.load(sys.stdin)
c, p = t["calibration"], t["points"]
print("извлечение:", t["extraction"])
if c:
    print("калибровка: рамка {}x{} от ({},{}), {} .. {}".format(
        c["plot_w"], c["plot_h"], c["plot_left"], c["plot_top"], c["t_min"], c["t_max"]))
    print("            полоса {} Гц, {:.2f} Гц/канал, центр {}".format(
        c["samp_rate"], c["bin_hz"], c["center_freq_hz"]))
n = len(p["mjd"])
print("точек:", n)
for i in ({0, n // 2, n - 1} if n else set()):
    print("  [{:>4}] mjd {:.6f}  f_abs {:.1f} Гц  смещение {:+.1f} Гц  вес {:.2f}".format(
        i, p["mjd"][i], p["f_abs_hz"][i], p["f_offset_hz"][i], p["weight"][i]))
'

TRACK="${BASE}/sessions/${UUID}/observations/${OBS}/track"
MANUAL_OFFSET_HZ=1234.5

echo
echo "4. PUT ${TRACK}  — добавляем ручную точку"
curl -fsS "${TRACK}" | python3 -c "
import json, sys

t = json.load(sys.stdin)
c, p = t['calibration'], t['points']
if not c:
    sys.exit('нет калибровки — извлечение не удалось, шаг 4 бессмысленен')

# Время берётся из калибровки, а не из точек: ручная разметка должна
# работать и на наблюдении, где извлечение не нашло ничего.
from datetime import datetime
t_min = datetime.fromisoformat(c['t_min'].replace('Z', '+00:00'))
mjd = t_min.timestamp() / 86400.0 + 40587.0

body = {'points': {
    'mjd':         [*p['mjd'], mjd],
    'f_offset_hz': [*p['f_offset_hz'], ${MANUAL_OFFSET_HZ}],
    'snr':         [*p['snr'], 0.0],
    'weight':      [*p['weight'], 1.0],
    'enabled':     [*p['enabled'], True],
    'source':      [*p['source'], 'manual'],
}}
json.dump(body, sys.stdout)
" > /tmp/orbit-demo-track.json

curl -fsS -X PUT "${TRACK}" \
    -H 'Content-Type: application/json' \
    -d @/tmp/orbit-demo-track.json \
    | python3 -c '
import json, sys

t = json.load(sys.stdin)
p, center = t["points"], t["calibration"]["center_freq_hz"]
i = p["source"].index("manual")
print("   ручная точка [{}]: смещение {:+.1f} Гц → f_abs {:.1f} Гц".format(
    i, p["f_offset_hz"][i], p["f_abs_hz"][i]))
print("   всего точек:", len(p["mjd"]))
# f_abs = f_центра − f_смещение: клиент прислал только смещение (правило 9).
assert abs(p["f_abs_hz"][i] + p["f_offset_hz"][i] - center) < 1e-6, \
    "сервер посчитал f_abs не по формуле ядра received_freq_hz"
print("   f_abs посчитан сервером по received_freq_hz ✓")
'

echo
echo "5. POST ${TRACK%/track}/reextract  — повтор с другим snr_threshold"
curl -fsS -X POST "${TRACK%/track}/reextract" \
    -H 'Content-Type: application/json' \
    -d '{"snr_threshold": 5.0}' -o /dev/null -w '   код %{http_code}\n'

# Пауза до первого опроса: статус переводит воркер, и без неё цикл увидел бы
# ещё прежнее `ok` и вышел, не дождавшись повтора.
sleep 3
for _ in $(seq 30); do
    STATUS=$(curl -fsS "${BASE}/sessions/${UUID}" \
        | python3 -c 'import json,sys; print(json.load(sys.stdin)["observations"][0]["extraction_status"])')
    [ "${STATUS}" = "pending" ] || [ "${STATUS}" = "running" ] || break
    sleep 2
done

curl -fsS "${TRACK}" | python3 -c '
import json, sys

p = json.load(sys.stdin)["points"]
manual = p["source"].count("manual")
print("   точек после повтора:", len(p["mjd"]), "из них ручных:", manual)
assert manual == 1, "ручная точка не пережила повторное извлечение"
assert p["mjd"] == sorted(p["mjd"]), "порядок точек не восстановлен по времени"
print("   ручная разметка сохранена ✓")
'

curl -fsS "${BASE}/sessions/${UUID}" | python3 -c '
import json, sys

o = json.load(sys.stdin)["observations"][0]
print("   RMS {:.4f} кГц на {} точках".format(o["rms_khz"], o["n_points"]))
print("   RMS вырос против 0.0250: точка поставлена наугад, и диагностика")
print("   считается по тому набору, который есть, а не по прежнему ✓")
'

# ---------------------------------------------------------------------------
# Шаг 6 — фаза 4. Фит синхронный: ни job id, ни опроса состояния.
#
# Сессия своя, из двух проходов объекта 64880: фит по одному наблюдению
# запрещён (algorithms.md §4.4), и это здесь тоже проверяется.
FIT_OBS=${FIT_OBS:-1527888,1526972}

echo
echo "6. POST ${BASE}/sessions/{uuid}/fits  (наблюдения ${FIT_OBS})"

echo "   6a. отказ на односессионном наборе"
curl -sS -X POST "${BASE}/sessions/${UUID}/fits" \
    -H 'Content-Type: application/json' -d '{}' \
    -o /tmp/orbit-demo-refusal.json -w '   код %{http_code} — ' \
    | cat
python3 -c '
import json
print(json.load(open("/tmp/orbit-demo-refusal.json"))["detail"])
'

FIT_UUID=$(curl -fsS -X POST "${BASE}/sessions" \
    -H 'Content-Type: application/json' \
    -d "{\"name\": \"демонстрация фазы 4\", \"observation_ids\": [${FIT_OBS}]}" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["uuid"])')
echo "   6b. сессия ${FIT_UUID}, ждём извлечение"
for _ in $(seq 60); do
    BUSY=$(curl -fsS "${BASE}/sessions/${FIT_UUID}" | python3 -c '
import json, sys
obs = json.load(sys.stdin)["observations"]
print(any(o["extraction_status"] in ("pending", "running") for o in obs))
')
    [ "${BUSY}" = "True" ] || break
    sleep 2
done

echo "   6c. фит"
curl -fsS -X POST "${BASE}/sessions/${FIT_UUID}/fits" \
    -H 'Content-Type: application/json' -d '{}' \
    | python3 -c '
import json, sys

f = json.load(sys.stdin)
print("   статус {}, RMS {:.4f} → {:.4f} кГц на {} точках".format(
    f["status"], f["rms_pre_khz"], f["rms_khz"], f["n_points"]))
for o in f["per_observation"]:
    print("     наблюдение {}: {:>4} точек, RMS {:.4f} кГц, несущая {:.1f} Гц".format(
        o["observation_id"], o["n"], o["rms_khz"], o["carrier_hz"]))
print("   удержаны приором:", ", ".join(f["prior_dominated"]) or "ничего")
print("  ", f["tle"]["tle1"])
print("  ", f["tle"]["tle2"])

# Невязки идут индекс-в-индекс с точками наблюдения: пара
# (observation_id, index) — ключ выделения во всех трёх панелях UI.
for obs_id, block in f["residuals"].items():
    assert len(block["mjd"]) == len(block["residual_khz"]), obs_id
print("   невязки индекс-в-индекс с точками ✓")
'

echo
echo "   6d. модельная кривая приходит вместе с треком (замена ikhnosoniks)"
curl -fsS "${BASE}/sessions/${FIT_UUID}/observations/${OBS}/track" | python3 -c '
import json, sys

m = json.load(sys.stdin)["model"]
assert m, "модельной кривой нет: её считает сервер, фронт SGP4 не гоняет"
print("   точек кривой: {}, смещение {:+.1f} .. {:+.1f} Гц".format(
    len(m["mjd"]), min(m["f_offset_hz"]), max(m["f_offset_hz"])))
'

curl -fsS "${BASE}/sessions?limit=5" | python3 -c '
import json, sys
for s in json.load(sys.stdin):
    print("   {}  {}  rms {}".format(s["uuid"][:8], s["status"], s["rms_khz"]))
'

# ---------------------------------------------------------------------------
# Шаги 7-8 — фаза 5. Ни один из них не пишет в боевой каталог СОНИКС:
# шаг 7 только считает, шаг 8 идёт режимом `propose`, который до Django
# не доходит вовсе. Публикации из демонстрации нет и быть не может.

FIT_RUN_ID=$(curl -fsS "${BASE}/sessions/${FIT_UUID}/fits" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["fit_run_id"])')

echo
echo "7. POST ${BASE}/fits/${FIT_RUN_ID}/reepoch  (замена sattools/propagate)"
for BODY in '{"epoch": "latest_observation"}' '{"epoch_yyddd": "26005.391632037"}'; do
    echo "   запрос ${BODY}"
    curl -fsS -X POST "${BASE}/fits/${FIT_RUN_ID}/reepoch" \
        -H 'Content-Type: application/json' -d "${BODY}" \
        | python3 -c '
import json, sys

r = json.load(sys.stdin)
lines = [r["tle"]["tle1"], r["tle"]["tle2"]]
print("   эпоха", r["epoch"])
for line in lines:
    print("  ", line)
    assert len(line) == 69, "длина {}, а Django валидирует ровно 69".format(len(line))
    digits = sum(int(c) for c in line[:68] if c.isdigit()) + line[:68].count("-")
    assert int(line[68]) == digits % 10, "контрольная сумма не сходится"
print("   69 символов и контрольная сумма ✓")
'
done

echo
echo "8. POST ${BASE}/fits/{id}/publish  — порог качества (decisions/007)"

# Порог здесь не только проверяется, но и **меряется на реальных данных**:
# из четырёх условий три видны в ответе фита, а расхождение положения
# с затравкой на эпохе до фазы 5 никто не считал.
echo "   8a. предложение по хорошему прогону: порог пройден"
curl -fsS -X POST "${BASE}/fits/${FIT_RUN_ID}/publish" \
    -H 'Content-Type: application/json' \
    -d '{"mode": "propose", "reepoch_to": {"epoch": "latest_observation"}}' \
    | python3 -c '
import json, sys

p = json.load(sys.stdin)
print("   режим {}, id в каталоге {}".format(p["mode"], p["published_tle_id"]))
assert p["published_tle_id"] is None, "propose не должен ходить в Django"
print("   в боевой каталог не ходили ✓")
'

echo
echo "9. GET ${BASE}/publications  — админ-вид до первой боевой публикации"
curl -fsS "${BASE}/publications?days=7" | python3 -c '
import json, sys
rows = json.load(sys.stdin)
print("   записей за 7 дней:", len(rows))
for r in rows[:5]:
    print("   {}  {}  norad {}  RMS {:.4f}  {} точек  id {}".format(
        r["published_at"], r["published_mode"], r["norad_id"],
        r["rms_khz"], r["n_points"], r["published_tle_id"]))
'
