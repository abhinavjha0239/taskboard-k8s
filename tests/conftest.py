import os

# Must be set before the app is imported: settings are read once at import time.
os.environ.setdefault("DATABASE_URL", "sqlite:///./test-taskboard.db")
os.environ.setdefault("APP_VERSION", "test")
os.environ.setdefault("GIT_COMMIT", "0" * 40)
