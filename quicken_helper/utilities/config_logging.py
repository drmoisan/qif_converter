# quicken_helper/utilities/config_logging.py
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "%(levelname)s %(name)s: %(message)s"},
        "verbose": {
            "format": "%(asctime)s %(levelname)s %(name)s "
            "[%(process)d:%(threadName)s] %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "level": "INFO",
            "formatter": "simple",
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "level": "DEBUG",
            "formatter": "verbose",
            "filename": "logs/app.log",
            "maxBytes": 5_000_000,
            "backupCount": 5,
            "encoding": "utf-8",
        },
    },
    "loggers": {
        # root logger
        "": {
            "level": "DEBUG",
            "handlers": ["console", "file"],
        },
        # quiet a noisy third-party lib if you want
        "urllib3": {"level": "WARNING", "propagate": True},
    },
}
