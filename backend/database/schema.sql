-- Supabase SQL Editor에서 먼저 실행한다. 기존 테이블과 업무 행은 유지한다.
CREATE SCHEMA IF NOT EXISTS schedule_service;
CREATE TABLE IF NOT EXISTS schedule_service.schedule_sessions (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, team_id TEXT NOT NULL, version INTEGER NOT NULL, payload TEXT NOT NULL, explanation_token TEXT, explanation_until TIMESTAMPTZ);
-- 이미 사용하던 문의 테이블에도 설명 처리권 열만 비파괴적으로 추가한다.
ALTER TABLE schedule_service.schedule_sessions ADD COLUMN IF NOT EXISTS explanation_token TEXT;
ALTER TABLE schedule_service.schedule_sessions ADD COLUMN IF NOT EXISTS explanation_until TIMESTAMPTZ;
-- 조회 근거가 같은 저장소에서 왔는지 확인하는 origin.
CREATE TABLE IF NOT EXISTS schedule_service.schedule_meta (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS schedule_service.workspaces (id TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS schedule_service.workspace_memberships (workspace_id TEXT NOT NULL REFERENCES schedule_service.workspaces(id), user_id TEXT NOT NULL, display_name TEXT NOT NULL, role TEXT NOT NULL CHECK (role = 'member'), joined_at TIMESTAMPTZ NOT NULL, PRIMARY KEY (workspace_id,user_id));
CREATE TABLE IF NOT EXISTS schedule_service.participants (id TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS schedule_service.rooms (id TEXT PRIMARY KEY, name TEXT NOT NULL, seats INTEGER NOT NULL CHECK (seats > 0));
CREATE TABLE IF NOT EXISTS schedule_service.equipment (name TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS schedule_service.room_equipment (room_id TEXT NOT NULL REFERENCES schedule_service.rooms(id), equipment TEXT NOT NULL REFERENCES schedule_service.equipment(name), setup_minutes INTEGER NOT NULL CHECK (setup_minutes >= 0), PRIMARY KEY (room_id,equipment));
CREATE TABLE IF NOT EXISTS schedule_service.calendar_windows (id TEXT PRIMARY KEY, participant_id TEXT NOT NULL REFERENCES schedule_service.participants(id), meeting_date DATE NOT NULL, timezone TEXT NOT NULL, start_at TIMESTAMPTZ NOT NULL, end_at TIMESTAMPTZ NOT NULL, CHECK (start_at < end_at));
CREATE TABLE IF NOT EXISTS schedule_service.room_windows (id TEXT PRIMARY KEY, room_id TEXT NOT NULL REFERENCES schedule_service.rooms(id), meeting_date DATE NOT NULL, timezone TEXT NOT NULL, start_at TIMESTAMPTZ NOT NULL, end_at TIMESTAMPTZ NOT NULL, CHECK (start_at < end_at));
CREATE TABLE IF NOT EXISTS schedule_service.reservations (proposal_id TEXT PRIMARY KEY, event_id TEXT NOT NULL UNIQUE, session_id TEXT NOT NULL REFERENCES schedule_service.schedule_sessions(id), owner_id TEXT NOT NULL, team_id TEXT NOT NULL, request_id TEXT NOT NULL, revision INTEGER NOT NULL CHECK (revision > 0), meeting_date DATE NOT NULL, timezone TEXT NOT NULL, room_id TEXT NOT NULL REFERENCES schedule_service.rooms(id), start_at TIMESTAMPTZ NOT NULL, end_at TIMESTAMPTZ NOT NULL, room_busy_start TIMESTAMPTZ NOT NULL, equipment TEXT NOT NULL REFERENCES schedule_service.equipment(name), setup_minutes INTEGER NOT NULL CHECK (setup_minutes >= 0), payload TEXT NOT NULL, CHECK (room_busy_start <= start_at AND start_at < end_at));
CREATE TABLE IF NOT EXISTS schedule_service.reservation_attendees (proposal_id TEXT NOT NULL REFERENCES schedule_service.reservations(proposal_id) ON DELETE CASCADE, participant_id TEXT NOT NULL REFERENCES schedule_service.participants(id), PRIMARY KEY (proposal_id,participant_id));
CREATE INDEX IF NOT EXISTS calendar_windows_day ON schedule_service.calendar_windows (participant_id,meeting_date);
CREATE INDEX IF NOT EXISTS room_windows_day ON schedule_service.room_windows (room_id,meeting_date);
CREATE INDEX IF NOT EXISTS reservations_room_day ON schedule_service.reservations (room_id,meeting_date);
CREATE INDEX IF NOT EXISTS reservation_attendees_person ON schedule_service.reservation_attendees (participant_id,proposal_id);
