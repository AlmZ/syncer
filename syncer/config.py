"""Configuration management with secure file storage."""

import json
import os
import stat
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from syncer.constants import CONFIG_FILE_MODE, CONFIG_DIR_MODE, get_logger

logger = get_logger("config")

CONFIG_DIR = Path.home() / ".config" / "yandex-tidal-sync"
CONFIG_FILE = CONFIG_DIR / "config.json"
TIDAL_SESSION_FILE = CONFIG_DIR / "tidal_session.json"


def _secure_mkdir(path: Path) -> None:
    """Create directory with secure permissions."""
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, CONFIG_DIR_MODE)
    except OSError as e:
        logger.warning(f"Не удалось установить права на директорию {path}: {e}")


def _secure_write(path: Path, data: dict) -> None:
    """Write JSON file with secure permissions."""
    _secure_mkdir(path.parent)

    with open(path, "w") as f:
        json.dump(data, f, indent=2)

    try:
        os.chmod(path, CONFIG_FILE_MODE)
    except OSError as e:
        logger.warning(f"Не удалось установить права на файл {path}: {e}")


def _check_permissions(path: Path) -> None:
    """Warn if file has insecure permissions."""
    if not path.exists():
        return

    try:
        mode = stat.S_IMODE(os.stat(path).st_mode)
        if mode & (stat.S_IRWXG | stat.S_IRWXO):  # Group or other has access
            logger.warning(
                f"Файл {path} имеет небезопасные права доступа ({oct(mode)}). "
                f"Рекомендуется: chmod 600 {path}"
            )
    except OSError:
        pass


@dataclass
class Config:
    yandex_token: Optional[str] = None

    def save(self) -> None:
        """Save config with secure file permissions."""
        _secure_write(CONFIG_FILE, asdict(self))
        logger.debug(f"Конфигурация сохранена в {CONFIG_FILE}")

    @classmethod
    def load(cls) -> "Config":
        """Load config from file."""
        if not CONFIG_FILE.exists():
            return cls()

        _check_permissions(CONFIG_FILE)

        try:
            with open(CONFIG_FILE) as f:
                data = json.load(f)
            logger.debug(f"Конфигурация загружена из {CONFIG_FILE}")
            return cls(**data)
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"Ошибка чтения конфигурации: {e}")
            return cls()


def save_tidal_session(session) -> None:
    """Save Tidal session credentials with secure permissions."""
    session_data = {
        "token_type": session.token_type,
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "expiry_time": session.expiry_time.isoformat() if session.expiry_time else None,
    }
    _secure_write(TIDAL_SESSION_FILE, session_data)
    logger.debug("Сессия Tidal сохранена")


def load_tidal_session(session) -> bool:
    """Load Tidal session credentials. Returns True if successful."""
    if not TIDAL_SESSION_FILE.exists():
        return False

    _check_permissions(TIDAL_SESSION_FILE)

    try:
        with open(TIDAL_SESSION_FILE) as f:
            data = json.load(f)

        session.load_oauth_session(
            token_type=data["token_type"],
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
        )

        if session.check_login():
            logger.debug("Сессия Tidal загружена успешно")
            return True

        logger.debug("Сессия Tidal истекла")
        return False

    except (json.JSONDecodeError, KeyError) as e:
        logger.warning(f"Ошибка загрузки сессии Tidal: {e}")
        return False
    except Exception as e:
        logger.error(f"Неожиданная ошибка при загрузке сессии: {e}")
        return False
