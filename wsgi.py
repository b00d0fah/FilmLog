import logging


logging.getLogger("waitress.queue").setLevel(logging.ERROR)
logging.getLogger("waitress").setLevel(logging.ERROR)

from app import app


if __name__ == "__main__":
    app.run()
