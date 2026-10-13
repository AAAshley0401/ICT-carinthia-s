"""Task lifecycle and guarded state transitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TaskState(str, Enum):
    CREATED = "CREATED"
    DETECTING = "DETECTING"
    DETECT_SUCCESS = "DETECT_SUCCESS"
    DETECT_FAILED = "DETECT_FAILED"
    SORTING = "SORTING"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    SUGGESTION_READY = "SUGGESTION_READY"
    INVALID_RESULT = "INVALID_RESULT"


ALLOWED_TRANSITIONS: dict[TaskState, frozenset[TaskState]] = {
    TaskState.CREATED: frozenset({TaskState.DETECTING}),
    TaskState.DETECTING: frozenset(
        {TaskState.DETECT_SUCCESS, TaskState.DETECT_FAILED, TaskState.INVALID_RESULT}
    ),
    TaskState.DETECT_SUCCESS: frozenset({TaskState.SORTING}),
    TaskState.SORTING: frozenset(
        {TaskState.REVIEW_REQUIRED, TaskState.SUGGESTION_READY}
    ),
    TaskState.DETECT_FAILED: frozenset(),
    TaskState.REVIEW_REQUIRED: frozenset(),
    TaskState.SUGGESTION_READY: frozenset(),
    TaskState.INVALID_RESULT: frozenset(),
}


@dataclass
class InspectionTask:
    task_id: str
    state: TaskState = TaskState.CREATED
    history: list[TaskState] = field(default_factory=lambda: [TaskState.CREATED])

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, str) or not self.task_id.strip():
            raise ValueError("task_id must be a nonempty string")
        if self.state != TaskState.CREATED or self.history != [TaskState.CREATED]:
            raise ValueError("new tasks must start in CREATED")

    def transition_to(self, new_state: TaskState) -> None:
        if new_state not in ALLOWED_TRANSITIONS[self.state]:
            raise ValueError(f"illegal state transition: {self.state.value} -> {new_state.value}")
        self.state = new_state
        self.history.append(new_state)
