from uuid import UUID

from application.interfaces.tasks import CalibrationQueue, IdentificationQueue
from infrastructure.tasks.calibrate import calibrate_task
from infrastructure.tasks.identify import identify_task


class TaskiqCalibrationQueue(CalibrationQueue):
    async def enqueue(self, session_uuid: UUID, observation_id: int) -> None:
        await calibrate_task.kiq(str(session_uuid), observation_id)


class TaskiqIdentificationQueue(IdentificationQueue):
    async def enqueue(self, session_uuid: UUID, observation_id: int) -> None:
        await identify_task.kiq(str(session_uuid), observation_id)
