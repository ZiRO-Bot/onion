CREATE TABLE IF NOT EXISTS releases (
	id INTEGER PRIMARY KEY,
	title TEXT,
	episode INTEGER,
	thumbnail_url TEXT,
	publish_at INTEGER,
	published INTEGER,
	UNIQUE (id, episode)
);
