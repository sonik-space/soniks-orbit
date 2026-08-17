from pydantic import BaseModel


class RabbitSettings(BaseModel):
    USER: str = "guest"
    PASSWORD: str = "guest"
    HOST: str = "orbit-rabbitmq"
    PORT: str = "5672"

    @property
    def url(self) -> str:
        return f"amqp://{self.USER}:{self.PASSWORD}@{self.HOST}:{self.PORT}/"


class AioPikaBrokerSettings(BaseModel):
    QUEUE_NAME: str = "orbit_tasks"
    EXCHANGE_NAME: str = "orbit_tasks"
    MAX_PRIORITY: int = 3
