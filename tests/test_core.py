# -*- coding: utf-8 -*-
"""
핵심 동작 자동 점검 (tests/run_tests.py로 실행 : 실제 데이터와 분리된 임시 폴더에서 돌아요)

- 운영진 로그인 : 비밀번호 · 통행증(위조 불가) · 메인 페이지 운영진 로그인
- 정보 보호 : 러너에게 수식 · 운영진 로그 · 운영진 전용 상태가 가지 않음
- 전투 방 입장 : 팀 편성된 참여자만 · 관전 허용 · 비공개
- 배틀 룸 목록 : 비공개는 러너에게 안 보임 · 순서
- PVP 행동 횟수
- LOOP : 시작 → 사건 → 초기화(기록까지 지움) · 국가 반반
- 공지 : 고정 공지 5개
- 백업 : 운영진만 상태 보기 · 지금 백업
"""
import os
import sys
import unittest

sys.path.insert(0, os.getcwd())
assert os.environ.get("EARTHTERRA_TEST") == "1", "tests/run_tests.py로 실행해 주세요(실제 데이터 보호)."

import webapp  # noqa: E402
import rooms as rooms_mod  # noqa: E402
import loop_game  # noqa: E402

PW = "test-pw-1234"
rooms_mod.load_rooms()
rooms_mod.ensure_lounge()


def lounge():
    return next(r for r in rooms_mod.ROOMS.values() if r.battle_type == "lounge")


def names(received, name):
    return [x["args"][0] if x["args"] else None for x in received if x["name"] == name]


class Client:
    """소켓 접속 하나(브라우저 탭 하나와 같아요)."""

    def __init__(self, flask_client=None):
        self.http = flask_client or webapp.app.test_client()
        self.sio = webapp.socketio.test_client(webapp.app, flask_test_client=self.http)

    def join(self, room, nickname, **extra):
        self.sio.get_received()
        self.sio.emit("join", dict(room_id=room.id, key=room.guest_key, nickname=nickname, **extra))
        return self.sio.get_received()

    def emit(self, ev, data=None):
        self.sio.get_received()
        self.sio.emit(ev, data or {})
        return self.sio.get_received()

    def close(self):
        if self.sio.is_connected():
            self.sio.disconnect()


def errors(rec):
    return [a.get("message", "") for a in names(rec, "error") if a]


class TestGmLogin(unittest.TestCase):
    def test_wrong_password_rejected(self):
        c = Client()
        rec = c.join(lounge(), "GM", gm_password="wrong")
        self.assertTrue(errors(rec), "틀린 비밀번호인데 거절되지 않음")
        self.assertFalse(names(rec, "joined"))
        c.close()

    def test_password_then_pass_token(self):
        c = Client()
        rec = c.join(lounge(), "GM", gm_password=PW)
        joined = names(rec, "joined")
        self.assertTrue(joined and joined[0].get("gm_pass"), "운영진 통행증이 오지 않음")
        token = joined[0]["gm_pass"]
        c.close()
        c2 = Client()
        rec2 = c2.join(lounge(), "GM", gm_pass=token)
        self.assertFalse(errors(rec2), "통행증으로 다시 들어오지 못함")
        self.assertTrue(names(rec2, "joined"))
        c2.close()

    def test_forged_pass_rejected(self):
        c = Client()
        rec = c.join(lounge(), "GM", gm_pass="forged.token.value")
        self.assertTrue(errors(rec), "위조 통행증이 통과됨")
        c.close()

    def test_room_list_needs_admin(self):
        http = webapp.app.test_client()
        r = http.get("/")
        self.assertIn(r.status_code, (301, 302), "운영진 로그인 없이 방 목록이 열림")
        r = http.post("/login", data={"password": PW})
        self.assertIn(r.status_code, (301, 302))
        r = http.get("/")
        self.assertEqual(r.status_code, 200)
        # 메인 페이지 운영진 로그인 브라우저는 비밀번호 없이 GM
        c = Client(http)
        rec = c.join(lounge(), "GM")
        self.assertFalse(errors(rec), "운영진 세션인데 GM 입장이 거절됨")
        c.close()


class TestNoLeak(unittest.TestCase):
    def test_runner_gets_no_gm_data(self):
        c = Client()
        rec = c.join(lounge(), "AA")
        self.assertFalse(errors(rec))
        self.assertFalse(names(rec, "gm_state"), "러너에게 운영진 상태(gm_state)가 감")
        for st in names(rec, "public_state"):
            self.assertFalse(st.get("operator_log"), "러너 상태에 운영진 로그가 들어 있음")
            self.assertNotIn("formulas", st, "러너 상태에 수식이 들어 있음")
        c.close()


