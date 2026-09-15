"""Configuration: API key loading and project-wide defaults.

Order of resolution for API keys (FRED_API_KEY, BLS_API_KEY, BEA_API_KEY):
  0. config.set_api_key(<name>, value)   (explicit — notebooks / scripts)
  1. st.secrets[<name>]  (Streamlit runtime)
  2. os.environ[<name>]
  3. .env file in the project root

Keeping this in one place means core/ and sections/ never need to know
which environment they're running in.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Optional

# ---- Project-wide defaults ----------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _resolve_cache_dir() -> Path:
    """Pick a writable cache directory.

    Streamlit Cloud's project tree is read-only in some deployments, so we try
    the in-repo .cache/ first and fall back to /tmp. Either way, the cache is
    ephemeral on Streamlit Cloud (cleared on app restart) — that's fine.
    """
    primary = PROJECT_ROOT / ".cache"
    try:
        primary.mkdir(exist_ok=True)
        # Verify we can actually write
        test_file = primary / ".write_test"
        test_file.touch()
        test_file.unlink()
        return primary
    except (OSError, PermissionError):
        fallback = Path("/tmp/fred_macro_cache")
        fallback.mkdir(exist_ok=True)
        return fallback


CACHE_DIR = _resolve_cache_dir()

DEFAULT_START_DATE = "2022-01-01"
DEFAULT_DIFFUSION_START_DATE = "2015-01-01"   # diffusion charts need more history
DEFAULT_MA_WINDOW = 3                          # months
DEFAULT_HEIGHT = 500                           # plot height in px


# ---- Key loading --------------------------------------------------------------

# Explicit overrides (set_api_key). Checked before every other source so a
# notebook never has to touch Streamlit secrets, the environment or .env.
_OVERRIDES: dict[str, str] = {}

# Callbacks notified when a key changes, so clients holding a singleton built
# with the old key can drop it (see core/fred_client).
_KEY_LISTENERS: list[Callable[[str], None]] = []


def set_api_key(name: str, value: Optional[str]) -> None:
    """Explicitly set (or clear, with None) an API key for this process.

    Takes precedence over Streamlit secrets, the environment and .env.
    Any client singleton built with the previous key is invalidated.
    """
    if value:
        _OVERRIDES[name] = value
    else:
        _OVERRIDES.pop(name, None)
    for cb in list(_KEY_LISTENERS):
        cb(name)


def register_key_listener(callback: Callable[[str], None]) -> None:
    """Register a callable invoked with the key name whenever set_api_key runs."""
    if callback not in _KEY_LISTENERS:
        _KEY_LISTENERS.append(callback)


def _try_override(name: str) -> Optional[str]:
    return _OVERRIDES.get(name)


def _try_streamlit_secrets(name: str) -> Optional[str]:
    """Read `name` from st.secrets if Streamlit is importable and configured.

    Importing streamlit at module-load time would couple core/ to Streamlit, so
    we import lazily and swallow all errors.
    """
    try:
        import streamlit as st  # noqa: WPS433 (intentional lazy import)
        # st.secrets raises if not configured; treat any failure as "no key"
        return st.secrets[name]  # type: ignore[index]
    except Exception:
        return None


def _try_env(name: str) -> Optional[str]:
    return os.environ.get(name)


def _try_dotenv(name: str) -> Optional[str]:
    try:
        from dotenv import load_dotenv  # noqa: WPS433
        load_dotenv(PROJECT_ROOT / ".env")
        return os.environ.get(name)
    except Exception:
        return None


def _get_key(name: str, signup_url: str) -> str:
    for source in (_try_override, _try_streamlit_secrets, _try_env, _try_dotenv):
        key = source(name)
        if key:
            return key

    raise RuntimeError(
        f"{name} not found. Set it in one of:\n"
        "  - .streamlit/secrets.toml  (for Streamlit)\n"
        f"  - environment variable {name}\n"
        "  - .env file in the project root\n"
        f"Get a free key at {signup_url}"
    )


def get_fred_key() -> str:
    """Return the FRED API key, trying every source in turn.

    Raises:
        RuntimeError: if no key is found in any source.
    """
    return _get_key("FRED_API_KEY", "https://fredaccount.stlouisfed.org/apikey")


def get_bls_key() -> str:
    """Return the BLS Public Data API registration key (same resolution order).

    Raises:
        RuntimeError: if no key is found in any source.
    """
    return _get_key("BLS_API_KEY", "https://data.bls.gov/registrationEngine/")


def get_bea_key() -> str:
    """Return the BEA API UserID key (same resolution order).

    Raises:
        RuntimeError: if no key is found in any source.
    """
    return _get_key("BEA_API_KEY", "https://apps.bea.gov/API/signup/")
