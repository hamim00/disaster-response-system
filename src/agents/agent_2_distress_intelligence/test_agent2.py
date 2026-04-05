"""
Test Suite for Agent 2: Distress Intelligence
===============================================
Tests multi-channel ingestion, cross-referencing, and prioritization
using realistic Bangladesh flood scenarios.

Run: python test_agent2.py

Author: Mahmudul Hasan
"""

import asyncio
import json
import sys
import os
from datetime import datetime, timedelta
from typing import Dict, Any, List

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import (
    UrgencyLevel, DistressChannel, DistressType,
    VerificationStatus, FloodSeverity,
)
from channels.social_media import SocialMediaChannel
from channels.sms_ussd import SMSUSSDChannel
from channels.emergency_hotline import EmergencyHotlineChannel
from channels.satellite_population import SatellitePopulationChannel
from cross_reference import CrossReferenceEngine
from prioritizer import DistressPrioritizer


# =====================================================================
# SIMULATED DATA — Based on real 2024 Dhaka monsoon flooding patterns
# =====================================================================

SIMULATED_SOCIAL_MEDIA_POSTS = [
    {
        "id": "fb_001",
        "platform": "facebook",
        "text": "মিরপুর ১২ নম্বর সেক্টরে পানি উঠে গেছে! রাস্তায় হাঁটু পানি, গাড়ি চলতে পারছে না 😱",
        "author": "Ahmed_Mirpur",
        "created_at": "2024-09-15T14:30:00",
        "engagement": 156,
        "has_media": True,
        "location_text": "Mirpur Section 12",
    },
    {
        "id": "fb_002",
        "platform": "facebook",
        "text": "URGENT! 5 families stranded on rooftop in Pallabi, Mirpur! Water is chest deep and rising! Please send help! বাঁচাও! 🆘",
        "author": "FloodWatch_BD",
        "created_at": "2024-09-15T15:00:00",
        "engagement": 843,
        "has_media": True,
        "location_text": "Pallabi, Mirpur",
    },
    {
        "id": "tw_003",
        "platform": "twitter",
        "text": "Uttara sector 10 e pani dhuktese basement e. Help please. 3 families stuck. Water 2ft already.",
        "author": "uttara_resident",
        "created_at": "2024-09-15T14:45:00",
        "engagement": 42,
        "has_media": False,
    },
    {
        "id": "fb_004",
        "platform": "facebook",
        "text": "Dhanmondi lake overflowing slightly, road 27 has some water. Not too bad though, just inconvenient for walking.",
        "author": "DhanmondiLife",
        "created_at": "2024-09-15T14:20:00",
        "engagement": 23,
        "has_media": False,
    },
    {
        "id": "fb_005",
        "platform": "facebook",
        "text": "জাত্রাবাড়ী এলাকায় ভয়াবহ বন্যা! পানি ৬ ফুট! একটা বাড়ি ভেঙে পড়েছে! মানুষ আটকে আছে! 999 এ কল করেও পাচ্ছি না! উদ্ধার দরকার!",
        "author": "jatrabari_crisis",
        "created_at": "2024-09-15T15:30:00",
        "engagement": 2105,
        "has_media": True,
    },
    {
        "id": "fb_006",
        "platform": "facebook",
        "text": "Beautiful rainy day in Gulshan! Love the monsoon weather from my apartment balcony 🌧️☕",
        "author": "lifestyle_dhaka",
        "created_at": "2024-09-15T14:00:00",
        "engagement": 89,
        "has_media": True,
    },
]

