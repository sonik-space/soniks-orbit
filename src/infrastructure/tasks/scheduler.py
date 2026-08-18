"""Планировщик taskiq: расписание живёт метками на самих задачах.

В фазе 2 планировщик не брался — под него не было сценария (правило 12).
В фазе 6 сценарий появился: decisions/006 требует автомата, а не кнопки,
и сканер обязан ходить сам.

`LabelScheduleSource` выбран потому, что расписание при нём стоит рядом
с задачей (`schedule=[{"cron": ...}]` в `scan.py`), а не в отдельной таблице,
которую надо держать в согласии с кодом.
"""

from taskiq import TaskiqScheduler
from taskiq.schedule_sources import LabelScheduleSource

from infrastructure.tasks.broker import broker

# Импорт ради регистрации: без него у планировщика нет ни одной задачи
# с меткой расписания.
from infrastructure.tasks import scan  # noqa: F401  isort:skip

scheduler = TaskiqScheduler(broker=broker, sources=[LabelScheduleSource(broker)])
