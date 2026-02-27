import json
import os
import threading
from datetime import datetime, timezone
from typing import Any

from .cognitive_state import CognitiveState, CognitiveStateValidator
from .logging_config import get_logger

logger = get_logger(__name__)


class PersistenceLayer:
    def __init__(self, base_path: str = "./data/state"):
        self.base_path = base_path
        os.makedirs(self.base_path, exist_ok=True)
        # simple in-memory journal queue for demonstration
        self._journal_lock = threading.RLock()
        self._journal: list[dict[str, Any]] = []

    def _write_journal(self, entry: dict[str, Any]) -> None:
        with self._journal_lock:
            self._journal.append(entry)
            logger.debug("journal entry added", extra={"entry": entry})

    def save_state_atomic(self, learner_id: str, state: CognitiveState) -> bool:
        learner_id = str(learner_id or "").strip()
        if not learner_id:
            logger.error("empty learner_id passed to save_state_atomic")
            return False
        journal_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "learner_id": learner_id,
            "operation": "save_state",
            "state_snapshot": state.to_json_snapshot(),
        }
        self._write_journal(journal_entry)

        valid, errors = CognitiveStateValidator.validate(state)
        if not valid:
            logger.error("state validation failed", extra={"errors": errors})
            state.mark_corrupted("validation_failed")
            return False
        temp_path = os.path.join(self.base_path, f"{learner_id}.json.tmp")
        final_path = os.path.join(self.base_path, f"{learner_id}.json")
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(state.to_json_snapshot(), f)
            os.replace(temp_path, final_path)
            state.last_persisted_at = datetime.now(timezone.utc).isoformat()
            state.last_persist_ok = True
            logger.info("state persisted", extra={"learner_id": learner_id})
            return True
        except (OSError, TypeError, ValueError) as e:
            logger.error("persistence failure", extra={"error": str(e)})
            state.last_persist_ok = False
            state.last_persist_error = str(e)
            return False

    def load_state(self, learner_id: str) -> CognitiveState:
        learner_id = str(learner_id or "").strip()
        path = os.path.join(self.base_path, f"{learner_id}.json")
        if not os.path.isfile(path):
            return CognitiveState()
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            state = CognitiveState.from_snapshot(payload)
            valid, errors = CognitiveStateValidator.validate(state)
            if not valid:
                logger.error("loaded state invalid", extra={"errors": errors})
                state.mark_corrupted("loaded_invalid")
            return state
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as e:
            logger.error("failed loading state", extra={"error": str(e)})
            # return empty but mark corrupted
            st = CognitiveState()
            st.mark_corrupted("load_error")
            return st

    def get_journal_tail(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._journal_lock:
            return list(self._journal[-limit:])

    def count_unresolved_journals(self) -> int:
        with self._journal_lock:
            # in real impl we'd remove on commit; simplified here
            return len(self._journal)
