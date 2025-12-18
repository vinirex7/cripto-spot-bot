from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional


@dataclass
class SlotScheduler:
    decision_every_minutes: int
    last_slot: Optional[str] = None

    def current_slot(self, now: Optional[datetime] = None) -> str:
        now = now or datetime.now(timezone.utc)
        minutes = (now.minute // self.decision_every_minutes) * self.decision_every_minutes
        slot_start = now.replace(minute=minutes, second=0, microsecond=0)
        return f"{slot_start.strftime('%Y-%m-%dT%H:%MZ')}/{self.decision_every_minutes}m"

    def should_run(self, now: Optional[datetime] = None) -> bool:
        slot = self.current_slot(now)
        if slot != self.last_slot:
            self.last_slot = slot
            return True
        return False

    def next_slot_eta(self, now: Optional[datetime] = None) -> timedelta:
        now = now or datetime.now(timezone.utc)
        minutes = (now.minute // self.decision_every_minutes) * self.decision_every_minutes
        slot_start = now.replace(minute=minutes, second=0, microsecond=0)
        return slot_start + timedelta(minutes=self.decision_every_minutes) - now