SIMULATED_SMS_MESSAGES = [
    {
        "text": "FLOOD MIRPUR 4FT 6 ROOFTOP",
        "phone_hash": "hash_sms_001",
        "operator": "GP",
        "signal": "2G",
        "timestamp": "2024-09-15T15:10:00",
    },
    {
        "text": "USSD|JATRABARI|CRITICAL|TRAPPED|12_PEOPLE",
        "phone_hash": "hash_sms_002",
        "operator": "Robi",
        "signal": "2G",
        "timestamp": "2024-09-15T15:35:00",
    },
    {
        "text": "Demra te pani 5ft. 3 poribar atke ase 2nd floor e. Help dorkar urgently. Amra 15 jon.",
        "phone_hash": "hash_sms_003",
        "operator": "Banglalink",
        "signal": "2G",
        "timestamp": "2024-09-15T15:45:00",
    },
    {
        "text": "FLOOD UTTARA 2FT 3 RISING",
        "phone_hash": "hash_sms_004",
        "operator": "GP",
        "signal": "3G",
        "timestamp": "2024-09-15T14:50:00",
    },
    {
        "text": "FLOOD MOHAMMADPUR KNEE 8 FOOD",
        "phone_hash": "hash_sms_005",
        "operator": "Teletalk",
        "signal": "2G",
        "timestamp": "2024-09-15T16:00:00",
    },
]

SIMULATED_HOTLINE_CALLS = [
    {
        "call_id": "999-2024-001234",
        "timestamp": "2024-09-15T15:15:00",
        "zone": "mirpur",
        "caller_phone_hash": "hash_999_001",
        "operator_notes": "Caller reports 5 elderly people trapped on 2nd floor, Mirpur section 12 building 45. Water at 5 feet and rising. One person needs insulin urgently. Building partially damaged.",
        "urgency": "critical",
        "people_count": 5,
        "situation": "trapped",
        "water_level_ft": 5,
        "call_duration_seconds": 180,
    },
    {
        "call_id": "999-2024-001235",
        "timestamp": "2024-09-15T15:40:00",
        "zone": "jatrabari",
        "caller_phone_hash": "hash_999_002",
        "operator_notes": "Building collapse reported near Kadamtali bridge. Multiple families trapped. Caller heard screaming. Water is 6+ feet. Fire service dispatched but road blocked.",
        "urgency": "critical",
        "people_count": 20,
        "situation": "collapse",
        "water_level_ft": 6,
        "call_duration_seconds": 240,
    },
    {
        "call_id": "999-2024-001236",
        "timestamp": "2024-09-15T16:00:00",
        "zone": "demra",
        "caller_phone_hash": "hash_999_003",
        "operator_notes": "Garment workers in Demra industrial area, factory basement flooded. About 30 workers moved to upper floor. Need evacuation. Water level 4 feet.",
        "urgency": "high",
        "people_count": 30,
        "situation": "evacuate",
        "water_level_ft": 4,
        "call_duration_seconds": 150,
    },
]

SIMULATED_FLOOD_ALERTS = [
    {
        "zone_id": "mirpur",
        "flood_pct": 37.5,
        "flood_depth_m": 1.5,
        "risk_score": 0.78,
        "severity": "high",
        "timestamp": "2024-09-15T14:00:00",
    },
    {
        "zone_id": "jatrabari",
        "flood_pct": 52.0,
        "flood_depth_m": 2.1,
        "risk_score": 0.89,
        "severity": "critical",
        "timestamp": "2024-09-15T14:00:00",
    },
    {
        "zone_id": "demra",
        "flood_pct": 28.0,
        "flood_depth_m": 1.2,
        "risk_score": 0.65,
        "severity": "high",
        "timestamp": "2024-09-15T14:00:00",
    },
    {
        "zone_id": "uttara",
        "flood_pct": 8.0,
        "flood_depth_m": 0.4,
        "risk_score": 0.35,
        "severity": "moderate",
        "timestamp": "2024-09-15T14:00:00",
    },
    {
        "zone_id": "dhanmondi",
        "flood_pct": 2.0,
        "flood_depth_m": 0.1,
        "risk_score": 0.15,
        "severity": "low",
        "timestamp": "2024-09-15T14:00:00",
    },
]

