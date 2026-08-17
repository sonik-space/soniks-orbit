from pydantic import BaseModel


class LoggingSettings(BaseModel):
    APP_NAME: str = "orbit"
    TASKIQ_NAME: str = "orbit.taskiq"

    APP_LEVEL: str = "INFO"

    DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"
    BASE_FORMAT: str = (
        "[%(asctime)s.%(msecs)03d] - %(name)s - "
        "%(filename)-20s:%(lineno)-4d %(levelname)s %(message)s"
    )
