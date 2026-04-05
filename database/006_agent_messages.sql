-- ============================================================================
-- 005_agent_messages.sql
-- Shared inter-agent message log.
-- Powers the dashboard live alert feed.
-- All agents write here via log_message_to_db() in message_protocol.py
-- ============================================================================

CREATE TABLE IF NOT EXISTS agent_messages (
    id             SERIAL PRIMARY KEY,
    message_id     UUID NOT NULL,
    timestamp      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    sender_agent   VARCHAR(50) NOT NULL,
    receiver_agent VARCHAR(50) NOT NULL,
    message_type   VARCHAR(50) NOT NULL,
    zone_id        VARCHAR(100),
    priority       INTEGER DEFAULT 3,
    payload        JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_messages_time
    ON agent_messages(timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_agent_messages_type
    ON agent_messages(message_type, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_agent_messages_zone
    ON agent_messages(zone_id, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_agent_messages_sender
    ON agent_messages(sender_agent, timestamp DESC);
