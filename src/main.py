from app import create_app
from core.configs import settings

app = create_app(settings)