# Agent 1 flood data for cross-referencing
AGENT1_FLOOD_DATA = {
    "mirpur": {"risk_score": 0.78, "severity": "high", "flood_pct": 37.5, "flood_depth_m": 1.5},
    "jatrabari": {"risk_score": 0.89, "severity": "critical", "flood_pct": 52.0, "flood_depth_m": 2.1},
    "demra": {"risk_score": 0.65, "severity": "high", "flood_pct": 28.0, "flood_depth_m": 1.2},
    "uttara": {"risk_score": 0.35, "severity": "moderate", "flood_pct": 8.0, "flood_depth_m": 0.4},
    "dhanmondi": {"risk_score": 0.15, "severity": "low", "flood_pct": 2.0, "flood_depth_m": 0.1},
    "mohammadpur": {"risk_score": 0.45, "severity": "moderate", "flood_pct": 12.0, "flood_depth_m": 0.5},
}


# =====================================================================
# TESTS
# =====================================================================

def print_header(title: str):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


def print_subheader(title: str):
    print(f"\n  ── {title} ──")


async def test_social_media_channel():
    """Test 1: Social media channel ingestion and NLP parsing."""
    print_header("TEST 1: Social Media Channel")
    
    channel = SocialMediaChannel()
    channel.load_simulated_posts(SIMULATED_SOCIAL_MEDIA_POSTS)
    reports = await channel.ingest()
    
    print(f"  Posts loaded:     {len(SIMULATED_SOCIAL_MEDIA_POSTS)}")
    print(f"  Reports parsed:   {len(reports)} (flood-related only)")
    
    for r in reports:
        zone = r.location.zone_name or "?"
        print(f"\n  📱 [{r.urgency.value.upper():8s}] {zone}")
        print(f"     Type: {r.distress_type.value}")
        print(f"     Rescue: {r.needs_rescue} | Water: {r.water_level_meters}m | People: {r.people_count}")
        print(f"     Lang: {r.language} | Confidence: {r.nlp_confidence:.2f}")
        print(f"     Content: {r.raw_content[:80]}...")
    
    # Assertions
    assert len(reports) >= 4, f"Expected >=4 flood reports, got {len(reports)}"
    
    # The Gulshan lifestyle post should be filtered out
    for r in reports:
        assert "Beautiful rainy" not in r.raw_content, "Non-flood post should be filtered"
    
    # Jatrabari post should be high urgency with rescue
    jatrabari = [r for r in reports if r.location.zone_name == "Jatrabari"]
    assert len(jatrabari) > 0, "Jatrabari post should be detected"
    assert jatrabari[0].needs_rescue, "Jatrabari post should need rescue"
    
    print(f"\n  ✅ Social media channel test PASSED")
    return reports


async def test_sms_channel():
    """Test 2: SMS/USSD channel parsing."""
    print_header("TEST 2: SMS/USSD Channel")
    
    channel = SMSUSSDChannel()
    channel.load_simulated_messages(SIMULATED_SMS_MESSAGES)
    reports = await channel.ingest()
    
    print(f"  Messages loaded:  {len(SIMULATED_SMS_MESSAGES)}")
    print(f"  Reports parsed:   {len(reports)}")
    
    for r in reports:
        zone = r.location.zone_name or "?"
        msg_type = r.channel_metadata.get("message_type", "?")
        signal = r.channel_metadata.get("signal_strength", "?")
        print(f"\n  💬 [{r.urgency.value.upper():8s}] {zone} (via {msg_type}, {signal})")
        print(f"     Type: {r.distress_type.value}")
        print(f"     Rescue: {r.needs_rescue} | Water: {r.water_level_meters}m | People: {r.people_count}")
        print(f"     Raw: {r.raw_content}")
    
    # Assertions
    assert len(reports) == 5, f"Expected 5 SMS reports, got {len(reports)}"
    
    # Structured SMS should have high confidence
    structured = [r for r in reports if r.channel_metadata.get("message_type") == "structured"]
    assert len(structured) >= 2, "Expected at least 2 structured SMS"
    for s in structured:
        assert s.nlp_confidence >= 0.85, "Structured SMS should have high confidence"
    
    # USSD should be parsed correctly
    ussd = [r for r in reports if r.channel_metadata.get("message_type") == "ussd"]
    assert len(ussd) == 1, "Expected 1 USSD message"
    assert ussd[0].location.zone_name == "Jatrabari"
    assert ussd[0].people_count == 12
    
    print(f"\n  ✅ SMS/USSD channel test PASSED")
    return reports


