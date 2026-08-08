from app.config import get_settings
from app.web import create_app


settings = get_settings()
app = create_app(settings)


if __name__ == "__main__":
    app.run(host=settings.app_host, port=settings.app_port, debug=settings.app_debug)

