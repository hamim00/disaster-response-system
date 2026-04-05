"""
Base Channel Interface
======================
Abstract base for all distress intake channels.
Every channel must implement ingest() → List[RawDistressReport].

Author: Mahmudul Hasan
"""

import logging
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any

from models import RawDistressReport, DistressChannel

logger = logging.getLogger(__name__)


class BaseChannel(ABC):
    """
    Abstract base class for distress intake channels.
    
    Each channel:
    1. Connects to its data source (API, socket, simulation)
    2. Ingests raw messages
    3. Parses them into RawDistressReport objects
    4. Returns a list ready for cross-referencing
    """
    
    def __init__(self, channel_type: DistressChannel, enabled: bool = True):
        self.channel_type = channel_type
        self.enabled = enabled
        self.total_ingested = 0
        self.total_errors = 0
        logger.info(f"Channel initialized: {channel_type.value} (enabled={enabled})")
    
    @abstractmethod
    async def ingest(self) -> List[RawDistressReport]:
        """
        Fetch and parse distress reports from this channel.
        
        Returns:
            List of parsed RawDistressReport objects
        """
        raise NotImplementedError
    
    @abstractmethod
    async def health_check(self) -> bool:
        """Check if this channel's data source is reachable."""
        raise NotImplementedError
    
    def get_status(self) -> Dict[str, Any]:
        """Get channel status summary."""
        return {
            "channel": self.channel_type.value,
            "enabled": self.enabled,
            "total_ingested": self.total_ingested,
            "total_errors": self.total_errors,
        }