async def test_hotline_channel():
    """Test 3: Emergency hotline (999) channel."""
    print_header("TEST 3: Emergency Hotline (999) Channel")
    
    channel = EmergencyHotlineChannel()
    channel.load_simulated_calls(SIMULATED_HOTLINE_CALLS)
    reports = await channel.ingest()
    
    print(f"  Calls loaded:     {len(SIMULATED_HOTLINE_CALLS)}")
    print(f"  Reports parsed:   {len(reports)}")
    
    for r in reports:
        zone = r.location.zone_name or "?"
        call_id = r.channel_metadata.get("call_id", "?")
        print(f"\n  📞 [{r.urgency.value.upper():8s}] {zone} (call: {call_id})")
        print(f"     Type: {r.distress_type.value}")
        print(f"     Rescue: {r.needs_rescue} | Water: {r.water_level_meters}m | People: {r.people_count}")
        print(f"     Notes: {r.raw_content[:100]}...")
    
    assert len(reports) == 3
    
    # All 999 calls should have high confidence
    for r in reports:
        assert r.nlp_confidence >= 0.9, "999 calls are operator-verified → high confidence"
    
    # Building collapse should be critical
    collapse = [r for r in reports if r.distress_type == DistressType.STRUCTURAL_COLLAPSE]
    assert len(collapse) == 1
    assert collapse[0].urgency == UrgencyLevel.CRITICAL
    assert collapse[0].people_count == 20
    
    print(f"\n  ✅ Emergency hotline test PASSED")
    return reports


async def test_satellite_population_channel():
    """Test 4: Satellite + Population overlay channel."""
    print_header("TEST 4: Satellite + Population Channel")
    
    channel = SatellitePopulationChannel()
    channel.load_flood_alerts(SIMULATED_FLOOD_ALERTS)
    reports = await channel.ingest()
    
    print(f"  Flood alerts:     {len(SIMULATED_FLOOD_ALERTS)}")
    print(f"  Reports generated: {len(reports)} (zones with >=5% flood)")
    
    for r in reports:
        zone = r.location.zone_name or "?"
        pop_data = r.channel_metadata.get("population_estimate", {})
        print(f"\n  🛰️ [{r.urgency.value.upper():8s}] {zone}")
        print(f"     Flood: {r.channel_metadata.get('flood_pct', 0):.1f}% | Depth: {r.water_level_meters}m")
        print(f"     People in flood zone: {pop_data.get('people_in_flood_zone', 0):,}")
        print(f"     Estimated stranded: {pop_data.get('estimated_stranded', 0):,}")
        print(f"     Resources: boats={pop_data.get('resource_estimates', {}).get('rescue_boats', 0)}, "
              f"medical={pop_data.get('resource_estimates', {}).get('medical_teams', 0)}")
    
    # Dhanmondi (2% flood) should be filtered out
    assert len(reports) == 4, f"Expected 4 reports (5 alerts - 1 below 5%), got {len(reports)}"
    
    # Jatrabari (52% flood, 2.1m depth) should be critical
    jat = [r for r in reports if r.location.zone_name == "Jatrabari"]
    assert len(jat) == 1
    assert jat[0].urgency == UrgencyLevel.CRITICAL
    
    print(f"\n  ✅ Satellite + Population test PASSED")
    return reports


