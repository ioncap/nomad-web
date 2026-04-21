"""
Centrale tool registry voor de N.O.M.A.D Agent.
Beheert registratie, configuratie, enable/disable en uitvoering van alle tools.
"""
import json
import logging
import os
import threading
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_CONFIG_PATH = os.path.join(_BASE_DIR, "config", "tools.json")


class ToolRegistry:
    def __init__(self, config_path: str = _DEFAULT_CONFIG_PATH):
        self._config_path = config_path
        self._tools: Dict[str, Dict[str, Any]] = {}
        self._config: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._load_config()

    # ── Registration ──────────────────────────────────────────────────────────

    def register(
        self,
        name: str,
        func: Callable,
        description: str,
        default_params: Optional[Dict] = None,
        help_text: str = "",
        example_prompt: str = "",
    ) -> None:
        with self._lock:
            self._tools[name] = {
                "func": func,
                "description": description,
                "help": help_text or description,
                "example": example_prompt,
                "default_params": default_params or {},
            }
            if name not in self._config:
                self._config[name] = {"enabled": True, "params": {}}

    # ── Retrieval ─────────────────────────────────────────────────────────────

    def get_tool(self, name: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._get_unlocked(name)

    def _get_unlocked(self, name: str) -> Optional[Dict[str, Any]]:
        if name not in self._tools:
            return None
        t = self._tools[name]
        cfg = self._config.get(name, {})
        merged_params = {**t["default_params"], **cfg.get("params", {})}
        return {
            "name": name,
            "description": t["description"],
            "help": t["help"],
            "example": t["example"],
            "enabled": cfg.get("enabled", True),
            "params": merged_params,
            "default_params": t["default_params"],
        }

    def list_tools(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [self._get_unlocked(n) for n in self._tools]

    # ── Config update ─────────────────────────────────────────────────────────

    def update_config(
        self,
        name: str,
        params: Optional[Dict] = None,
        enabled: Optional[bool] = None,
    ) -> bool:
        with self._lock:
            if name not in self._tools:
                return False
            if name not in self._config:
                self._config[name] = {"enabled": True, "params": {}}
            if params is not None:
                dp = self._tools[name]["default_params"]
                coerced: Dict[str, Any] = {}
                for k, v in params.items():
                    if k in dp and dp[k] is not None:
                        try:
                            coerced[k] = type(dp[k])(v)
                        except (ValueError, TypeError):
                            coerced[k] = v
                    else:
                        coerced[k] = v
                self._config[name]["params"].update(coerced)
            if enabled is not None:
                self._config[name]["enabled"] = bool(enabled)
            self._save_unlocked()
            return True

    # ── Execution ─────────────────────────────────────────────────────────────

    def execute(self, name: str, args: Optional[Dict] = None) -> str:
        args = args or {}
        with self._lock:
            tool = self._get_unlocked(name)
            if tool is None:
                return f"Unknown tool: {name}"
            if not tool["enabled"]:
                return (
                    f"Tool '{name}' is currently disabled. "
                    "Enable it in ⚙ Tool Settings."
                )
            # Merge order: default_params < config overrides < caller args
            merged = {**tool["params"], **args}
            func = self._tools[name]["func"]
        try:
            return func(merged)
        except Exception as exc:
            logger.error("Tool '%s' failed: %s", name, exc, exc_info=True)
            return f"Tool error ({name}): {exc}"

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load_config(self) -> None:
        os.makedirs(os.path.dirname(self._config_path), exist_ok=True)
        if not os.path.exists(self._config_path):
            return
        try:
            with open(self._config_path) as f:
                data = json.load(f)
            for name, cfg in data.items():
                self._config[name] = {
                    "enabled": cfg.get("enabled", True),
                    "params": cfg.get("params", {}),
                }
            logger.info("Tool registry: loaded config from %s", self._config_path)
        except Exception as exc:
            logger.warning("Tool registry: could not load config: %s", exc)

    def _save_unlocked(self) -> None:
        os.makedirs(os.path.dirname(self._config_path), exist_ok=True)
        out: Dict[str, Any] = {}
        for name, cfg in self._config.items():
            if name not in self._tools:
                continue
            dp = self._tools[name]["default_params"]
            # Only write entries that differ from defaults or are disabled.
            overrides = {
                k: v for k, v in cfg.get("params", {}).items()
                if k not in dp or dp[k] != v
            }
            if not cfg.get("enabled", True) or overrides:
                entry: Dict[str, Any] = {}
                if not cfg.get("enabled", True):
                    entry["enabled"] = False
                if overrides:
                    entry["params"] = overrides
                out[name] = entry
        with open(self._config_path, "w") as f:
            json.dump(out, f, indent=2)
        logger.debug("Tool registry: config saved (%d overrides)", len(out))
