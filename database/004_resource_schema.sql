-- ============================================================================
-- 003_resource_schema.sql
-- Database Schema for Resource Management (Agent 3)
-- Run after 002_satellite_schema.sql (Agent 1)
-- ============================================================================

-- Resource inventory
CREATE TABLE IF NOT EXISTS resource_units (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    resource_type        VARCHAR(30) NOT NULL
                             CHECK (resource_type IN (
                                 'rescue_boat', 'medical_team', 'medical_kit',
                                 'food_supply', 'water_supply'
                             )),
    name                 VARCHAR(100) NOT NULL,
    status               VARCHAR(20) NOT NULL DEFAULT 'available'
                             CHECK (status IN (
                                 'available', 'deployed', 'returning', 'maintenance'
                             )),
    capacity             INTEGER NOT NULL DEFAULT 1,
    current_location     GEOGRAPHY(POINT, 4326) NOT NULL,
    base_location        GEOGRAPHY(POINT, 4326) NOT NULL,
    assigned_zone_id     VARCHAR(100),
    assigned_incident_id VARCHAR(100),
    deployed_at          TIMESTAMP WITH TIME ZONE,
    created_at           TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at           TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Inventory audit log
CREATE TABLE IF NOT EXISTS inventory_transactions (
    id             SERIAL PRIMARY KEY,
    transaction_id UUID DEFAULT gen_random_uuid(),
    timestamp      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    resource_type  VARCHAR(30) NOT NULL,
    unit_id        UUID REFERENCES resource_units(id),
    direction      VARCHAR(20) NOT NULL
                       CHECK (direction IN (
                           'allocated', 'restocked', 'returned', 'maintenance'
                       )),
    quantity       INTEGER NOT NULL DEFAULT 1,
    triggered_by   VARCHAR(50),   -- 'agent_3_auto', 'manual_restock', 'agent_4_return'
    incident_id    VARCHAR(100),
    zone_id        VARCHAR(100),
    notes          TEXT
);

-- Resource allocations (one per incident processed)
CREATE TABLE IF NOT EXISTS resource_allocations (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp           TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    incident_id         VARCHAR(100) NOT NULL,
    zone_id             VARCHAR(100) NOT NULL,
    zone_name           VARCHAR(200),
    destination         GEOGRAPHY(POINT, 4326) NOT NULL,
    priority            INTEGER CHECK (priority >= 1 AND priority <= 5),
    urgency             VARCHAR(30),
    num_people_affected INTEGER,
    allocated_units     JSONB NOT NULL,   -- array of {unit_id, type, name}
    partial_allocation  BOOLEAN DEFAULT FALSE,
    requires_medical    BOOLEAN DEFAULT FALSE,
    status              VARCHAR(20) DEFAULT 'pending'
                            CHECK (status IN ('pending', 'dispatched', 'completed')),
    completed_at        TIMESTAMP WITH TIME ZONE
);

-- ---- Indexes ---------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_resource_units_type_status
    ON resource_units(resource_type, status);

CREATE INDEX IF NOT EXISTS idx_resource_units_location
    ON resource_units USING GIST(current_location);

CREATE INDEX IF NOT EXISTS idx_inventory_transactions_time
    ON inventory_transactions(timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_resource_allocations_zone
    ON resource_allocations(zone_id, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_resource_allocations_incident
    ON resource_allocations(incident_id);

-- ---- Helper view -----------------------------------------------------------
CREATE OR REPLACE VIEW inventory_summary AS
SELECT
    resource_type,
    COUNT(*)                                          AS total,
    COUNT(*) FILTER (WHERE status = 'available')     AS available,
    COUNT(*) FILTER (WHERE status = 'deployed')      AS deployed,
    COUNT(*) FILTER (WHERE status = 'returning')     AS returning,
    COUNT(*) FILTER (WHERE status = 'maintenance')   AS maintenance
FROM resource_units
GROUP BY resource_type;