async def test_cross_referencing():
    """Test 5: Cross-reference distress reports with Agent 1 data."""
    print_header("TEST 5: Cross-Referencing with Agent 1")
    
    # Collect reports from all channels
    social_ch = SocialMediaChannel(simulated_posts=SIMULATED_SOCIAL_MEDIA_POSTS)
    sms_ch = SMSUSSDChannel(simulated_messages=SIMULATED_SMS_MESSAGES)
    hotline_ch = EmergencyHotlineChannel(simulated_calls=SIMULATED_HOTLINE_CALLS)
    
    social_reports = await social_ch.ingest()
    sms_reports = await sms_ch.ingest()
    hotline_reports = await hotline_ch.ingest()
    
    all_reports = social_reports + sms_reports + hotline_reports
    print(f"  Total reports: {len(all_reports)} (social={len(social_reports)}, sms={len(sms_reports)}, hotline={len(hotline_reports)})")
    
    # Cross-reference with Agent 1 flood data
    engine = CrossReferenceEngine(flood_data_override=AGENT1_FLOOD_DATA)
    cross_referenced = await engine.cross_reference(all_reports)
    
    print_subheader("Cross-Reference Results")
    
    verified = [x for x in cross_referenced if x.verification_status == VerificationStatus.VERIFIED]
    contradicted = [x for x in cross_referenced if x.verification_status == VerificationStatus.CONTRADICTED]
    unverified = [x for x in cross_referenced if x.verification_status == VerificationStatus.UNVERIFIED]
    
    print(f"  Verified:     {len(verified)}")
    print(f"  Contradicted: {len(contradicted)}")
    print(f"  Unverified:   {len(unverified)}")
    
    for xref in cross_referenced[:8]:
        r = xref.distress_report
        status_icon = {"verified": "✅", "contradicted": "❌", "unverified": "❓", "pending": "⏳"}
        icon = status_icon.get(xref.verification_status.value, "?")
        zone = r.location.zone_name or "?"
        print(f"\n  {icon} [{xref.final_urgency.value.upper():8s}] {zone} "
              f"(score={xref.final_priority_score:.2f}) via {r.channel.value}")
        print(f"     A1: risk={xref.agent1_risk_score}, flood_pct={xref.agent1_flood_pct}")
        print(f"     {xref.priority_reasoning[:100]}")
    
    # Mirpur reports should be VERIFIED (Agent 1 sees 37.5% flood)
    mirpur_verified = [x for x in verified 
                       if x.distress_report.location.zone_name == "Mirpur"]
    assert len(mirpur_verified) > 0, "Mirpur reports should be verified by Agent 1"
    
    # Verified reports should have boosted priority
    for v in verified:
        assert v.final_priority_score > 0.3, "Verified reports should have meaningful priority"
    
    print(f"\n  ✅ Cross-referencing test PASSED")
    return cross_referenced


