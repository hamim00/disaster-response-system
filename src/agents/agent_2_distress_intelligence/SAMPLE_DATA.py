# =====================================================================
# SAMPLE DATA FOR DEMO CONSOLE
# Copy-paste each section into the corresponding tab
# =====================================================================


# ─────────────────────────────────────────────────────────────────────
# TAB 1: 999 OPERATOR CONSOLE
# ─────────────────────────────────────────────────────────────────────
# Just fill in the form fields. Here are 3 scenarios to demo:
#
# SCENARIO A: Mirpur rescue
#   Zone: Mirpur | Urgency: Critical | Situation: Stranded/Trapped
#   People: 5 | Water: 5 ft
#   Notes: "Caller reports 5 elderly people trapped on 2nd floor,
#           Mirpur section 12 building 45. Water at 5 feet and rising.
#           One person needs insulin urgently."
#
# SCENARIO B: Jatrabari collapse  
#   Zone: Jatrabari | Urgency: Critical | Situation: Building Collapse
#   People: 20 | Water: 6 ft
#   Notes: "Building collapse near Kadamtali bridge. Multiple families
#           trapped. Caller heard screaming. Water 6+ feet."
#
# SCENARIO C: Demra factory
#   Zone: Demra | Urgency: High | Situation: Evacuation Needed
#   People: 30 | Water: 4 ft
#   Notes: "Garment workers in Demra industrial area. Factory basement
#           flooded. 30 workers moved to upper floor. Need evacuation."


# ─────────────────────────────────────────────────────────────────────
# TAB 2: SMS / USSD SENDER
# ─────────────────────────────────────────────────────────────────────
# Click the format buttons and paste these one at a time:
#
# STRUCTURED FORMAT:
#   FLOOD MIRPUR 4FT 6 ROOFTOP
#   FLOOD JATRABARI 6FT 12 TRAPPED
#   FLOOD UTTARA 2FT 3 RISING
#   FLOOD DEMRA 5FT 15 EVACUATE
#   FLOOD MOHAMMADPUR KNEE 8 FOOD
#
# USSD FORMAT (*999# menu):
#   USSD|MIRPUR|SEVERE|ROOFTOP|5_PEOPLE
#   USSD|JATRABARI|CRITICAL|TRAPPED|12_PEOPLE
#   USSD|DEMRA|SEVERE|EVACUATE|30_PEOPLE
#
# BANGLISH FREE-TEXT:
#   Demra te pani 5ft. 3 poribar atke ase 2nd floor e. Help dorkar urgently. Amra 15 jon.
#   Mirpur 12 number e pani 4ft. 6 jon rooftop e achi. Bachao!
#   Uttara sector 10 e pani dhuktese basement e. Help please. 3 families stuck.
#
# BENGALI FREE-TEXT:
#   মিরপুর ১২ নম্বরে পানি ৪ ফুট! ৬ জন আটকে আছি ছাদে! বাঁচাও!
#   জাত্রাবাড়ীতে ভয়াবহ বন্যা! ২০ জন আটকে! উদ্ধার দরকার!


# ─────────────────────────────────────────────────────────────────────
# TAB 3: SOCIAL MEDIA FEED  
# ─────────────────────────────────────────────────────────────────────
# Click "Load Sample Data (15 posts)" button — it loads automatically.
# Or paste this JSON:

