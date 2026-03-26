import json
import os
import threading
from datetime import datetime, timezone
from typing import Any

from .cognitive_state import CognitiveState, CognitiveStateValidator
from .logging_config import get_logger
from .state_locking import bind_cognitive_state_lock, locked_cognitive_state, snapshot_cognitive_state

logger = get_logger(__name__)


class PersistenceLayer:
    def __init__(self, base_path: str = "./data/state"):
        self.base_path = base_path
        os.makedirs(self.base_path, exist_ok=True)
        # simple in-memory journal queue for demonstration
        self._journal_lock = threading.RLock()
        self._journal_max_entries = max(
            1,
            min(
                5000,
                int(os.environ.get("STUDYPLAN_PERSISTENCE_JOURNAL_MAX_ENTRIES", "256") or "256"),
            ),
        )
        self._journal: list[dict[str, Any]] = []
        self._learner_locks: dict[str, threading.RLock] = {}
        self._learner_locks_lock = threading.RLock()

    def _learner_write_lock(self, learner_id: str) -> threading.RLock:
        key = str(learner_id or "").strip() or "default"
        with self._learner_locks_lock:
            lock = self._learner_locks.get(key)
            if lock is None:
                lock = threading.RLock()
                self._learner_locks[key] = lock
            return lock

    def _write_journal(self, entry: dict[str, Any]) -> None:
        with self._journal_lock:
            self._journal.append(entry)
            overflow = len(self._journal) - int(self._journal_max_entries)
            if overflow > 0:
                del self._journal[:overflow]
            logger.debug("journal entry added", extra={"entry": entry})

    def save_state_atomic(self, learner_id: str, state: CognitiveState) -> bool:
        learner_id = str(learner_id or "").strip()
        if not learner_id:
            logger.error("empty learner_id passed to save_state_atomic")
            return False
        state_lock = bind_cognitive_state_lock(state)
        with locked_cognitive_state(state, state_lock):
            snapshot = snapshot_cognitive_state(state)
        frozen_state = CognitiveState.from_snapshot(snapshot)
        journal_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "learner_id": learner_id,
            "operation": "save_state",
            "state_snapshot": snapshot,
        }
        self._write_journal(journal_entry)

        valid, errors = CognitiveStateValidator.validate(frozen_state)
        if not valid:
            logger.error("state validation failed", extra={"errors": errors})
            with locked_cognitive_state(state, state_lock):
                state.mark_corrupted("validation_failed")
            return False
        temp_path = os.path.join(self.base_path, f"{learner_id}.json.tmp")
        final_path = os.path.join(self.base_path, f"{learner_id}.json")
        try:
            learner_lock = self._learner_write_lock(learner_id)
            with learner_lock:
                with open(temp_path, "w", encoding="utf-8") as f:
                    json.dump(snapshot, f)
                os.replace(temp_path, final_path)
            with locked_cognitive_state(state, state_lock):
                state.last_persisted_at = datetime.now(timezone.utc).isoformat()
                state.last_persist_ok = True
                state.last_persist_error = None
            logger.info("state persisted", extra={"learner_id": learner_id})
            return True
        except (OSError, TypeError, ValueError) as e:
            logger.error("persistence failure", extra={"error": str(e)})
            with locked_cognitive_state(state, state_lock):
                state.last_persist_ok = False
                state.last_persist_error = str(e)
            return False

    def load_state(self, learner_id: str) -> CognitiveState:
        learner_id = str(learner_id or "").strip()
        path = os.path.join(self.base_path, f"{learner_id}.json")
        if not os.path.isfile(path):
            state = CognitiveState()
            bind_cognitive_state_lock(state)
            return state
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            state = CognitiveState.from_snapshot(payload)
            bind_cognitive_state_lock(state)
            valid, errors = CognitiveStateValidator.validate(state)
            if not valid:
                logger.error("loaded state invalid", extra={"errors": errors})
                state.mark_corrupted("loaded_invalid")
            return state
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as e:
            logger.error("failed loading state", extra={"error": str(e)})
            # return empty but mark corrupted
            st = CognitiveState()
            bind_cognitive_state_lock(st)
            st.mark_corrupted("load_error")
            return st

    def get_journal_tail(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._journal_lock:
            return list(self._journal[-limit:])

    def count_unresolved_journals(self) -> int:
        with self._journal_lock:
            # in real impl we'd remove on commit; simplified here
            return len(self._journal)