async def test_full_pipeline():
    """Test 6: Full end-to-end pipeline with all channels."""
    print_header("TEST 6: Full Pipeline — Multi-Channel → Cross-Reference → Queue")
    
    # ── Ingest from all channels ──
    social_ch = SocialMediaChannel(simulated_posts=SIMULATED_SOCIAL_MEDIA_POSTS)
    sms_ch = SMSUSSDChannel(simulated_messages=SIMULATED_SMS_MESSAGES)
    hotline_ch = EmergencyHotlineChannel(simulated_calls=SIMULATED_HOTLINE_CALLS)
    sat_ch = SatellitePopulationChannel(flood_alerts=SIMULATED_FLOOD_ALERTS)
    
    all_reports = []
    for name, ch in [("Social", social_ch), ("SMS", sms_ch), ("Hotline", hotline_ch), ("Satellite", sat_ch)]:
        reports = await ch.ingest()
        all_reports.extend(reports)
        print(f"  {name:10s}: {len(reports)} reports")
    
    print(f"  {'TOTAL':10s}: {len(all_reports)} reports")
    
    # ── Cross-reference ──
    engine = CrossReferenceEngine(flood_data_override=AGENT1_FLOOD_DATA)
    cross_referenced = await engine.cross_reference(all_reports)
    
    # ── Prioritize ──
    prioritizer = DistressPrioritizer()
    queue = prioritizer.build_queue(cross_referenced)
    
    print_subheader(f"Final Distress Queue ({len(queue)} items)")
    
    for i, item in enumerate(queue):
        print(f"\n  #{i+1} [{item.priority_score:.2f}] {item.summary}")
        print(f"     Resources: {', '.join(item.recommended_resources)}")
    
    # ── Assertions ──
    assert len(queue) > 0, "Queue should not be empty"
    
    # Queue should be sorted by priority
    for i in range(len(queue) - 1):
        assert queue[i].priority_score >= queue[i+1].priority_score, \
            "Queue must be sorted by priority (descending)"
    
    # At least one critical item
    critical = [q for q in queue if q.urgency == UrgencyLevel.CRITICAL]
    assert len(critical) >= 1, "Should have at least 1 critical item"
    
    # At least one rescue situation
    rescues = [q for q in queue if q.needs_rescue]
    assert len(rescues) >= 1, "Should have at least 1 rescue situation"
    
    # Rescue boats should be recommended for stranded/water-rising
    for q in queue:
        if q.needs_rescue or (q.water_level_meters and q.water_level_meters >= 1.0):
            assert "rescue_boat" in q.recommended_resources, \
                f"Rescue boat should be recommended for {q.zone_name}"
    
    # Multiple channels should be represented
    channels_in_queue = set(q.channel.value for q in queue)
    assert len(channels_in_queue) >= 3, \
        f"Expected >=3 channels in queue, got {channels_in_queue}"
    
    print_subheader("Queue Statistics")
    print(f"  Total items:        {len(queue)}")
    print(f"  Critical:           {len(critical)}")
    print(f"  Rescue situations:  {len(rescues)}")
    print(f"  Flood-verified:     {sum(1 for q in queue if q.flood_verified)}")
    print(f"  Channels present:   {', '.join(sorted(channels_in_queue))}")
    print(f"  Avg priority score: {sum(q.priority_score for q in queue)/len(queue):.2f}")
    
    print(f"\n  ✅ Full pipeline test PASSED")