SOCIAL_MEDIA_POSTS = [
    {"id":"fb_001","platform":"facebook","text":"মিরপুর ১২ নম্বর সেক্টরে পানি উঠে গেছে! রাস্তায় হাঁটু পানি, গাড়ি চলতে পারছে না 😱","author":"Ahmed_Mirpur","created_at":"2024-09-15T14:30:00","engagement":156,"has_media":True},
    {"id":"fb_002","platform":"facebook","text":"URGENT! 5 families stranded on rooftop in Pallabi, Mirpur! Water is chest deep and rising! Please send help! বাঁচাও! 🆘","author":"FloodWatch_BD","created_at":"2024-09-15T15:00:00","engagement":843,"has_media":True},
    {"id":"tw_003","platform":"twitter","text":"Uttara sector 10 e pani dhuktese basement e. Help please. 3 families stuck. Water 2ft already.","author":"uttara_resident","created_at":"2024-09-15T14:45:00","engagement":42},
    {"id":"fb_004","platform":"facebook","text":"Dhanmondi lake overflowing slightly, road 27 has some water. Not too bad though.","author":"DhanmondiLife","created_at":"2024-09-15T14:20:00","engagement":23},
    {"id":"fb_005","platform":"facebook","text":"জাত্রাবাড়ী এলাকায় ভয়াবহ বন্যা! পানি ৬ ফুট! একটা বাড়ি ভেঙে পড়েছে! মানুষ আটকে আছে! উদ্ধার দরকার!","author":"jatrabari_crisis","created_at":"2024-09-15T15:30:00","engagement":2105,"has_media":True},
    {"id":"fb_006","platform":"facebook","text":"Beautiful rainy day in Gulshan! Love the monsoon weather from my apartment balcony 🌧️☕","author":"lifestyle_dhaka","created_at":"2024-09-15T14:00:00","engagement":89,"has_media":True},
    {"id":"fb_007","platform":"facebook","text":"Demra industrial area te heavy flooding. Factory basement e pani dhuktese. 30 workers trapped upstairs.","author":"demra_news","created_at":"2024-09-15T15:45:00","engagement":312},
    {"id":"tw_008","platform":"twitter","text":"Mohammadpur Shyamoli road pani knee deep. Gari choltese na. Food supply lagbe badly.","author":"shyamoli_updates","created_at":"2024-09-15T16:00:00","engagement":67},
    {"id":"fb_009","platform":"facebook","text":"HELP! Badda Gulshan link road completely flooded! Rescue boat needed for elderly couple stuck in ground floor!","author":"badda_help","created_at":"2024-09-15T15:20:00","engagement":534,"has_media":True},
    {"id":"fb_010","platform":"facebook","text":"Medical emergency in Mirpur 11! Pregnant woman trapped, water 4ft around house. Ambulance can't reach!","author":"mirpur_sos","created_at":"2024-09-15T16:15:00","engagement":1203,"has_media":True},
    {"id":"fb_011","platform":"facebook","text":"Today cricket match cancelled due to rain. Sad day for Bangladesh fans! 🏏","author":"cricket_bd","created_at":"2024-09-15T14:10:00","engagement":340},
    {"id":"tw_012","platform":"twitter","text":"আমরা ১০ জন উত্তরায় আটকে আছি। পানি বাড়ছে। ছাদে আছি। কেউ সাহায্য করেন!","author":"uttara_help","created_at":"2024-09-15T16:10:00","engagement":445},
    {"id":"fb_013","platform":"facebook","text":"Demra Matuail e 3 tin-shed bari venge gese pani te. 2 baccha missing. URGENT search needed!","author":"matuail_info","created_at":"2024-09-15T16:30:00","engagement":1567,"has_media":True},
]
# NLP will automatically:
# - Filter out fb_006 (Gulshan lifestyle) and fb_011 (cricket) — not flood related
# - Detect zones: Mirpur, Uttara, Jatrabari, Demra, Mohammadpur, Badda
# - Extract water levels: "হাঁটু পানি" → 0.5m, "chest deep" → 1.3m, "৬ ফুট" → 1.83m
# - Identify rescue needs: "stranded", "trapped", "বাঁচাও", "atke"
# - Classify urgency: CRITICAL for rescue+deep water, HIGH for rescue, MEDIUM otherwise


# ─────────────────────────────────────────────────────────────────────
# TAB 4: SATELLITE ALERTS (from Agent 1)
# ─────────────────────────────────────────────────────────────────────
# Click "Load 2024 Monsoon Data" button — it loads automatically.
# Or use connect_agent1.py to feed your actual test results.
#
# NOTE: You don't manually create this data. It comes FROM Agent 1.
# This tab only exists for testing when Agent 1 isn't running.
# When both agents run together via Docker, Agent 1 publishes
# flood_alert to Redis and Agent 2 receives it automatically.
#
# What Channel 4 adds that Agent 1 doesn't have:
#   Agent 1: "Mirpur 37% flooded, depth 1.5m"
#   Channel 4: "618,750 people in flood zone, ~216,000 stranded,
#               need 4,331 boats, 1,082 medical teams"
#
# To connect your Sylhet/Sunamganj test results:
#   python connect_agent1.py --sylhet
#   python connect_agent1.py --sunamganj
#   python connect_agent1.py --all-scenarios

SATELLITE_ALERTS = [
    {"zone_id":"mirpur","flood_pct":37.5,"flood_depth_m":1.5,"risk_score":0.78,"severity":"high","timestamp":"2024-09-15T14:00:00"},
    {"zone_id":"jatrabari","flood_pct":52.0,"flood_depth_m":2.1,"risk_score":0.89,"severity":"critical","timestamp":"2024-09-15T14:00:00"},
    {"zone_id":"demra","flood_pct":28.0,"flood_depth_m":1.2,"risk_score":0.65,"severity":"high","timestamp":"2024-09-15T14:00:00"},
    {"zone_id":"uttara","flood_pct":8.0,"flood_depth_m":0.4,"risk_score":0.35,"severity":"moderate","timestamp":"2024-09-15T14:00:00"},
    {"zone_id":"dhanmondi","flood_pct":2.0,"flood_depth_m":0.1,"risk_score":0.15,"severity":"low","timestamp":"2024-09-15T14:00:00"},
]
