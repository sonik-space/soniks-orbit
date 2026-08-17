#!/usr/bin/env bash
# Демонстрация фазы 2: curl создаёт сессию и получает откалиброванные точки.
#
#     make up && make migrate && make demo
#
# Ожидаемый результат на наблюдении 1527888 — 362 точки и RMS 0.0250 кГц,
# то же число, что даёт стенд `scripts/phase0/end_to_end.py`, но полученное
# через HTTP: это и есть проверка, что цепочка доехала до сервиса целиком.
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