async def test_connectivity_degradation():
    """
    Test 7: Simulate connectivity degradation during flooding.
    Shows how the system gracefully falls back to 2G channels
    when internet goes down.
    """
    print_header("TEST 7: Connectivity Degradation Scenario")
    
    print("  Scenario: As flooding intensifies, mobile data fails.")
    print("  Phase 1: All channels active (early flooding)")
    print("  Phase 2: Social media stops (data networks down)")
    print("  Phase 3: Only SMS/USSD + 999 + Satellite remain")
    print()
    
    # Phase 1 — All channels
    print_subheader("Phase 1: All channels active")
    social_ch = SocialMediaChannel(simulated_posts=SIMULATED_SOCIAL_MEDIA_POSTS[:3])
    sms_ch = SMSUSSDChannel(simulated_messages=SIMULATED_SMS_MESSAGES[:2])
    hotline_ch = EmergencyHotlineChannel(simulated_calls=SIMULATED_HOTLINE_CALLS[:1])
    sat_ch = SatellitePopulationChannel(flood_alerts=SIMULATED_FLOOD_ALERTS[:2])
    
    phase1_reports = []
    for ch in [social_ch, sms_ch, hotline_ch, sat_ch]:
        phase1_reports.extend(await ch.ingest())
    
    channels_1 = set(r.channel.value for r in phase1_reports)
    print(f"  Reports: {len(phase1_reports)} from channels: {channels_1}")
    
    # Phase 2 — Social media goes down
    print_subheader("Phase 2: Social media DOWN (no data connectivity)")
    social_ch_down = SocialMediaChannel(simulated_posts=[])  # No posts available
    sms_ch_2 = SMSUSSDChannel(simulated_messages=SIMULATED_SMS_MESSAGES)
    hotline_ch_2 = EmergencyHotlineChannel(simulated_calls=SIMULATED_HOTLINE_CALLS[:2])
    sat_ch_2 = SatellitePopulationChannel(flood_alerts=SIMULATED_FLOOD_ALERTS[:3])
    
    phase2_reports = []
    for ch in [social_ch_down, sms_ch_2, hotline_ch_2, sat_ch_2]:
        phase2_reports.extend(await ch.ingest())
    
    channels_2 = set(r.channel.value for r in phase2_reports)
    print(f"  Reports: {len(phase2_reports)} from channels: {channels_2}")
    assert DistressChannel.SOCIAL_MEDIA.value not in channels_2, \
        "Social media should produce 0 reports when data is down"
    assert len(phase2_reports) > 0, "System should still work without social media"
    
    # Phase 3 — Only 2G channels + satellite
    print_subheader("Phase 3: Only 2G (SMS/USSD) + 999 + Satellite")
    sms_ch_3 = SMSUSSDChannel(simulated_messages=SIMULATED_SMS_MESSAGES)
    hotline_ch_3 = EmergencyHotlineChannel(simulated_calls=SIMULATED_HOTLINE_CALLS)
    sat_ch_3 = SatellitePopulationChannel(flood_alerts=SIMULATED_FLOOD_ALERTS)
    
    phase3_reports = []
    for ch in [sms_ch_3, hotline_ch_3, sat_ch_3]:
        phase3_reports.extend(await ch.ingest())
    
    channels_3 = set(r.channel.value for r in phase3_reports)
    print(f"  Reports: {len(phase3_reports)} from channels: {channels_3}")
    
    # Cross-reference and prioritize phase 3
    engine = CrossReferenceEngine(flood_data_override=AGENT1_FLOOD_DATA)
    xrefs = await engine.cross_reference(phase3_reports)
    prioritizer = DistressPrioritizer()
    queue = prioritizer.build_queue(xrefs)
    
    print(f"  Queue size: {len(queue)} | Critical: {sum(1 for q in queue if q.urgency == UrgencyLevel.CRITICAL)}")
    
    assert len(queue) > 0, "System must produce actionable output even without internet"
    
    # The system should still identify critical situations
    critical = [q for q in queue if q.urgency == UrgencyLevel.CRITICAL]
    assert len(critical) >= 1, "Critical situations must be detected via 2G/999/satellite"
    
    print(f"\n  ✅ Connectivity degradation test PASSED")
    print(f"     KEY RESULT: System remains fully operational when internet fails.")
    print(f"     SMS (2G), 999 hotline, and satellite channels provide coverage.")


# =====================================================================
# MAIN
# =====================================================================

async def main():
    print("\n" + "█" * 70)
    print("  AGENT 2: DISTRESS INTELLIGENCE — MULTI-CHANNEL TEST SUITE")
    print("  Autonomous Multi-Agent Flood Response System for Bangladesh")
    print("█" * 70)
    
    tests = [
        ("Social Media Channel", test_social_media_channel),
        ("SMS/USSD Channel", test_sms_channel),
        ("Emergency Hotline Channel", test_hotline_channel),
        ("Satellite + Population Channel", test_satellite_population_channel),
        ("Cross-Referencing with Agent 1", test_cross_referencing),
        ("Full Pipeline", test_full_pipeline),
        ("Connectivity Degradation", test_connectivity_degradation),
    ]
    
    passed = 0
    failed = 0
    
    for name, test_fn in tests:
        try:
            await test_fn()
            passed += 1
        except Exception as e:
            print(f"\n  ❌ {name} FAILED: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print(f"\n{'='*70}")
    print(f"  RESULTS: {passed}/{passed+failed} tests passed")
    if failed == 0:
        print(f"  🎉 ALL TESTS PASSED!")
    else:
        print(f"  ⚠️  {failed} test(s) failed")
    print(f"{'='*70}\n")
    
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
