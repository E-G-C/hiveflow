"""State Management - Generic dictionary-based state container.

This module provides state management with immutable merging between agent steps.
"""

from typing import Any


class WorkflowState:
    """Generic dictionary-based state container for workflows.

    Supports immutable merging pattern: {**prev_state, **new_output}
    """

    def __init__(self, initial_state: dict[str, Any] | None = None) -> None:
        """Initialize workflow state.

        Args:
            initial_state: Optional initial state dictionary
        """
        self._state: dict[str, Any] = initial_state or {}
        self._history: list[dict[str, Any]] = []

    def merge(self, updates: dict[str, Any]) -> "WorkflowState":
        """Create new state by merging updates (immutable).

        Args:
            updates: Dictionary of state updates

        Returns:
            New WorkflowState instance with merged values
        """
        # Save current state to history
        self._history.append(self._state.copy())

        # Create new merged state
        new_state = {**self._state, **updates}
        new_workflow_state = WorkflowState(new_state)
        new_workflow_state._history = self._history.copy()

        return new_workflow_state

    def get(self, key: str, default: Any = None) -> Any:
        """Get value from state.

        Args:
            key: State key to retrieve
            default: Default value if key not found

        Returns:
            State value or default
        """
        return self._state.get(key, default)

    def to_dict(self) -> dict[str, Any]:
        """Export state as dictionary.

        Returns:
            Current state as dictionary
        """
        return self._state.copy()

    @property
    def history(self) -> list[dict[str, Any]]:
        """Get state history.

        Returns:
            List of previous states
        """
        return self._history.copy()
