from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Dict, Optional
from models.agent import Agent
from models.message import Message

# Represents the state of a simulation session.
# NOTE: concurrent sessions handled via utils/session_manager.py
@dataclass
class SessionState:
    """Holds the complete state of a simulation session."""
    
    session_id: str
    agents: List[Agent]
    messages: List[Message] = field(default_factory=list)
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    duration_minutes: int = 15
    # Canonical identifier for the human participant (privacy-safe; real name never leaves frontend)
    user_name: str = "participant"
    # Optional pre-session self-report used as a prior when selecting pool agents.
    participant_stance_hint: Optional[str] = None
    experimental_config: dict = field(default_factory=dict)
    simulation_config: dict = field(default_factory=dict)
    treatment_group: Optional[str] = None
    # Map of agent name -> ISO timestamp when the agent was blocked for this session
    # This allows keeping existing messages visible while suppressing new ones
    # created after the block time.
    blocked_agents: Dict[str, str] = field(default_factory=dict)
    # Total seconds the session has been paused (participant away); excluded
    # from the duration so every participant gets the full exposure time.
    paused_seconds: float = 0.0
 
    def add_message(self, message: Message) -> None:
        """Add a message to the session history."""
        self.messages.append(message)
    
    def get_recent_messages(self, n: int) -> List[Message]:
        """Get the last n messages from the history."""
        return self.messages[-n:] if len(self.messages) >= n else self.messages
    
    def elapsed_active_minutes(self) -> float:
        """Minutes of active (non-paused) session time."""
        elapsed = (datetime.now(timezone.utc) - self.start_time).total_seconds() - self.paused_seconds
        return elapsed / 60

    def is_expired(self) -> bool:
        """Check if the session has exceeded its duration (paused time excluded)."""
        return self.elapsed_active_minutes() >= self.duration_minutes

    def block_agent(self, agent_name: str, when_iso: str) -> None:
        """Mark an agent as blocked at the given ISO timestamp for this session."""
        self.blocked_agents[agent_name] = when_iso

    def unblock_agent(self, agent_name: str) -> None:
        """Unblock a previously blocked agent."""
        self.blocked_agents.pop(agent_name, None)
