from uuid import UUID

from application.interfaces.tasks import ExtractionQueue
from infrastructure.tasks.extract_track import extract_track_task


class TaskiqExtractionQueue(ExtractionQueue):
    async def enqueue(self, session_uuid: UUID, observation_id: int) -> None:
        await extract_track_task.kiq(str(session_uuid), observation_id)
