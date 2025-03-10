CREATE TABLE IF NOT EXISTS version (version TEXT PRIMARY KEY);
INSERT INTO version (version) VALUES ('v3.14') ON CONFLICT (version) DO NOTHING;
CREATE TABLE IF NOT EXISTS plugins (plugin TEXT PRIMARY KEY, version TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS message_persistence (server_name TEXT NOT NULL, embed_name TEXT NOT NULL, embed BIGINT NOT NULL, thread BIGINT NULL, PRIMARY KEY (server_name, embed_name));
CREATE TABLE IF NOT EXISTS instances (node TEXT NOT NULL, instance TEXT NOT NULL, port BIGINT NOT NULL, server_name TEXT, last_seen TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'utc'), PRIMARY KEY(node, instance));
CREATE UNIQUE INDEX IF NOT EXISTS idx_instances ON instances (node, port);
CREATE UNIQUE INDEX IF NOT EXISTS idx_instances_server_name ON instances (server_name);
CREATE TABLE IF NOT EXISTS servers (server_name TEXT PRIMARY KEY, blue_password TEXT, red_password TEXT, maintenance BOOLEAN NOT NULL DEFAULT FALSE);
CREATE TABLE IF NOT EXISTS audit(id SERIAL PRIMARY KEY, node TEXT NOT NULL, event TEXT NOT NULL, server_name TEXT, discord_id BIGINT, ucid TEXT, time TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'utc'));
