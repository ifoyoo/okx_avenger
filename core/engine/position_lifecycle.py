from __future__ import annotations

import json
import os
import threading
import tempfile
from dataclasses import asdict
from json import JSONDecodeError
from pathlib import Path

from loguru import logger

from core.models import SignalAction
from core.strategy.lifecycle import LifecyclePlan, evaluate_lifecycle_stage


class PositionLifecycleManager:
    def __init__(
        self,
        okx_client,
        state_path: Path = Path("data/position_lifecycle_state.json"),
        interval_seconds: float = 15.0,
    ) -> None:
        self.okx = okx_client
        self.state_path = state_path
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state = self.load_state()
        self._interval_seconds = max(1.0, float(interval_seconds or 15.0))
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._enforce_lock = threading.Lock()
        self._lock = threading.RLock()

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._state = self.load_state()
            self._thread = threading.Thread(target=self._run_loop, name="position-lifecycle-manager", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(1.0, self._interval_seconds + 1.0))
        with self._lock:
            if thread is None or not thread.is_alive():
                self._thread = None

    def load_state(self) -> dict:
        if not self.state_path.exists():
            return {}
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (JSONDecodeError, OSError):
            logger.warning("position lifecycle state load failed path={} reset_to_empty=true", self.state_path)
            return {}

    def save_state(self) -> None:
        payload = json.dumps(self._state, ensure_ascii=False, indent=2)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.state_path.parent,
            prefix=f"{self.state_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as fh:
            fh.write(payload)
            temp_path = Path(fh.name)
        try:
            temp_path.replace(self.state_path)
        except Exception:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            raise

    def register_plan(self, *, inst_id: str, pos_side: str, size: float, plan: LifecyclePlan) -> None:
        with self._lock:
            key = self._state_key(inst_id=inst_id, pos_side=pos_side)
            self._state[key] = {
                "size": size,
                "plan": asdict(plan),
                "tp1_hit": False,
                "tp2_hit": False,
                "scale_in_done": False,
            }
            self.save_state()

    def enforce(self) -> None:
        with self._enforce_lock:
            positions = self.okx.get_positions(inst_type="SWAP").get("data") or []
            for entry in positions:
                with self._lock:
                    key = self._resolve_state_key(inst_id=entry.get("instId"), pos_side=entry.get("posSide"))
                    current = self._state.get(key)
                    if not current:
                        continue
                    record = dict(current)
                plan_data = record["plan"]
                plan = LifecyclePlan(
                    action=SignalAction(plan_data["action"]),
                    entry_price=plan_data["entry_price"],
                    stop_price=plan_data["stop_price"],
                    tp1_price=plan_data["tp1_price"],
                    tp2_price=plan_data["tp2_price"],
                    scale_in_trigger_price=plan_data["scale_in_trigger_price"],
                    scale_in_size_ratio=plan_data["scale_in_size_ratio"],
                )
                stage = evaluate_lifecycle_stage(
                    plan=plan,
                    mark_price=float(entry.get("markPx") or 0.0),
                    tp1_hit=bool(record["tp1_hit"]),
                    tp2_hit=bool(record["tp2_hit"]),
                    scale_in_done=bool(record["scale_in_done"]),
                )
                response = None
                if stage.tp1_hit and not record["tp1_hit"]:
                    position_size = self._position_size(entry=entry, fallback=float(record["size"]))
                    reduce_size = position_size * 0.4
                    response = self.okx.place_order(
                        inst_id=entry["instId"],
                        td_mode=entry.get("mgnMode") or "isolated",
                        side="sell" if plan.action == SignalAction.BUY else "buy",
                        ord_type="market",
                        sz=f"{reduce_size:.8f}".rstrip("0").rstrip("."),
                        pos_side=self._normalize_pos_side(entry.get("posSide")),
                        reduce_only=True,
                    )
                with self._lock:
                    latest = self._state.get(key)
                    if not latest:
                        continue
                    dirty = False
                    next_tp2_hit = bool(latest.get("tp2_hit")) or bool(stage.tp2_hit)
                    next_scale_in_done = bool(latest.get("scale_in_done")) or bool(stage.scale_in_done)
                    if next_tp2_hit != bool(latest.get("tp2_hit")):
                        latest["tp2_hit"] = next_tp2_hit
                        dirty = True
                    if next_scale_in_done != bool(latest.get("scale_in_done")):
                        latest["scale_in_done"] = next_scale_in_done
                        dirty = True
                    if response is not None and self._order_succeeded(response) and not latest.get("tp1_hit"):
                        latest["tp1_hit"] = True
                        dirty = True
                    if dirty:
                        self._state[key] = latest
                        self.save_state()

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.enforce()
            except Exception as exc:  # pragma: no cover
                logger.warning("position lifecycle enforce failed err={}", exc)
            self._stop_event.wait(self._interval_seconds)

    def _resolve_state_key(self, *, inst_id: object, pos_side: object) -> str:
        key = self._state_key(inst_id=inst_id, pos_side=pos_side)
        if key in self._state:
            return key
        normalized_side = self._normalize_state_side(pos_side)
        if normalized_side != "net":
            return key
        prefix = f"{str(inst_id or '').strip()}:" if inst_id is not None else ""
        matches = [item for item in self._state if prefix and item.startswith(prefix)]
        if len(matches) == 1:
            return matches[0]
        return key

    @staticmethod
    def _state_key(*, inst_id: object, pos_side: object) -> str:
        inst = str(inst_id or "").strip()
        return f"{inst}:{PositionLifecycleManager._normalize_state_side(pos_side)}"

    @staticmethod
    def _normalize_state_side(pos_side: object) -> str:
        text = str(pos_side or "").strip().lower()
        return "net" if text in {"", "net"} else text

    @staticmethod
    def _normalize_pos_side(pos_side: object) -> str:
        text = str(pos_side or "").strip().lower()
        return "" if text in {"", "net"} else text

    @staticmethod
    def _position_size(*, entry: dict, fallback: float) -> float:
        try:
            size = abs(float(entry.get("pos") or 0.0))
        except (TypeError, ValueError):
            size = 0.0
        return size if size > 0 else max(0.0, float(fallback or 0.0))

    @staticmethod
    def _order_succeeded(response: object) -> bool:
        if not isinstance(response, dict):
            return False
        if str(response.get("code") or "") != "0":
            return False
        data = response.get("data")
        if not isinstance(data, list) or not data:
            return True
        first = data[0] if isinstance(data[0], dict) else {}
        return str(first.get("sCode") or "0") == "0"
