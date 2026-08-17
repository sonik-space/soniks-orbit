from pydantic import BaseModel


class NetworkApiSettings(BaseModel):
    """Боевой Django, а не реплика dev2.

    Опубликованное на реплике TLE не дошло бы до планирования наблюдений
    реальной сети, поэтому раздел на dev2 — только UI, а данные боевые
    (decisions/009).
    """

    BASE_URL: str = "https://sonik.space"
    TIMEOUT_IN_SECONDS: float = 60.0
