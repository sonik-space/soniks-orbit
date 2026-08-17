# soniks-orbit

Сервис определения и уточнения орбитальных параметров по наблюдениям сети
СОНИКС. Документация — в [docs/](docs/), читать в порядке из
[docs/README.md](docs/README.md); начинать обязательно с
[docs/ai-development-rules.md](docs/ai-development-rules.md).

## Запуск

```bash
cp env.example .env
make up          # postgres, rabbitmq, api, taskiq-воркер
make migrate     # alembic upgrade head
make demo        # сессия по наблюдению 1527888 через HTTP
```

Документация OpenAPI — `http://localhost:8000/api/v1/docs`.
Локально аутентификация выключается `APP__DISABLE_AUTH=true`; валидатор
в `AppSettings` не даст включить это в dev или prod.

Данные берутся из **боевого** Django (`sonik.space`), а не из реплики dev2:
опубликованное на реплике TLE не дошло бы до планирования наблюдений реальной
сети ([decisions/009](docs/decisions/009-prod-data.md)).

## Проверка

```bash
make test        # 141 тест
make gate        # тесты плюс два числа, которые нельзя ухудшать
```

Два числа — это критерии, по которым мерялась пригодность всего подхода,
и любая правка проверяется по ним, а не только по зелёным тестам:

| Стенд | Число |
|---|---|
| `scripts/phase0/end_to_end.py 1527888` | RMS **0.0250 кГц**, запас ×225 при пороге 0.5 кГц |
| `scripts/phase1/sweep.py` | покрытие **11 из 23** наблюдений корпуса |

Стенды сети не требуют: корпус лежит в `scripts/phase0/cache/`. Они зовут
тот же `application/services/extraction.py`, что и сервис, — третьей копии
цепочки нет (правило 8).

## Что где

```
src/domain/{od,waterfall}/   алгоритмы: без фреймворков, только numpy/scipy/sgp4
src/application/             оркестрация; services/extraction.py — место сшивки
src/infrastructure/          httpx, PIL, SQLAlchemy, taskiq, JWT
src/presentation/api/v1/     один маршрут — один файл
scripts/phase0, phase1       стенды замера; phase2 — демонстрация
tests/{unit,regression,golden}
```
