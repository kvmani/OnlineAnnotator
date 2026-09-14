-- Database written by Online Annotator v1.0.1 (schema 1), generated with that tag's own
-- code for tests/test_migrations.py. Synthetic rows only; no real accounts or images.
-- PRAGMA user_version is not part of an SQL dump, so it is restored explicitly below.
CREATE TABLE audit_events (
	id INTEGER NOT NULL, 
	timestamp DATETIME NOT NULL, 
	user_email VARCHAR(255) NOT NULL, 
	action VARCHAR(40) NOT NULL, 
	project_id INTEGER, 
	image_id INTEGER, 
	summary TEXT NOT NULL, 
	details TEXT NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE auth_sessions (
	token_hash VARCHAR(64) NOT NULL, 
	user_id INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	expires_at DATETIME NOT NULL, 
	last_seen_at DATETIME NOT NULL, 
	PRIMARY KEY (token_hash), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE TABLE exports (
	id INTEGER NOT NULL, 
	project_id INTEGER NOT NULL, 
	created_by VARCHAR(255) NOT NULL, 
	created_at DATETIME NOT NULL, 
	filename VARCHAR(255) NOT NULL, 
	size_bytes INTEGER NOT NULL, 
	sha256 VARCHAR(64) NOT NULL, 
	image_count INTEGER NOT NULL, 
	options TEXT NOT NULL, 
	summary TEXT NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE
);
CREATE TABLE image_locks (
	image_id INTEGER NOT NULL, 
	user_email VARCHAR(255) NOT NULL, 
	user_name VARCHAR(255) NOT NULL, 
	acquired_at DATETIME NOT NULL, 
	expires_at DATETIME NOT NULL, 
	PRIMARY KEY (image_id), 
	FOREIGN KEY(image_id) REFERENCES images (id) ON DELETE CASCADE
);
CREATE TABLE images (
	id INTEGER NOT NULL, 
	project_id INTEGER NOT NULL, 
	original_filename VARCHAR(255) NOT NULL, 
	stem VARCHAR(200) NOT NULL, 
	stored_name VARCHAR(255) NOT NULL, 
	display_name VARCHAR(255) NOT NULL, 
	sha256 VARCHAR(64) NOT NULL, 
	width INTEGER NOT NULL, 
	height INTEGER NOT NULL, 
	source_mode VARCHAR(20) NOT NULL, 
	conversion_note TEXT NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	split VARCHAR(12) NOT NULL, 
	assigned_to VARCHAR(255), 
	notes TEXT NOT NULL, 
	uploaded_by VARCHAR(255) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	working_revision INTEGER NOT NULL, 
	working_sha256 VARCHAR(64), 
	working_class_pixels TEXT NOT NULL, 
	working_updated_by VARCHAR(255), 
	working_updated_at DATETIME, 
	working_origin VARCHAR(255) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_image_sha UNIQUE (project_id, sha256), 
	CONSTRAINT uq_image_stem UNIQUE (project_id, stem), 
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE
);
INSERT INTO "images" VALUES(1,1,'a.png','a','1_original.png','1_original.png','0000000000000000000000000000000000000000000000000000000000000000',64,48,'','','approved','unassigned',NULL,'','anil@lab.test','2026-09-01 09:30:00.000000','2026-09-01 09:30:00.000000',1,'1111111111111111111111111111111111111111111111111111111111111111','{}',NULL,NULL,'');
CREATE TABLE label_classes (
	id INTEGER NOT NULL, 
	project_id INTEGER NOT NULL, 
	"index" INTEGER NOT NULL, 
	name VARCHAR(80) NOT NULL, 
	color VARCHAR(7) NOT NULL, 
	description TEXT NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_class_index UNIQUE (project_id, "index"), 
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE
);
INSERT INTO "label_classes" VALUES(1,1,1,'Hydride','#FF0000','');
CREATE TABLE otp_challenges (
	id VARCHAR(64) NOT NULL, 
	user_id INTEGER NOT NULL, 
	code_hash VARCHAR(64) NOT NULL, 
	expires_at DATETIME NOT NULL, 
	attempts INTEGER NOT NULL, 
	used BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE TABLE projects (
	id INTEGER NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	description TEXT NOT NULL, 
	guidelines TEXT NOT NULL, 
	archived BOOLEAN NOT NULL, 
	created_by VARCHAR(255) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (name)
);
INSERT INTO "projects" VALUES(1,'Legacy hydrides','','',0,'lead@lab.test','2026-09-01 09:30:00.000000');
CREATE TABLE users (
	id INTEGER NOT NULL, 
	email VARCHAR(255) NOT NULL, 
	full_name VARCHAR(255) NOT NULL, 
	role VARCHAR(20) NOT NULL, 
	password_hash VARCHAR(255) NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	must_change_password BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	last_login_at DATETIME, 
	PRIMARY KEY (id)
);
INSERT INTO "users" VALUES(1,'lead@lab.test','Lead Scientist','admin','not-a-real-bcrypt-hash',1,0,'2026-09-01 09:30:00.000000',NULL);
INSERT INTO "users" VALUES(2,'rita@lab.test','Rita Rao','reviewer','not-a-real-bcrypt-hash',1,0,'2026-09-01 09:30:00.000000',NULL);
INSERT INTO "users" VALUES(3,'anil@lab.test','Anil Nair','annotator','not-a-real-bcrypt-hash',1,0,'2026-09-01 09:30:00.000000',NULL);
CREATE TABLE versions (
	id INTEGER NOT NULL, 
	image_id INTEGER NOT NULL, 
	number INTEGER NOT NULL, 
	mask_file VARCHAR(255) NOT NULL, 
	mask_sha256 VARCHAR(64) NOT NULL, 
	class_pixels TEXT NOT NULL, 
	kind VARCHAR(20) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	created_by VARCHAR(255) NOT NULL, 
	created_at DATETIME NOT NULL, 
	note TEXT NOT NULL, 
	reviewed_by VARCHAR(255), 
	reviewed_at DATETIME, 
	review_comment TEXT NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_version_number UNIQUE (image_id, number), 
	FOREIGN KEY(image_id) REFERENCES images (id) ON DELETE CASCADE
);
INSERT INTO "versions" VALUES(1,1,1,'v0001.png','1111111111111111111111111111111111111111111111111111111111111111','{"1": 180}','submission','approved','anil@lab.test','2026-09-01 09:30:00.000000','','rita@lab.test','2026-09-01 09:30:00.000000','');
CREATE UNIQUE INDEX ix_users_email ON users (email);
CREATE INDEX ix_audit_events_image_id ON audit_events (image_id);
CREATE INDEX ix_audit_events_project_id ON audit_events (project_id);
CREATE INDEX ix_audit_events_action ON audit_events (action);
CREATE INDEX ix_audit_events_user_email ON audit_events (user_email);
CREATE INDEX ix_audit_events_timestamp ON audit_events (timestamp);
CREATE INDEX ix_auth_sessions_user_id ON auth_sessions (user_id);
CREATE INDEX ix_otp_challenges_user_id ON otp_challenges (user_id);
CREATE INDEX ix_label_classes_project_id ON label_classes (project_id);
CREATE INDEX ix_images_status ON images (status);
CREATE INDEX ix_images_project_id ON images (project_id);
CREATE INDEX ix_images_sha256 ON images (sha256);
CREATE INDEX ix_exports_project_id ON exports (project_id);
CREATE INDEX ix_versions_image_id ON versions (image_id);
CREATE INDEX ix_versions_status ON versions (status);
PRAGMA user_version=1;
