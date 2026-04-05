-- ============================================================================
-- Database Schema for Distress Intelligence Data
-- Agent 2: Distress Intelligence (Multi-Channel)
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS postgis;

-- ============================================================================
-- TABLE: distress_reports
-- Stores all incoming distress reports from all channels
-- ============================================================================

CREATE TABLE IF NOT EXISTS distress_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Channel & timing
    channel VARCHAR(30) NOT NULL CHECK (channel IN 
        ('social_media', 'sms_ussd', 'emergency_hotline', 'satellite_population')),
    reported_at TIMESTAMP WITH TIME ZONE NOT NULL,
    ingested_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    
    -- Content
    raw_content TEXT NOT NULL,
    language VARCHAR(10),  -- bn, en, banglish
    
    -- Classification
    distress_type VARCHAR(30) NOT NULL CHECK (distress_type IN 
        ('stranded', 'medical_emergency', 'structural_collapse', 
         'water_rising', 'evacuation_needed', 'supplies_needed',
         'missing_person', 'general_flood_report', 'population_at_risk')),
    urgency VARCHAR(10) NOT NULL CHECK (urgency IN ('low', 'medium', 'high', 'critical')),
    
    -- Location
    location GEOGRAPHY(POINT, 4326),
    zone_id VARCHAR(50),
    zone_name VARCHAR(100),
    address_text TEXT,
    location_confidence FLOAT CHECK (location_confidence >= 0 AND location_confidence <= 1),
    
    -- Situation details
    people_count INTEGER,
    needs_rescue BOOLEAN DEFAULT FALSE,
    water_level_meters FLOAT,
    
    -- NLP/parsing confidence
    nlp_confidence FLOAT CHECK (nlp_confidence >= 0 AND nlp_confidence <= 1),
    
    -- Deduplication
    is_duplicate BOOLEAN DEFAULT FALSE,
    duplicate_of UUID REFERENCES distress_reports(id),
    
    -- Channel-specific metadata
    channel_metadata JSONB DEFAULT '{}',
    
    -- Audit
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_distress_channel ON distress_reports(channel);
CREATE INDEX idx_distress_zone ON distress_reports(zone_id);
CREATE INDEX idx_distress_urgency ON distress_reports(urgency);
CREATE INDEX idx_distress_reported_at ON distress_reports(reported_at DESC);
CREATE INDEX idx_distress_needs_rescue ON distress_reports(needs_rescue) WHERE needs_rescue = TRUE;
CREATE INDEX idx_distress_location ON distress_reports USING GIST(location);
CREATE INDEX idx_distress_metadata ON distress_reports USING GIN(channel_metadata);


-- ============================================================================
-- TABLE: cross_references
-- Stores cross-reference results between distress reports and Agent 1 data
-- ============================================================================

CREATE TABLE IF NOT EXISTS cross_references (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    distress_report_id UUID NOT NULL REFERENCES distress_reports(id),
    
    -- Verification
    verification_status VARCHAR(15) NOT NULL CHECK (verification_status IN 
        ('verified', 'unverified', 'contradicted', 'pending')),
    
    -- Agent 1 data at time of cross-reference
    agent1_flood_severity VARCHAR(10),
    agent1_risk_score FLOAT,
    agent1_flood_depth_m FLOAT,
    agent1_flood_pct FLOAT,
    
    -- Priority calculation
    final_urgency VARCHAR(10) NOT NULL,
    final_priority_score FLOAT NOT NULL CHECK (final_priority_score >= 0 AND final_priority_score <= 1),
    priority_reasoning TEXT,
    
    cross_referenced_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_xref_distress ON cross_references(distress_report_id);
CREATE INDEX idx_xref_status ON cross_references(verification_status);
CREATE INDEX idx_xref_priority ON cross_references(final_priority_score DESC);


-- ============================================================================
-- TABLE: distress_queue
-- The final prioritized queue published to Agent 3
-- ============================================================================

CREATE TABLE IF NOT EXISTS distress_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    distress_report_id UUID NOT NULL REFERENCES distress_reports(id),
    
    -- Channel
    channel VARCHAR(30) NOT NULL,
    
    -- Location
    zone_id VARCHAR(50),
    zone_name VARCHAR(100),
    location GEOGRAPHY(POINT, 4326),
    
    -- Situation
    distress_type VARCHAR(30) NOT NULL,
    urgency VARCHAR(10) NOT NULL,
    people_count INTEGER,
    needs_rescue BOOLEAN DEFAULT FALSE,
    water_level_meters FLOAT,
    
    -- Priority
    priority_score FLOAT NOT NULL CHECK (priority_score >= 0 AND priority_score <= 1),
    flood_verified BOOLEAN DEFAULT FALSE,
    agent1_risk_score FLOAT,
    
    -- Resource recommendations
    recommended_resources JSONB DEFAULT '[]',
    
    -- Summary for dashboard
    summary TEXT,
    
    -- Status tracking
    status VARCHAR(20) DEFAULT 'pending' CHECK (status IN 
        ('pending', 'assigned', 'dispatched', 'resolved', 'expired')),
    assigned_to_agent3 BOOLEAN DEFAULT FALSE,
    
    -- Timing
    reported_at TIMESTAMP WITH TIME ZONE NOT NULL,
    queued_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    assigned_at TIMESTAMP WITH TIME ZONE,
    resolved_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_queue_priority ON distress_queue(priority_score DESC);
CREATE INDEX idx_queue_status ON distress_queue(status);
CREATE INDEX idx_queue_urgency ON distress_queue(urgency);
CREATE INDEX idx_queue_zone ON distress_queue(zone_id);
CREATE INDEX idx_queue_rescue ON distress_queue(needs_rescue) WHERE needs_rescue = TRUE;
CREATE INDEX idx_queue_location ON distress_queue USING GIST(location);


-- ============================================================================
-- TABLE: channel_stats
-- Aggregated channel statistics per monitoring cycle
-- ============================================================================

CREATE TABLE IF NOT EXISTS channel_stats (
    id SERIAL PRIMARY KEY,
    cycle_timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    
    social_media_count INTEGER DEFAULT 0,
    sms_ussd_count INTEGER DEFAULT 0,
    emergency_hotline_count INTEGER DEFAULT 0,
    satellite_population_count INTEGER DEFAULT 0,
    total_ingested INTEGER DEFAULT 0,
    
    verified_count INTEGER DEFAULT 0,
    contradicted_count INTEGER DEFAULT 0,
    unverified_count INTEGER DEFAULT 0,
    duplicate_count INTEGER DEFAULT 0,
    
    queue_size INTEGER DEFAULT 0,
    critical_items INTEGER DEFAULT 0,
    rescue_situations INTEGER DEFAULT 0,
    
    processing_time_seconds FLOAT
);

CREATE INDEX idx_channel_stats_time ON channel_stats(cycle_timestamp DESC);


-- ============================================================================
-- Trigger: auto-update updated_at
-- ============================================================================

CREATE OR REPLACE FUNCTION update_distress_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_distress_reports_updated
    BEFORE UPDATE ON distress_reports
    FOR EACH ROW EXECUTE FUNCTION update_distress_updated_at();
