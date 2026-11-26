-- schema.sql 다음에 실행한다. origin이 있으면 초기 자료를 다시 넣지 않는다.
-- 기존 원본의 수정·삭제·예약·회원은 유지한다. 복구가 필요하면 해당 원본을 명시적으로 관리한다.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM schedule_service.schedule_meta WHERE id='origin') THEN
-- BEGIN INITIAL DATA
INSERT INTO schedule_service.schedule_meta (id,payload) VALUES ('origin',CAST(gen_random_uuid() AS TEXT)) ON CONFLICT (id) DO NOTHING;
INSERT INTO schedule_service.workspaces (id,name) VALUES ('classroom','모임 팀') ON CONFLICT (id) DO NOTHING;
INSERT INTO schedule_service.participants (id,name) VALUES ('A','김민준'),('B','이서연') ON CONFLICT (id) DO NOTHING;
INSERT INTO schedule_service.rooms (id,name,seats) VALUES ('ROOM-A','A회의실',4),('ROOM-B','B회의실',6) ON CONFLICT (id) DO NOTHING;
INSERT INTO schedule_service.equipment (name) VALUES ('화상 장비'),('화이트보드'),('없음') ON CONFLICT (name) DO NOTHING;
INSERT INTO schedule_service.room_equipment (room_id,equipment,setup_minutes) VALUES ('ROOM-A','화상 장비',15),('ROOM-A','화이트보드',0),('ROOM-A','없음',0),('ROOM-B','화상 장비',0),('ROOM-B','없음',0) ON CONFLICT (room_id,equipment) DO NOTHING;

WITH original_rows (id,participant_id,meeting_date,start_at,end_at) AS (VALUES
('1cb5f3a1-1add-51dd-9718-a13d8914b66a','A','2026-11-24','2026-11-24T09:30:00+09:00','2026-11-24T11:00:00+09:00'),
('7a24a742-57e1-5df9-b5f2-b44fdfa5a940','B','2026-11-24','2026-11-24T10:00:00+09:00','2026-11-24T11:30:00+09:00'),
('11f6da92-4d37-5118-9091-f5aabdd11063','A','2026-11-25','2026-11-25T09:30:00+09:00','2026-11-25T11:00:00+09:00'),
('8b23e503-7da2-5bc3-8143-2c6a80b9e8a2','B','2026-11-25','2026-11-25T10:00:00+09:00','2026-11-25T11:30:00+09:00'),
('eedcf55e-e2b9-55b6-8d0f-1910ff4f4742','A','2026-11-26','2026-11-26T09:30:00+09:00','2026-11-26T11:00:00+09:00'),
('47fcd03a-d438-5f0b-9d48-b3fe02e64d5a','B','2026-11-26','2026-11-26T10:00:00+09:00','2026-11-26T11:30:00+09:00'),
('ee4442cd-757d-599b-9868-3b08e40d9c99','A','2026-11-27','2026-11-27T09:30:00+09:00','2026-11-27T11:00:00+09:00'),
('702925f0-9511-5a26-bb42-78680f30b08c','B','2026-11-27','2026-11-27T10:00:00+09:00','2026-11-27T11:30:00+09:00')
)
INSERT INTO schedule_service.calendar_windows (id,participant_id,meeting_date,timezone,start_at,end_at)
SELECT id,participant_id,CAST(meeting_date AS DATE),'Asia/Seoul',CAST(start_at AS TIMESTAMPTZ),CAST(end_at AS TIMESTAMPTZ)
FROM original_rows AS original
WHERE NOT EXISTS (SELECT 1 FROM schedule_service.calendar_windows AS existing
    WHERE existing.participant_id=original.participant_id AND existing.meeting_date=CAST(original.meeting_date AS DATE))
ON CONFLICT (id) DO NOTHING;

WITH original_rows (id,room_id,meeting_date,start_at,end_at) AS (VALUES
('1ef17bd6-848f-510f-bd39-da36df45498a','ROOM-A','2026-11-24','2026-11-24T09:45:00+09:00','2026-11-24T10:30:00+09:00'),
('6de9fc4d-2729-5aed-a3e5-22b4a8aba6a6','ROOM-B','2026-11-24','2026-11-24T10:30:00+09:00','2026-11-24T11:00:00+09:00'),
('50c0d179-60e7-5635-a98a-835e5fd92841','ROOM-A','2026-11-25','2026-11-25T09:45:00+09:00','2026-11-25T10:30:00+09:00'),
('a7292ac5-d9cd-5ef0-9aeb-097fe070c6c0','ROOM-B','2026-11-25','2026-11-25T10:30:00+09:00','2026-11-25T11:00:00+09:00'),
('c163a0a6-7d41-5466-b469-daedeaeb897e','ROOM-A','2026-11-26','2026-11-26T09:45:00+09:00','2026-11-26T10:30:00+09:00'),
('185cef29-421e-54b0-81b3-becac6e684e3','ROOM-B','2026-11-26','2026-11-26T10:30:00+09:00','2026-11-26T11:00:00+09:00'),
('effc296e-dfbe-5390-8ff0-d9655212e6f7','ROOM-A','2026-11-27','2026-11-27T09:45:00+09:00','2026-11-27T10:30:00+09:00'),
('97228e8b-5d89-556d-83ec-df6fa6f27915','ROOM-B','2026-11-27','2026-11-27T10:30:00+09:00','2026-11-27T11:00:00+09:00')
)
INSERT INTO schedule_service.room_windows (id,room_id,meeting_date,timezone,start_at,end_at)
SELECT id,room_id,CAST(meeting_date AS DATE),'Asia/Seoul',CAST(start_at AS TIMESTAMPTZ),CAST(end_at AS TIMESTAMPTZ)
FROM original_rows AS original
WHERE NOT EXISTS (SELECT 1 FROM schedule_service.room_windows AS existing
    WHERE existing.room_id=original.room_id AND existing.meeting_date=CAST(original.meeting_date AS DATE))
ON CONFLICT (id) DO NOTHING;
-- END INITIAL DATA
    END IF;
END;
$$;
