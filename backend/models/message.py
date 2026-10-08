from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid
from typing import Optional, List, Set


# Represents a single message or post. 
@dataclass
class Message:
    """Represents a single message in the chatroom."""
    
    sender: str  # "participant" or agent name (e.g., "Alice")
    content: str 
    timestamp: datetime
    message_id: str
    # Optional reply metadata (for quoted replies)
    reply_to: Optional[str] = None  # message_id being replied to
    quoted_text: Optional[str] = None  # text excerpt of the message being replied to
    # Optional mentions (tags) included in the message, e.g., ["Alice", "Bob"]
    mentions: Optional[List[str]] = None
    # Track which participants have liked this message (store user identifiers)
    liked_by: Set[str] = field(default_factory=set)
    # Whether this message has been reported by the (single) human participant
    reported: bool = False
    # Classifier labels for agent messages
    is_incivil: Optional[bool] = None
    is_like_minded: Optional[bool] = None
    inferred_participant_stance: Optional[str] = None
    classification_rationale: Optional[str] = None
    # Set when the safety screen judged this message unsafe. In-memory only
    # (persisted as messages.safety_verdict); keeps agents from liking it.
    safety_unsafe: bool = False
    # Arbitrary extra fields (e.g. scenario seed metadata) included in to_dict()
    metadata: dict = field(default_factory=dict)
    
    @classmethod
    def create(
        cls,
        sender: str,
        content: str,
        reply_to: Optional[str] = None,
        quoted_text: Optional[str] = None,
        mentions: Optional[List[str]] = None,
        is_incivil: Optional[bool] = None,
        is_like_minded: Optional[bool] = None,
        inferred_participant_stance: Optional[str] = None,
        classification_rationale: Optional[str] = None,
    ) -> "Message":
        """Factory method to create a new message with auto-generated ID and timestamp.

        reply_to and quoted_text are optional metadata used for quoted replies.
        """
        return cls(
            sender=sender,
            content=content,
            timestamp=datetime.now(timezone.utc),
            message_id=str(uuid.uuid4()),
            reply_to=reply_to,
            quoted_text=quoted_text,
            mentions=mentions,
            is_incivil=is_incivil,
            is_like_minded=is_like_minded,
            inferred_participant_stance=inferred_participant_stance,
            classification_rationale=classification_rationale,
        )
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        d = {
            "sender": self.sender,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "message_id": self.message_id,
            "reply_to": self.reply_to,
            "quoted_text": self.quoted_text,
            "mentions": self.mentions,
            # Likes metadata
            "likes_count": len(self.liked_by),
            "liked_by": list(self.liked_by),
            # Reported flag (single human participant model)
            "reported": self.reported,
            # Classifier labels
            "is_incivil": self.is_incivil,
            "is_like_minded": self.is_like_minded,
            "inferred_participant_stance": self.inferred_participant_stance,
            "classification_rationale": self.classification_rationale,
        }
        if self.metadata:
            d.update(self.metadata)
        return d

    # Likes management
    @property
    def likes_count(self) -> int:
        """Return number of likes for this message."""
        return len(self.liked_by)
    
    def toggle_like(self, user_id: str) -> str:
        """Toggle like state for user_id. Returns 'liked' or 'unliked'."""
        if user_id in self.liked_by:
            self.liked_by.remove(user_id)
            return "unliked"
        else:
            self.liked_by.add(user_id)
            return "liked"

    def toggle_report(self) -> str:
        """Toggle the reported flag for this message. Returns 'reported' or 'unreported'."""
        if self.reported:
            self.reported = False
            return "unreported"
        else:
            self.reported = True
            return "reported"
