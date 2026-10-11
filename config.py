"""Configuration: environment variables, optionally from a .env file next to app.py (see .env.example).

Imported first by app.py, before any module reads its settings, so a value in .env behaves exactly like one set in the
environment; a variable already set in the environment wins over the file.
"""
import logging, os

HERE = os.path.dirname(os.path.abspath(__file__))


def load_env(path=None):
    """KEY=VALUE lines (blank lines and # comments ignored; optional quotes around the value). Never overrides a variable
    that is already set."""
    path = path or os.path.join(HERE, ".env")
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line: continue
                k, v = line.split("=", 1); k, v = k.strip(), v.strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"": v = v[1:-1]
                os.environ.setdefault(k, v)
    except FileNotFoundError:
        pass


def flag(name, default="0"):
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def setup_logging():
    level = os.environ.get("ALETHEIA_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=getattr(logging, level, logging.INFO), format="%(asctime)s %(levelname)s %(name)s: %(message)s")


load_env()