class TestBattleRoom(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.room = rooms_mod.create_room("pvp", name="점검 PVP")
        cls.room.hidden = False
        cls.gm = Client()
        cls.gm.join(cls.room, "GM", gm_password=PW)
        cls.gm.emit("preview_teams", {"team_a": ["AA"], "team_b": ["AB"]})

    @classmethod
    def tearDownClass(cls):
        cls.gm.close()

    def set_watch(self, on):
        self.gm.emit("set_chat_tabs", {"tabs": {"spectator": on}})

    def test_participant_can_enter(self):
        c = Client()
        rec = c.join(self.room, "AA")
        self.assertFalse(errors(rec), "편성된 참여자가 못 들어감")
        c.close()

    def test_non_participant_blocked(self):
        c = Client()
        rec = c.join(self.room, "AC")
        self.assertTrue(errors(rec), "편성되지 않은 캐릭터가 들어감")
        c.close()

    def test_watch_toggle(self):
        self.set_watch(False)
        c = Client()
        self.assertTrue(errors(c.join(self.room, "익명")), "관전 꺼짐인데 관전 입장됨")
        c.close()
        self.set_watch(True)
        c = Client()
        self.assertFalse(errors(c.join(self.room, "익명")), "관전 켜짐인데 관전 입장 안 됨")
        c.close()

    def test_hidden_room(self):
        self.gm.emit("battle_set_hidden", {"hidden": True})
        try:
            c = Client()
            self.assertTrue(errors(c.join(self.room, "AA")), "비공개인데 참여자가 들어감")
            c.close()
            r = Client()
            r.join(lounge(), "AA")
            lst = names(r.emit("battle_list"), "battle_list")[-1]
            self.assertNotIn(self.room.id, [b["id"] for b in lst["battles"]], "비공개 전투가 러너 목록에 보임")
            r.close()
        finally:
            self.gm.emit("battle_set_hidden", {"hidden": False})

    def test_action_count(self):
        self.gm.emit("set_action_count", {"name": "AA", "count": 3})
        rec = self.gm.emit("start_battle", {"team_a": ["AA"], "team_b": ["AB"]})
        b = self.room.game.battle
        self.assertIsNotNone(b, "전투가 시작되지 않음")
        aa = b.find_character("AA")
        self.assertEqual(aa.actions_per_turn, 3, "행동 횟수 3이 적용되지 않음")
        self.gm.emit("set_action_count", {"name": "AA", "count": 1})
        self.assertEqual(aa.actions_per_turn, 1, "진행 중 행동 횟수 변경이 적용되지 않음")


class TestEngine(unittest.TestCase):
    def test_multi_action_and_undo(self):
        import config
        from models import Character
        from battle import Battle, BattleError
        st = {k: 5 for k in config.STAT_KEYS}
        A = [Character("X1", "스트라이커", dict(st)), Character("X2", "가디언", dict(st))]
        B = [Character("Y1", "스트라이커", dict(st)), Character("Y2", "가디언", dict(st)), Character("Y3", "메딕", dict(st))]
        bt = Battle(A, B)
        key = bt._team_key(bt.current_turn_team)
        mine = [c for c in A + B if c.team == key]
        other = [c for c in A + B if c.team != key]
        npc = mine[0]
        npc.actions_per_turn = 3
        for i in range(3):
            bt.perform_attack(npc.name, other[i % len(other)].name)
        self.assertTrue(npc.has_acted)
        with self.assertRaises(BattleError):
            bt.perform_attack(npc.name, other[-1].name)
        bt.undo_last()
        self.assertEqual(npc.actions_left, 1)
        self.assertFalse(bt.can_advance_turn(), "행동이 남았는데 턴이 넘어갈 수 있음")


class TestLoop(unittest.TestCase):
    def test_start_play_reset(self):
        book = loop_game.LoopBook(path=os.path.join(os.getcwd(), "loop_runs_test.json"))
        book.data = {}
        n = "TEST#unittestdevice1"
        book.start(n, "res")
        self.assertEqual(book.data[n]["run"]["res"], "res", "공명자로 시작하지 않음")
        book.begin(n)
        for _ in range(200):
            r = book.data[n]["run"]
            if r["status"] == "event":
                for k in range(3):
                    try:
                        book.choose(n, r["event"], k)
                        break
                    except loop_game.LoopError:
                        pass
                else:
                    break
            elif r["status"] == "result":
                book.next(n)
            elif r["status"] == "dead":
                book.after_death(n, "end")
            elif r["status"] == "ending":
                book.finish(n)
            else:
                break
        self.assertTrue(book.data[n]["lives"], "생애가 기록되지 않음")
        self.assertTrue(book.life_detail(n, 0)["log"], "지난 운명 기록을 못 불러옴")
        book.reset(n, force=True)
        self.assertEqual(book.data[n]["lives"], [], "초기화했는데 지난 운명이 남음")
        self.assertIsNone(book.data[n]["run"])

    def test_country_random_after_reset(self):
        book = loop_game.LoopBook(path=os.path.join(os.getcwd(), "loop_runs_test2.json"))
        book.data = {}
        n = "TEST#unittestdevice2"
        seen = set()
        for _ in range(60):
            book.start(n, "res")
            seen.add(book.data[n]["run"]["country"])
            book.reset(n, force=True)
        self.assertEqual(seen, {"arcadia", "nova"}, "초기화 뒤 국가가 한쪽으로 고정됨")


class TestDisconnect(unittest.TestCase):
    def test_disconnect_cleans_up(self):
        import errlog
        before = errlog.summary()["server"]
        c = Client()
        c.join(lounge(), "AA")
        sid = next(k for k, v in webapp.CONNECTIONS.items() if v.get("nickname") == "AA")
        c.close()
        self.assertNotIn(sid, webapp.CONNECTIONS, "접속을 끊어도 연결 정보가 남음(접속 표시가 꺼지지 않음)")
        self.assertEqual(errlog.summary()["server"], before, "접속 끊김 때 서버 오류가 남")


class TestErrorLog(unittest.TestCase):
    def test_client_error_recorded_and_gm_only_summary(self):
        import errlog
        before = errlog.summary()["count"]
        r = Client()
        r.join(lounge(), "AA")
        r.emit("client_error", {"message": "TypeError: x is undefined", "src": "guest.html", "line": 10})
        self.assertEqual(errlog.summary()["count"], before + 1, "화면 오류가 기록되지 않음")
        self.assertFalse(names(r.emit("error_summary"), "error_summary"), "러너에게 오류 요약이 감")
        r.close()
        g = Client()
        g.join(lounge(), "GM", gm_password=PW)
        got = names(g.emit("error_summary"), "error_summary")
        self.assertTrue(got and got[-1]["count"] >= 1, "운영진이 오류 요약을 못 받음")
        g.close()

    def test_server_exception_caught(self):
        import errlog
        before = errlog.summary()["server"]

        @webapp.socketio.on("__test_boom")
        def _boom(data=None):
            raise RuntimeError("boom")
        c = Client()
        c.join(lounge(), "AA")
        rec = c.emit("__test_boom")
        self.assertEqual(errlog.summary()["server"], before + 1, "서버 오류가 기록되지 않음")
        self.assertTrue(names(rec, "action_error"), "서버 오류 때 안내가 가지 않음")
        c.close()


class TestBackup(unittest.TestCase):
    def test_backup_gm_only_and_now(self):
        import backup
        r = Client()
        r.join(lounge(), "AA")
        self.assertFalse(names(r.emit("backup_status"), "backup_status"), "러너에게 백업 상태가 감")
        before = backup.status()["count"]
        r.emit("backup_now")
        self.assertEqual(backup.status()["count"], before, "러너가 백업을 만들 수 있음")
        r.close()
        g = Client()
        g.join(lounge(), "GM", gm_password=PW)
        got = names(g.emit("backup_now"), "backup_status")
        self.assertTrue(got and got[-1]["count"] == before + 1, "운영진 '지금 백업'이 zip을 만들지 않음")
        self.assertTrue(got[-1]["last_size"] > 0)
        g.close()


class TestNotices(unittest.TestCase):
    def test_pinned_notices(self):
        import notices
        board = notices.NoticeBoard(path=os.path.join(os.getcwd(), "notices_test.json"))
        titles = [n["title"] for n in board.payload()]
        for t in ("제작 도구", "등급분류", "LOOP 이용 안내", "개인정보", "이용 수칙"):
            self.assertTrue(any(t in x for x in titles), f"고정 공지 '{t}'가 없음")


if __name__ == "__main__":
    unittest.main()
