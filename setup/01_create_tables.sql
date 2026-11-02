-- Run ONCE in the target Lakebase SQL editor, as the database owner.
-- Select the intended database (normally databricks_postgres), NOT a Spark SQL warehouse.
-- Refuses to run if any active Atlas table already exists. Does not copy history.
BEGIN;
SET LOCAL search_path TO public;
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_tables WHERE schemaname = 'public'
    AND tablename IN ('atlas_users','atlas_conversations','atlas_messages','atlas_comments','atlas_tool_runs')
  ) THEN
    RAISE EXCEPTION 'Atlas tables already exist. This script is for a fresh database only.';
  END IF;
END;
$$;

CREATE TABLE atlas_users (
	id VARCHAR(100) NOT NULL,
	name VARCHAR(250) NOT NULL,
	email VARCHAR(320) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE atlas_conversations (
	id VARCHAR(36) NOT NULL,
	user_id VARCHAR(100) NOT NULL,
	title VARCHAR(120) NOT NULL,
	pinned BOOLEAN NOT NULL,
	archived BOOLEAN NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	generation_started TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	FOREIGN KEY(user_id) REFERENCES atlas_users (id) ON DELETE CASCADE
);

CREATE INDEX ix_atlas_conversations_updated_at ON atlas_conversations (updated_at);

CREATE INDEX ix_atlas_conversations_user_id ON atlas_conversations (user_id);

CREATE TABLE atlas_messages (
	id VARCHAR(36) NOT NULL,
	conversation_id VARCHAR(36) NOT NULL,
	role VARCHAR(12) NOT NULL,
	content TEXT NOT NULL,
	feedback VARCHAR(4),
	saved BOOLEAN NOT NULL,
	status VARCHAR(12) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(conversation_id) REFERENCES atlas_conversations (id) ON DELETE CASCADE
);

CREATE INDEX atlas_messages_order ON atlas_messages (conversation_id, created_at);

CREATE INDEX ix_atlas_messages_conversation_id ON atlas_messages (conversation_id);

CREATE TABLE atlas_comments (
	id VARCHAR(36) NOT NULL,
	message_id VARCHAR(36) NOT NULL,
	text TEXT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(message_id) REFERENCES atlas_messages (id) ON DELETE CASCADE
);

CREATE INDEX ix_atlas_comments_message_id ON atlas_comments (message_id);

CREATE TABLE atlas_tool_runs (
	id VARCHAR(36) NOT NULL,
	message_id VARCHAR(36) NOT NULL,
	call_id VARCHAR(250) NOT NULL,
	name VARCHAR(100) NOT NULL,
	status VARCHAR(16) NOT NULL,
	input TEXT NOT NULL,
	output TEXT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(message_id) REFERENCES atlas_messages (id) ON DELETE CASCADE
);

CREATE INDEX ix_atlas_tool_runs_message_id ON atlas_tool_runs (message_id);

COMMIT;
