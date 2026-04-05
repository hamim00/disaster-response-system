"""
Distress intake channels.
Each channel converts its raw input into RawDistressReport objects.
"""

from channels.base import BaseChannel
from channels.social_media import SocialMediaChannel
from channels.sms_ussd import SMSUSSDChannel
from channels.emergency_hotline import EmergencyHotlineChannel
from channels.satellite_population import SatellitePopulationChannel

__all__ = [
    "BaseChannel",
    "SocialMediaChannel",
    "SMSUSSDChannel",
    "EmergencyHotlineChannel",
    "SatellitePopulationChannel",
]
