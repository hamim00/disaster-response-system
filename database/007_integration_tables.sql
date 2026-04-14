-- ============================================================================
-- 007_integration_tables.sql
-- FloodShield BD — Integration: 999 Gateway, Field Portal & Feedback Loop
-- Run after 006_agent_messages.sql
-- ============================================================================

-- ============================================================================
-- TABLE: intake_log — Every incoming 999 call / SMS / social media message
-- ============================================================================
CREATE TABLE IF NOT EXISTS intake_log (
    id                    SERIAL PRIMARY KEY,
    source_type           VARCHAR(20) NOT NULL CHECK (source_type IN ('call_999', 'sms', 'social_media')),
    source_phone          VARCHAR(20),
    caller_name           VARCHAR(100),
    raw_message           TEXT NOT NULL,
    language              VARCHAR(10) DEFAULT 'bn',
    location_lat          DOUBLE PRECISION,
    location_lng          DOUBLE PRECISION,
    location_description  TEXT,
    auto_detected_urgency VARCHAR(10) CHECK (auto_detected_urgency IN ('critical', 'high', 'medium', 'low')),
    processing_status     VARCHAR(20) DEFAULT 'received'
                              CHECK (processing_status IN ('received', 'sent_to_agent2', 'processed', 'duplicate', 'false_alarm')),
    agent2_distress_id    INTEGER,
    received_at           TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    processed_at          TIMESTAMP WITH TIME ZONE,
    scenario_event_id     VARCHAR(50)
);

CREATE INDEX IF NOT EXISTS idx_intake_status    ON intake_log(processing_status);
CREATE INDEX IF NOT EXISTS idx_intake_received  ON intake_log(received_at DESC);

-- ============================================================================
-- TABLE: team_status — Real-time status & location of every field team
-- ============================================================================
CREATE TABLE IF NOT EXISTS team_status (
    team_id               VARCHAR(50) PRIMARY KEY,
    team_name             VARCHAR(100) NOT NULL,
    current_lat           DOUBLE PRECISION,
    current_lng           DOUBLE PRECISION,
    home_depot_id         INTEGER,
    status                VARCHAR(20) DEFAULT 'standby'
                              CHECK (status IN (
                                  'standby','dispatched','en_route','on_site',
                                  'returning','unreachable','off_duty'
                              )),
    current_mission_id    INTEGER,
    last_heartbeat        TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    heartbeat_interval_sec INTEGER DEFAULT 30,
    team_members          INTEGER DEFAULT 5,
    has_boat              BOOLEAN DEFAULT FALSE,
    has_medical_officer   BOOLEAN DEFAULT FALSE,
    pin_hash              VARCHAR(128) DEFAULT '1234',
    created_at            TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at            TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- TABLE: team_responses — Accept/Decline dispatch orders
-- ============================================================================
CREATE TABLE IF NOT EXISTS team_responses (
    id              SERIAL PRIMARY KEY,
    dispatch_id     INTEGER NOT NULL,
    team_id         VARCHAR(50) NOT NULL REFERENCES team_status(team_id),
    response        VARCHAR(20) NOT NULL CHECK (response IN ('accepted', 'declined', 'no_response')),
    decline_reason  TEXT,
    responded_at    TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    response_time_sec INTEGER
);
CREATE INDEX IF NOT EXISTS idx_team_resp_dispatch ON team_responses(dispatch_id);

-- ============================================================================
-- TABLE: resource_consumption — What was sent, used, returned per mission
-- ============================================================================
CREATE TABLE IF NOT EXISTS resource_consumption (
    id                 SERIAL PRIMARY KEY,
    dispatch_id        INTEGER NOT NULL,
    team_id            VARCHAR(50) NOT NULL REFERENCES team_status(team_id),
    resource_type      VARCHAR(50) NOT NULL,
    quantity_sent      INTEGER NOT NULL,
    quantity_consumed  INTEGER DEFAULT 0,
    quantity_returned  INTEGER DEFAULT 0,
    reported_by_team   BOOLEAN DEFAULT FALSE,
    consumed_at        TIMESTAMP WITH TIME ZONE,
    created_at         TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_consumption_dispatch ON resource_consumption(dispatch_id);

-- ============================================================================
-- TABLE: ground_reports — Field teams report actual conditions
-- ============================================================================
CREATE TABLE IF NOT EXISTS ground_reports (
    id                      SERIAL PRIMARY KEY,
    mission_id              INTEGER NOT NULL,
    team_id                 VARCHAR(50) NOT NULL REFERENCES team_status(team_id),
    actual_affected_count   INTEGER,
    estimated_affected_count INTEGER,
    additional_needs        TEXT,
    route_conditions        TEXT,
    area_accessibility      VARCHAR(20) CHECK (area_accessibility IN (
                                'accessible','partially_blocked','fully_blocked','boat_only')),
    water_level_observation VARCHAR(20) CHECK (water_level_observation IN ('rising','stable','receding')),
    photo_evidence_count    INTEGER DEFAULT 0,
    notes                   TEXT,
    reported_at             TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- TABLE: resupply_requests — Auto-generated when depot drops below threshold
-- ============================================================================
CREATE TABLE IF NOT EXISTS resupply_requests (
    id                  SERIAL PRIMARY KEY,
    depot_id            INTEGER NOT NULL,
    resource_type       VARCHAR(50) NOT NULL,
    current_quantity    INTEGER NOT NULL,
    threshold_quantity  INTEGER NOT NULL,
    requested_quantity  INTEGER NOT NULL,
    status              VARCHAR(20) DEFAULT 'pending'
                            CHECK (status IN ('pending','approved','in_transit','fulfilled')),
    requested_at        TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    fulfilled_at        TIMESTAMP WITH TIME ZONE
);

-- ============================================================================
-- SEED: Pre-populate field teams for demo
-- ============================================================================
INSERT INTO team_status (team_id, team_name, current_lat, current_lng, status, team_members, has_boat, has_medical_officer, pin_hash)
VALUES
    ('team_alpha',   'Team Alpha - Sylhet',     24.8949, 91.8687, 'standby', 6, TRUE,  TRUE,  '1234'),
    ('team_bravo',   'Team Bravo - Sunamganj',  25.0715, 91.3950, 'standby', 5, TRUE,  FALSE, '1234'),
    ('team_charlie', 'Team Charlie - Dhaka',    23.8103, 90.4125, 'standby', 5, FALSE, TRUE,  '1234'),
    ('team_delta',   'Team Delta - Sirajganj',  24.4534, 89.7007, 'standby', 4, TRUE,  FALSE, '1234'),
    ('team_echo',    'Team Echo - Companiganj', 25.0456, 91.5234, 'standby', 5, TRUE,  TRUE,  '1234')
ON CONFLICT (team_id) DO NOTHING;
