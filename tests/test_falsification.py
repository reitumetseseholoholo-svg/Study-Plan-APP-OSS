"""M2.5 Falsification — distinguishing architectural principles from implementation conventions.

These tests construct valid CognitiveProcess subclasses that violate the
*implementation pattern* while preserving the *architectural principle*.

They prove:
  - The principle survives (e.g., "runtime requires termination predicate")
  - The implementation pattern is conventional (e.g., "bool(state.get('done'))")

Each test constructs a process that:
  1. Is a valid CognitiveProcess subclass (passes structural requirements)
  2. Runs through CognitiveRuntime.execute() without error
  3. Produces a valid ExecutionTrace that downstream consumers can process
  4. VIOLATES the familiar implementation pattern while PRESERVING the principle

If all tests pass, the corresponding principle is robust at its correct layer
and the implementation pattern is confirmed to be a local convention.
"""

from __future__ import annotations

from typing import Any


from studyplan.cci import (
    CognitiveProcess,
    CognitiveRuntime,
    ComputationResultInterpreter,
    ExecutionTrace,
    TraceInterpreter,
)


# =========================================================================
# Principle 1: Runtime requires a deterministic termination condition.
# Implementation pattern: bool(state.get("done"))
# =========================================================================


class CounterexampleProcessA(CognitiveProcess):
    """Uses step_count instead of 'done' key for termination.

    Principle under test:
        The runtime requires a deterministic termination condition.

    Implementation pattern violated:
        finished() checks ``bool(state.get("done"))``.

    If this runs successfully, the *principle* survives (runtime still
    terminates) while the *implementation* ('done' key) is conventional.
    """

    def __init__(self, concept_id: str) -> None:
        self._concept_id = concept_id

    @property
    def concept_id(self) -> str:
        return self._concept_id

    def initialize(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return {
            "inputs": dict(inputs),
            "step_count": 0,
            "result": None,
        }

    def step(self, state: dict[str, Any]) -> dict[str, Any]:
        result = sum(v for v in state["inputs"].values() if isinstance(v, (int, float)))
        return {
            "next_state": {
                **state,
                "step_count": state["step_count"] + 1,
                "result": result,
            },
            "transition": {"depth": state["step_count"] + 1},
        }

    def finished(self, state: dict[str, Any]) -> bool:
        return state["step_count"] >= 1

    def result(self, state: dict[str, Any]) -> Any:
        return state.get("result")


def test_falsification_A_finished_without_done_key():
    """Principle survives: runtime uses ``finished()``, not the 'done' key.

    The 'done' key is conventional. The principle (termination predicate)
    is kernel-level — the runtime requires a way to determine termination.
    """
    process = CounterexampleProcessA("test.falsify_A")
    runtime = CognitiveRuntime()
    trace = runtime.execute(process, {"x": 5.0, "y": 3.0})
    assert len(trace) == 3
    assert trace.events[1].type == "step"
    assert trace.events[2].type == "terminate"
    result = ComputationResultInterpreter("test.falsify_A").interpret(trace)
    assert result["result"] == 8.0
    # Principle confirmed: runtime does not require 'done' key.
    # Layer: Kernel (runtime calls finished(), the 'how' is conventional)


# =========================================================================
# Principle 1b: Termination condition must eventually return True.
# =========================================================================


class CounterexampleProcessB(CognitiveProcess):
    """Tests multi-step execution with a step-counter termination condition.

    Principle under test:
        The termination condition must eventually return True.

    Verifies the runtime correctly handles multi-step processes where
    finished() uses a counter rather than a boolean flag.
    """

    def __init__(self, concept_id: str, max_steps: int = 5) -> None:
        self._concept_id = concept_id
        self._max_steps = max_steps

    @property
    def concept_id(self) -> str:
        return self._concept_id

    def initialize(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return {
            "inputs": dict(inputs),
            "done": False,
            "result": None,
            "_step": 0,
        }

    def step(self, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "next_state": {
                **state,
                "_step": state["_step"] + 1,
            },
            "transition": {"counter": state["_step"] + 1},
        }

    def finished(self, state: dict[str, Any]) -> bool:
        return state["_step"] >= self._max_steps

    def result(self, state: dict[str, Any]) -> Any:
        return state["_step"]


def test_falsification_B_finished_never_true():
    """Principle survives: multi-step termination via counter is valid.

    The runtime does not care what drives finished() — only that it
    eventually returns True. The {'_step': N} pattern confirms that
    the termination PREDICATE is the principle; the specific key ('done')
    is conventional.
    """
    process = CounterexampleProcessB("test.falsify_B", max_steps=3)
    runtime = CognitiveRuntime()
    trace = runtime.execute(process, {"x": 1.0})
    assert len(trace) == 5  # init + 3 steps + terminate
    assert len([e for e in trace.events if e.type == "step"]) == 3
    # Principle confirmed: runtime correctly drives multi-step processes
    # Layer: Kernel


# =========================================================================
# Principle 2: Every executable cognition must be identifiable.
# Implementation pattern: concept_id property on CognitiveProcess.
# =========================================================================


class CounterexampleProcessC(CognitiveProcess):
    """Lacks a ``concept_id`` property.

    Principle under test:
        Every executable cognition must be identifiable after construction.

    Implementation pattern violated:
        ``@property concept_id`` on the process class.

    The runtime never reads concept_id. Identity is consumed only by
    downstream interpreters and the application layer. This confirms
    the principle lives at the Application layer, not the Kernel.
    """

    def initialize(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return {"inputs": dict(inputs), "done": False, "result": None}

    def step(self, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "next_state": {**state, "done": True, "result": 42},
            "transition": {"depth": 1},
        }

    def finished(self, state: dict[str, Any]) -> bool:
        return bool(state.get("done"))

    def result(self, state: dict[str, Any]) -> Any:
        return state.get("result")


def test_falsification_C_no_concept_id():
    """Principle partially confirmed: identity is Application-layer.

    The runtime executes without concept_id — it never reads it.
    But downstream interpreters must supply concept_id externally
    (ComputationResultInterpreter takes it as constructor arg).
    This confirms identity is required at the Application layer,
    not the Kernel layer.
    """
    process = CounterexampleProcessC()
    runtime = CognitiveRuntime()
    trace = runtime.execute(process, {"x": 1.0})
    assert len(trace) == 3
    result = ComputationResultInterpreter("no_concept_id").interpret(trace)
    assert result["result"] == 42
    # Principle confirmed: identity is required (interpreters need it)
    # but at the Application layer, not the Kernel.
    # Layer: Application


# =========================================================================
# Principle 3: Each step produces a new, observable state configuration.
# Implementation pattern: {**state, ...} immutable spread.
# =========================================================================


class CounterexampleProcessD(CognitiveProcess):
    """Mutates state in place instead of copying+spreading.

    Principle under test:
        Each step must produce a new, observable state configuration.

    Implementation pattern violated:
        ``{**state, "done": True, ...}`` immutable spread.

    The runtime hashes the state AFTER receiving it from step(). Whether
    it's a new dict or the same dict mutated, the runtime always observes
    the new configuration. The spread pattern is defensive copying, not
    an architectural requirement.
    """

    def __init__(self, concept_id: str) -> None:
        self._concept_id = concept_id

    @property
    def concept_id(self) -> str:
        return self._concept_id

    def initialize(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return {"inputs": dict(inputs), "done": False, "result": None}

    def step(self, state: dict[str, Any]) -> dict[str, Any]:
        state["done"] = True
        state["result"] = sum(v for v in state["inputs"].values() if isinstance(v, (int, float)))
        return {"next_state": state, "transition": {"depth": 1}}

    def finished(self, state: dict[str, Any]) -> bool:
        return bool(state.get("done"))

    def result(self, state: dict[str, Any]) -> Any:
        return state.get("result")


def test_falsification_D_in_place_mutation():
    """Principle survives: runtime observes new state regardless of copy strategy.

    The hash chain is preserved because the runtime hashes AFTER receiving
    the (potentially mutated) state from step(). The immutable spread is
    a defensive copy convention, not an architectural invariant.
    """
    process = CounterexampleProcessD("test.falsify_D")
    runtime = CognitiveRuntime()
    trace = runtime.execute(process, {"a": 1.0, "b": 2.0})
    assert len(trace) == 3
    result = ComputationResultInterpreter("test.falsify_D").interpret(trace)
    assert result["result"] == 3.0
    # Hash chain preserved even with in-place mutation
    assert trace.events[1].state_hash_after == trace.events[2].state_hash_before
    # Principle confirmed: runtime observes new state via next_state
    # Layer: Kernel


# =========================================================================
# Principle 4: Step results separate state evolution from semantic metadata.
# Implementation pattern: {next_state, transition} two-key return.
# =========================================================================


class CounterexampleProcessE(CognitiveProcess):
    """Returns extra keys alongside next_state/transition from step().

    Principle under test:
        Step results separate state evolution from semantic metadata.

    Implementation pattern violated:
        Exactly ``{next_state, transition}`` two-key return.

    The runtime reads only step_result["next_state"]. Extra keys are
    silently ignored. The separation of state (next_state) from metadata
    (transition, debug_info, etc.) is the principle; the "exactly two keys"
    constraint was too strict.
    """

    def __init__(self, concept_id: str) -> None:
        self._concept_id = concept_id

    @property
    def concept_id(self) -> str:
        return self._concept_id

    def initialize(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return {"inputs": dict(inputs), "done": False, "result": None}

    def step(self, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "next_state": {**state, "done": True, "result": 99},
            "transition": {"depth": 1},
            "extra_key": "runtime_should_ignore_me",
            "debug_info": {"memory": "42GB"},
        }

    def finished(self, state: dict[str, Any]) -> bool:
        return bool(state.get("done"))

    def result(self, state: dict[str, Any]) -> Any:
        return state.get("result")


def test_falsification_E_extra_step_keys():
    """Principle partially confirmed: next_state is Kernel; transition is Algebra.

    next_state is required (Kernel) — the runtime reads it unconditionally.
    transition is conventional (Algebra) — it is optional and opaque to the
    runtime. Extra keys are silently ignored. The separation of state from
    metadata is the principle; the specific key count is conventional.
    """
    process = CounterexampleProcessE("test.falsify_E")
    runtime = CognitiveRuntime()
    trace = runtime.execute(process, {"x": 1.0})
    assert len(trace) == 3
    result = ComputationResultInterpreter("test.falsify_E").interpret(trace)
    assert result["result"] == 99
    # Principle confirmed: next_state carries state; everything else is metadata
    # Layer: Kernel (next_state) / Algebra (transition, extra keys)


# =========================================================================
# Principle 5: The trace is the sole data source for downstream interpretation.
# Implementation pattern: for event in trace.events:
# =========================================================================


class StreamingInterpreter(TraceInterpreter):
    """Reads events via iterator protocol instead of for-loop.

    Principle under test:
        The trace is the sole data source for downstream interpretation (I6).

    Implementation pattern violated:
        ``for event in trace.events:`` conventional loop.

    The key architectural invariant is that interpreters read from the trace
    and only from the trace. *How* they iterate the events (for-loop, generator,
    list comprehension, index access) is implementation style.
    """

    def interpret(self, trace: ExecutionTrace, **kwargs: Any) -> dict[str, Any]:
        it = iter(trace.events)
        init_event = next(it)
        remaining = list(it)
        return {
            "init_type": init_event.type,
            "step_count": len(remaining) - 1,
            "last_type": remaining[-1].type if remaining else None,
        }


def test_falsification_F_streaming_interpreter():
    """Principle survives: iteration strategy is conventional; trace-as-source is invariant.

    The for-loop pattern is code style. The architectural invariant (I6) is
    that interpreters consume only the trace and never call back into the
    process or runtime. The iterator protocol produces identical results.
    """
    process = CounterexampleProcessA("test.falsify_F")
    runtime = CognitiveRuntime()
    trace = runtime.execute(process, {"x": 1.0})

    interp = StreamingInterpreter()
    result = interp.interpret(trace)
    assert result["init_type"] == "initialize"
    assert result["last_type"] == "terminate"
    # Principle confirmed: trace is sole data source; iteration is style
    # Layer: Kernel (I6)
