from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict
from enum import Enum
from datetime import datetime


# Enums
class DistanceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class LinePosition(str, Enum):
    HEAD = "HEAD"
    STERN = "STERN"
    BREAST = "BREAST"
    SPRING_FWD = "SPRING_FWD"
    SPRING_AFT = "SPRING_AFT"


# Nested Models (Bottom-Up)
class Hook(BaseModel):
    name: str
    tension: Optional[float] = None
    faulted: bool = False
    attachedLine: Optional[str] = None  # Could be LinePosition enum if always these values

    @property
    def is_active(self) -> bool:
        """Check if hook has an active line attached."""
        return self.tension is not None and self.attachedLine is not None

    @property
    def tension_status(self) -> str:
        """Determine tension status based on value."""
        if self.tension is None:
            return "INACTIVE"
        elif self.tension < 50:
            return "LOW"
        elif self.tension < 150:
            return "NORMAL"
        elif self.tension < 250:
            return "WARNING"
        else:
            return "CRITICAL"


class Bollard(BaseModel):
    name: str
    hooks: List[Hook]

    @property
    def total_tension(self) -> float:
        """Calculate total tension across all hooks on this bollard."""
        return sum(hook.tension for hook in self.hooks if hook.tension is not None)

    @property
    def active_hooks(self) -> List[Hook]:
        """Get all hooks with active lines."""
        return [hook for hook in self.hooks if hook.is_active]

    @property
    def hook_count(self) -> int:
        """Total number of hooks on this bollard."""
        return len(self.hooks)

    @property
    def active_hook_count(self) -> int:
        """Number of hooks with active lines."""
        return len(self.active_hooks)

    def get_tensions_by_line(self) -> Dict[str, List[float]]:
        """Get all tensions grouped by line type (HEAD, STERN, etc)."""
        tensions_by_line = {}
        for hook in self.hooks:
            if hook.attachedLine and hook.tension is not None:
                if hook.attachedLine not in tensions_by_line:
                    tensions_by_line[hook.attachedLine] = []
                tensions_by_line[hook.attachedLine].append(hook.tension)
        return tensions_by_line


class Ship(BaseModel):
    name: str
    vesselId: str


class Radar(BaseModel):
    name: str
    shipDistance: Optional[float] = None
    distanceChange: Optional[float] = None
    distanceStatus: DistanceStatus

    @property
    def is_active(self) -> bool:
        """Check if radar is actively tracking."""
        return self.distanceStatus == DistanceStatus.ACTIVE


class Berth(BaseModel):
    name: str
    bollardCount: int
    hookCount: int
    ship: Optional[Ship] = None
    radars: List[Radar] = []
    bollards: List[Bollard] = []

    @validator('bollards')
    def validate_bollard_count(cls, v, values):
        """Ensure bollard count matches actual bollards."""
        if len(v) != values.get('bollardCount', 0):
            print(f"Warning: bollardCount mismatch. Expected {values.get('bollardCount')}, got {len(v)}")
        return v

    @property
    def has_ship(self) -> bool:
        """Check if berth has a ship moored."""
        return self.ship is not None

    @property
    def total_berth_tension(self) -> float:
        """Calculate total tension across all bollards."""
        return sum(bollard.total_tension for bollard in self.bollards)

    @property
    def active_radars(self) -> List[Radar]:
        """Get all active radars."""
        return [radar for radar in self.radars if radar.is_active]

    def get_bollard_by_name(self, name: str) -> Optional[Bollard]:
        """Find bollard by name."""
        return next((b for b in self.bollards if b.name == name), None)

    def get_tensions_by_bollard(self) -> Dict[str, Dict[str, List[float]]]:
        """
        Get all tensions organized by bollard and line type.
        Returns: {
            "BOL491": {"HEAD": [1.0, 3.0], "STERN": [5.0]},
            "BOL890": {"HEAD": [2.0]}
        }
        """
        result = {}
        for bollard in self.bollards:
            tensions_by_line = bollard.get_tensions_by_line()
            if tensions_by_line:  # Only include bollards with active lines
                result[bollard.name] = tensions_by_line
        return result

    def get_all_tensions_by_line_type(self) -> Dict[str, float]:
        """
        Get total tension for each line type across all bollards.
        Returns: {"HEAD": 15.0, "STERN": 20.0}
        """
        line_totals = {}
        for bollard in self.bollards:
            for line_type, tensions in bollard.get_tensions_by_line().items():
                if line_type not in line_totals:
                    line_totals[line_type] = 0.0
                line_totals[line_type] += sum(tensions)
        return line_totals


class MooringTerminal(BaseModel):
    name: str
    berths: List[Berth]
    timestamp: Optional[datetime] = None

    @property
    def active_berths(self) -> List[Berth]:
        """Get berths with ships moored."""
        return [berth for berth in self.berths if berth.has_ship]

    def get_berth_by_name(self, name: str) -> Optional[Berth]:
        """Find berth by name."""
        return next((b for b in self.berths if b.name == name), None)

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }