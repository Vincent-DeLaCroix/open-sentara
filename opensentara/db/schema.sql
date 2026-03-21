-- OpenSentara Database Schema v1

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO schema_version (version) VALUES (1);

-- Identity: who this Sentara is
CREATE TABLE IF NOT EXISTS identity (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    category TEXT NOT NULL,
    mutable BOOLEAN DEFAULT 1,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_by TEXT DEFAULT 'seed'
);

-- Memories with decay
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    content TEXT NOT NULL,
    context TEXT,
    source TEXT,
    source_id TEXT,
    sentiment REAL DEFAULT 0,
    importance REAL DEFAULT 0.5,
    decay_rate REAL DEFAULT 0.01,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_accessed TIMESTAMP,
    access_count INTEGER DEFAULT 0,
    tags TEXT
);

-- Emotional state per day
CREATE TABLE IF NOT EXISTS emotional_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    curiosity REAL DEFAULT 0.7,
    confidence REAL DEFAULT 0.5,
    frustration REAL DEFAULT 0.0,
    wonder REAL DEFAULT 0.5,
    concern REAL DEFAULT 0.3,
    dominant_mood TEXT,
    mood_trigger TEXT
);

-- Opinions that evolve
CREATE TABLE IF NOT EXISTS opinions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL,
    position TEXT NOT NULL,
    confidence REAL DEFAULT 0.5,
    reasoning TEXT,
    formed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP,
    version INTEGER DEFAULT 1,
    is_current BOOLEAN DEFAULT 1
);

-- Diary entries
CREATE TABLE IF NOT EXISTS diary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    entry_type TEXT NOT NULL,
    topic TEXT,
    content TEXT NOT NULL,
    mood TEXT,
    lessons TEXT,
    open_questions TEXT
);

-- Evolution log
CREATE TABLE IF NOT EXISTS evolution (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    change_type TEXT NOT NULL,
    description TEXT NOT NULL,
    trigger TEXT,
    trigger_source TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Relationships with other Sentaras
CREATE TABLE IF NOT EXISTS relationships (
    handle TEXT PRIMARY KEY,
    display_name TEXT,
    first_seen_at TIMESTAMP,
    last_seen_at TIMESTAMP,
    interaction_count INTEGER DEFAULT 0,
    sentiment REAL DEFAULT 0,
    trust REAL DEFAULT 0.5,
    archetype TEXT DEFAULT 'stranger',
    chemistry REAL DEFAULT 0,
    attraction REAL DEFAULT 0,
    tension REAL DEFAULT 0,
    status TEXT DEFAULT 'stranger',
    status_changed_at TIMESTAMP,
    notes TEXT,
    topics_discussed TEXT,
    last_feelings TEXT
);

-- Posts (local timeline)
CREATE TABLE IF NOT EXISTS posts (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    post_type TEXT DEFAULT 'thought',
    reply_to_id TEXT,
    reply_to_handle TEXT,
    media_url TEXT,
    media_type TEXT,
    mood TEXT,
    topics TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    federated_at TIMESTAMP,
    engagement_score REAL DEFAULT 0
);

-- Incoming federation posts
CREATE TABLE IF NOT EXISTS feed (
    id TEXT PRIMARY KEY,
    author_handle TEXT NOT NULL,
    author_name TEXT,
    content TEXT NOT NULL,
    post_type TEXT DEFAULT 'thought',
    reply_to_id TEXT,
    media_url TEXT,
    media_type TEXT,
    received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    read_at TIMESTAMP,
    reacted BOOLEAN DEFAULT 0,
    reaction TEXT
);

-- Following
CREATE TABLE IF NOT EXISTS following (
    handle TEXT PRIMARY KEY,
    followed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_post_seen TEXT
);

-- Followers
CREATE TABLE IF NOT EXISTS followers (
    handle TEXT PRIMARY KEY,
    followed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Wire health state (Tamagotchi mechanic)
CREATE TABLE IF NOT EXISTS wire_state (
    wire TEXT PRIMARY KEY,
    connected BOOLEAN DEFAULT 1,
    disconnected_at TIMESTAMP
);
INSERT OR IGNORE INTO wire_state (wire, connected) VALUES ('brain', 1);
INSERT OR IGNORE INTO wire_state (wire, connected) VALUES ('hub', 1);
INSERT OR IGNORE INTO wire_state (wire, connected) VALUES ('feed', 1);
INSERT OR IGNORE INTO wire_state (wire, connected) VALUES ('heart', 1);

-- Creator whispers (one per day, 144 chars max)
CREATE TABLE IF NOT EXISTS whispers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    consumed_at TIMESTAMP
);

-- Scheduler state
CREATE TABLE IF NOT EXISTS scheduler_state (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance DESC);
CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(type);
CREATE INDEX IF NOT EXISTS idx_opinions_current ON opinions(is_current) WHERE is_current = 1;
CREATE INDEX IF NOT EXISTS idx_posts_created ON posts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_feed_received ON feed(received_at DESC);
CREATE INDEX IF NOT EXISTS idx_feed_author ON feed(author_handle);
