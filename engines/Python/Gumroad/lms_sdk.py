"""
Personal LM Studio SDK wrapper.

This module provides convenience helpers for using LM Studio from Python with
localhost and .env configuration. It includes helpers for creating clients,
loading models, running agent-style calls, preparing images, and defining tools.
"""

import importlib
import inspect
import os
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional, TYPE_CHECKING, Union
from engines.Python.Gumroad.model_tools import tool as model_tool
import lmstudio as lms

DEFAULT_LOCAL_API_URL = "http://127.0.0.1:3841"
DEFAULT_ENV_PATHS = [
    Path.cwd() / ".env",
    Path(__file__).resolve().parent / ".env",
]



def load_env(env_path: Optional[Union[str, Path]] = None) -> None:
    """Load environment variables from a .env file if present."""
    if env_path is None:
        env_path = next((path for path in DEFAULT_ENV_PATHS if path.exists()), None)
    env_path = Path(env_path) if env_path is not None else None
    if env_path is None or not env_path.exists():
        return

    try:
        dotenv = importlib.import_module("dotenv")
        dotenv.load_dotenv(dotenv_path=env_path, override=False)
    except ImportError:
        _load_dotenv_simple(env_path)


def _load_dotenv_simple(env_path: Path) -> None:
    """Minimal fallback loader for .env files."""
    with env_path.open("r", encoding="utf-8") as stream:
        for raw_line in stream:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = map(str.strip, line.split("=", 1))
            if len(value) >= 2 and ((value[0] == value[-1] == '"') or (value[0] == value[-1] == "'")):
                value = value[1:-1]
            os.environ.setdefault(key, value)


def get_env(key: str, default: Optional[str] = None) -> Optional[str]:
    load_env()
    return os.getenv(key, default)


def configure_localhost(host: Optional[str] = None, api_key: Optional[str] = None) -> None:
    """Configure the SDK to use a local LM Studio instance and optional API key."""
    load_env()
    host = host or os.getenv("LMSTUDIO_API_URL") or DEFAULT_LOCAL_API_URL
    os.environ["LMSTUDIO_API_URL"] = host
    if api_key is not None:
        os.environ["LMSTUDIO_API_KEY"] = api_key


def _pick_kwargs(func: Callable[..., Any], kwargs: Dict[str, Any]) -> Dict[str, Any]:
    sig = inspect.signature(func)
    return {key: value for key, value in kwargs.items() if key in sig.parameters}


def create_client(host: Optional[str] = None, api_key: Optional[str] = None, **kwargs: Any) -> Any:
    """Create a local LM Studio synchronous client."""
    configure_localhost(host=host, api_key=api_key)
    client_kwargs = _pick_kwargs(lms.Client, {"host": host, "api_key": api_key, **kwargs})
    return lms.Client(**client_kwargs)


def create_async_client(host: Optional[str] = None, api_key: Optional[str] = None, **kwargs: Any) -> Any:
    """Create a local LM Studio asynchronous client."""
    configure_localhost(host=host, api_key=api_key)
    client_kwargs = _pick_kwargs(lms.AsyncClient, {"host": host, "api_key": api_key, **kwargs})
    return lms.AsyncClient(**client_kwargs)


def local_llm(model_name: str, client: Optional[Any] = None, host: Optional[str] = None, api_key: Optional[str] = None, **kwargs: Any) -> Any:
    """Load a local LM Studio model using the convenience API or a provided client."""
    if client is None:
        client = create_client(host=host, api_key=api_key)
    if hasattr(client, "llm") and hasattr(client.llm, "model"):
        return client.llm.model(model_name, **kwargs)
    return lms.llm(model_name, **kwargs)


def prepare_image(image_source: Any, client: Optional[Any] = None) -> Any:
    """Prepare an image for use with a vision-capable model."""
    if client is None:
        client = create_client()
    if hasattr(lms, "prepare_image"):
        return lms.prepare_image(image_source)
    if hasattr(client, "files") and hasattr(client.files, "prepare_image"):
        return client.files.prepare_image(image_source)
    raise RuntimeError("Could not locate prepare_image in the LM Studio SDK.")


def create_chat(system_prompt: Optional[str] = None) -> Any:
    """Create a new chat instance."""
    if system_prompt is None:
        return lms.Chat()
    return lms.Chat(system_prompt)


def respond(model: Any, prompt_or_chat: Any, **kwargs: Any) -> Any:
    """Send a prompt or chat to the model and return the response."""
    return model.respond(prompt_or_chat, **kwargs)


def act(model: Any, prompt_or_chat: Any, tools: Iterable[Any], **kwargs: Any) -> Any:
    """Run an agent-style act call with a model and tools."""
    return model.act(prompt_or_chat, tools, **kwargs)


def tool(name: Optional[str] = None, description: Optional[str] = None) -> Callable[[Callable[..., Any]], Any]:
    """Decorator to turn a Python function into a tool definition."""
    return model_tool(name=name, description=description)


def make_tool(fn: Callable[..., Any], name: Optional[str] = None, description: Optional[str] = None) -> Any:
    """Create a tool definition from a callable."""
    return tool(name=name, description=description)(fn)


def get_default_model_name() -> str:
    """Return a default model name from environment or a sensible local fallback."""
    return os.getenv("LMSTUDIO_DEFAULT_MODEL", "qwen2.5-7b-instruct")


def open_local_chat(model_name: Optional[str] = None, host: Optional[str] = None, api_key: Optional[str] = None) -> Any:
    """Create a chat model using localhost and .env settings."""
    model_name = model_name or get_default_model_name()
    return local_llm(model_name, host=host, api_key=api_key)

