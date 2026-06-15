-- Module 9.0 M5 — RLS validation harness (run on a throwaway Postgres).
-- Proves assignment-scoped RLS at the DATABASE level for the `authenticated` role.
-- auth.uid() is emulated via the custom GUC test.uid.

CREATE SCHEMA IF NOT EXISTS auth;
CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid
  AS $$ SELECT NULLIF(current_setting('test.uid', true), '')::uuid $$ LANGUAGE sql STABLE;
CREATE ROLE authenticated NOLOGIN;

CREATE TABLE users (id uuid PRIMARY KEY, auth_user_id uuid, role text, firm_id uuid);
CREATE TABLE user_client_assignments (user_id uuid, client_id uuid, firm_id uuid);
CREATE TABLE clients (id uuid PRIMARY KEY, firm_id uuid, is_internal boolean DEFAULT false, client_name text);
CREATE TABLE documents (id uuid PRIMARY KEY, firm_id uuid, client_id uuid, title text);
CREATE TABLE client_timeline_events (id uuid PRIMARY KEY, firm_id uuid, client_id text);  -- TEXT client_id
CREATE TABLE notifications (id uuid PRIMARY KEY, firm_id uuid, user_id uuid, client_id uuid);

CREATE OR REPLACE FUNCTION get_my_role() RETURNS text
  AS $$ SELECT role FROM users WHERE auth_user_id = auth.uid() $$ LANGUAGE sql STABLE SECURITY DEFINER;
CREATE OR REPLACE FUNCTION get_my_user_id() RETURNS uuid
  AS $$ SELECT id FROM users WHERE auth_user_id = auth.uid() $$ LANGUAGE sql STABLE SECURITY DEFINER;

INSERT INTO users(id,auth_user_id,role,firm_id) VALUES
 ('11111111-1111-1111-1111-111111111111','aaaaaaaa-0000-0000-0000-0000000000a1','Partner','ffffffff-1111-1111-1111-111111111111'),
 ('22222222-2222-2222-2222-222222222222','aaaaaaaa-0000-0000-0000-0000000000a2','Manager','ffffffff-1111-1111-1111-111111111111'),
 ('33333333-3333-3333-3333-333333333333','aaaaaaaa-0000-0000-0000-0000000000a3','Executive','ffffffff-1111-1111-1111-111111111111');
INSERT INTO clients(id,firm_id,client_name) VALUES
 ('c1111111-1111-1111-1111-111111111111','ffffffff-1111-1111-1111-111111111111','Assigned Co'),
 ('c2222222-2222-2222-2222-222222222222','ffffffff-1111-1111-1111-111111111111','Other Co');
INSERT INTO user_client_assignments(user_id,client_id,firm_id) VALUES
 ('33333333-3333-3333-3333-333333333333','c1111111-1111-1111-1111-111111111111','ffffffff-1111-1111-1111-111111111111'),
 ('22222222-2222-2222-2222-222222222222','c1111111-1111-1111-1111-111111111111','ffffffff-1111-1111-1111-111111111111');
INSERT INTO documents(id,firm_id,client_id,title) VALUES
 ('d1111111-1111-1111-1111-111111111111','ffffffff-1111-1111-1111-111111111111','c1111111-1111-1111-1111-111111111111','Doc for C1'),
 ('d2222222-2222-2222-2222-222222222222','ffffffff-1111-1111-1111-111111111111','c2222222-2222-2222-2222-222222222222','Doc for C2');
INSERT INTO client_timeline_events(id,firm_id,client_id) VALUES
 ('e1111111-1111-1111-1111-111111111111','ffffffff-1111-1111-1111-111111111111','c1111111-1111-1111-1111-111111111111'),
 ('e2222222-2222-2222-2222-222222222222','ffffffff-1111-1111-1111-111111111111','c2222222-2222-2222-2222-222222222222');
INSERT INTO notifications(id,firm_id,user_id,client_id) VALUES
 ('f1111111-1111-1111-1111-111111111111','ffffffff-1111-1111-1111-111111111111','33333333-3333-3333-3333-333333333333','c1111111-1111-1111-1111-111111111111'),
 ('f2222222-2222-2222-2222-222222222222','ffffffff-1111-1111-1111-111111111111','11111111-1111-1111-1111-111111111111','c2222222-2222-2222-2222-222222222222');

-- Emulate existing permissive firm-isolation policies (present in prod).
ALTER TABLE clients ENABLE ROW LEVEL SECURITY;  CREATE POLICY p ON clients FOR ALL TO authenticated USING (true);
ALTER TABLE documents ENABLE ROW LEVEL SECURITY; CREATE POLICY p ON documents FOR ALL TO authenticated USING (true);
ALTER TABLE client_timeline_events ENABLE ROW LEVEL SECURITY; CREATE POLICY p ON client_timeline_events FOR ALL TO authenticated USING (true);
ALTER TABLE notifications ENABLE ROW LEVEL SECURITY; CREATE POLICY p ON notifications FOR ALL TO authenticated USING (true);
GRANT SELECT ON clients, documents, client_timeline_events, notifications TO authenticated;
