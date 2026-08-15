# -*- coding: utf-8 -*-
"""
gui.py
======
Tkinter 기반의 다크모드 GUI입니다.
화면은 세 단계로 구성됩니다.

    1) 캐릭터 데이터베이스 화면 (CharacterDBFrame)
    2) 팀 편성 화면 (TeamSetupFrame)
    3) 전투 화면 (BattleFrame)

이 파일은 화면 표시와 사용자 입력만 담당하며,
실제 규칙/계산은 battle.py, models.py, config.py 에 위임합니다.
"""

import random
import tkinter as tk
from tkinter import ttk, messagebox, colorchooser, simpledialog

import config
from battle import GameManager, BattleError


# ==========================================================================
# 색상 테마 (다크모드 / RPG 스타일)
# ==========================================================================
COLORS = {
    "bg": "#15171f",
    "bg_panel": "#1f232d",
    "bg_panel_alt": "#272c38",
    "bg_panel_alt2": "#2f3542",
    "border": "#3a4051",
    "text": "#e7e9ee",
    "text_dim": "#9aa0ae",
    "accent": "#c9a227",       # 골드 포인트
    "accent2": "#5b8def",      # 블루 포인트
    "team_a": "#e0663f",       # 1팀(레드 계열)
    "team_b": "#4593d1",       # 2팀(블루 계열)
    "hp_full": "#4caf50",
    "hp_mid": "#e0c341",
    "hp_low": "#e0473f",
    "danger": "#e0473f",
    "dead": "#5a5f6c",
    "fled": "#8a6bd1",
    "downed": "#ff8c42",
    "fleeing": "#c77dff",
    "btn_bg": "#333949",
    "btn_bg_hover": "#3f4759",
    "aggro": "#e08a2f",
}

FONT_TITLE = ("맑은 고딕", 21, "bold")
FONT_SUB = ("맑은 고딕", 13, "bold")
FONT_NORMAL = ("맑은 고딕", 10)
FONT_SMALL = ("맑은 고딕", 9)
FONT_TINY = ("맑은 고딕", 8)
FONT_LOG = ("Consolas", 10)
FONT_LOG_SMALL = ("Consolas", 9)


# ==========================================================================
# 공용 위젯 헬퍼
# ==========================================================================
def styled_button(parent, text, command, bg=None, fg=None, width=None, state="normal", font=None):
    btn = tk.Button(
        parent, text=text, command=command,
        bg=bg or COLORS["btn_bg"], fg=fg or COLORS["text"],
        activebackground=COLORS["btn_bg_hover"], activeforeground=COLORS["text"],
        disabledforeground=COLORS["text_dim"],
        relief="flat", bd=0, padx=10, pady=6, font=font or FONT_NORMAL,
        state=state, cursor="hand2" if state == "normal" else "arrow",
    )
    if width:
        btn.config(width=width)
    return btn


def show_copyable_message(parent, title, message, kind="error"):
    """오류/안내 메시지를 복사 가능한 형태로 보여주는 팝업."""
    top = tk.Toplevel(parent)
    top.title(title)
    top.configure(bg=COLORS["bg_panel"])
    top.geometry("420x260")
    top.transient(parent)
    top.grab_set()

    icon = "⚠" if kind == "error" else "ℹ"
    color = COLORS["danger"] if kind == "error" else COLORS["accent2"]

    tk.Label(top, text=f"{icon}  {title}", font=FONT_SUB, bg=COLORS["bg_panel"],
              fg=color).pack(pady=(14, 8), padx=16, anchor="w")

    text = tk.Text(top, bg=COLORS["bg_panel_alt"], fg=COLORS["text"], relief="flat",
                    font=FONT_NORMAL, wrap="word", padx=10, pady=10)
    text.insert("1.0", message)
    text.bind("<Key>", lambda e: "break")  # 타이핑으로 내용이 바뀌지 않도록(선택/복사는 가능)
    text.pack(padx=16, pady=(0, 10), fill="both", expand=True)

    def copy():
        top.clipboard_clear()
        top.clipboard_append(message)
        copy_btn.config(text="복사됨 ✓")
        top.after(1200, lambda: copy_btn.config(text="복사"))

    btn_row = tk.Frame(top, bg=COLORS["bg_panel"])
    btn_row.pack(pady=(0, 14), padx=16, fill="x")
    copy_btn = styled_button(btn_row, "복사", copy, bg=COLORS["btn_bg"])
    copy_btn.pack(side="left")
    styled_button(btn_row, "확인", top.destroy, bg=color).pack(side="right")


def show_error(parent, message):
    show_copyable_message(parent, "오류", message, kind="error")


class Tooltip:
    """위젯에 마우스를 올리면 텍스트를 보여주는 간단한 툴팁."""

    def __init__(self, widget, text: str):
        self.widget = widget
        self.text = text
        self.tip = None
        widget.bind("<Enter>", self.show)
        widget.bind("<Leave>", self.hide)

    def show(self, event=None):
        if self.tip or not self.text:
            return
        x = self.widget.winfo_rootx() + 16
        y = self.widget.winfo_rooty() + 20
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        tk.Label(
            self.tip, text=self.text, justify="left", bg=COLORS["bg_panel_alt2"],
            fg=COLORS["text"], relief="solid", borderwidth=1, font=FONT_SMALL, padx=8, pady=6,
        ).pack()

    def hide(self, event=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


class HPBar(tk.Canvas):
    """캔버스로 그리는 HP 게이지 위젯"""

    def __init__(self, parent, width=200, height=18, **kwargs):
        super().__init__(parent, width=width, height=height,
                          bg=COLORS["bg_panel_alt2"], highlightthickness=0, **kwargs)
        self.width = width
        self.height = height

    def draw(self, current, maximum, status="alive"):
        self.delete("all")
        ratio = 0 if maximum <= 0 else max(0, min(1, current / maximum))
        if status == "dead":
            color = COLORS["dead"]
        elif status == "fled":
            color = COLORS["fled"]
        elif status == "downed":
            color = COLORS["downed"]
        elif status == "fleeing":
            color = COLORS["fleeing"]
        elif ratio > 0.5:
            color = COLORS["hp_full"]
        elif ratio > 0.25:
            color = COLORS["hp_mid"]
        else:
            color = COLORS["hp_low"]

        self.create_rectangle(0, 0, self.width, self.height, fill=COLORS["bg_panel_alt2"], outline="")
        fill_w = int(self.width * ratio)
        if fill_w > 0:
            self.create_rectangle(0, 0, fill_w, self.height, fill=color, outline="")
        self.create_rectangle(0, 0, self.width, self.height, outline=COLORS["border"])

        if status == "dead":
            label = "사망"
        elif status == "fled":
            label = "도주 성공"
        elif status == "downed":
            label = f"{current} / {maximum} (빈사 - 마지막 기회)"
        elif status == "fleeing":
            label = f"{current} / {maximum} (도주 시도 중 - 무방비)"
        else:
            label = f"{current} / {maximum}"
        self.create_text(self.width // 2, self.height // 2, text=label,
                          fill=COLORS["text"], font=FONT_SMALL)


# 로그 태그별 색상/폰트 스타일
LOG_TAG_STYLE = {
    "round": {"foreground": COLORS["accent"], "font": ("맑은 고딕", 12, "bold"), "spacing1": 10, "spacing3": 4},
    "system": {"foreground": COLORS["accent2"], "font": ("맑은 고딕", 9, "italic")},
    "action": {"foreground": COLORS["text"], "font": ("맑은 고딕", 10, "bold"), "spacing1": 6},
    "defend": {"foreground": COLORS["accent2"], "font": ("맑은 고딕", 10, "bold"), "spacing1": 6},
    "taunt": {"foreground": COLORS["aggro"], "font": ("맑은 고딕", 10, "bold"), "spacing1": 6},
    "formula": {"foreground": COLORS["text_dim"], "font": FONT_LOG_SMALL},
    "crit": {"foreground": "#ffb02e", "font": ("맑은 고딕", 10, "bold")},
    "damage": {"foreground": COLORS["hp_low"], "font": ("맑은 고딕", 10, "bold")},
    "heal": {"foreground": COLORS["hp_full"], "font": ("맑은 고딕", 10, "bold")},
    "hp": {"foreground": COLORS["accent2"]},
    "summary": {"foreground": COLORS["text_dim"], "font": FONT_LOG_SMALL},
    "arrow": {"foreground": COLORS["text_dim"], "justify": "center"},
    "normal": {"foreground": COLORS["text"]},
}


def setup_log_tags(text_widget):
    for tag, style in LOG_TAG_STYLE.items():
        text_widget.tag_configure(tag, **style)


LOG_TAG_ICON = {
    "round": "▌ ", "crit": "✦ ", "damage": "⚔ ", "heal": "✚ ",
    "defend": "🛡 ", "taunt": "🎯 ",
    "system": "· ", "summary": "  - ",
}


def render_log(text_widget, log_entries):
    text_widget.config(state="normal")
    text_widget.delete("1.0", tk.END)
    for entry in log_entries:
        icon = LOG_TAG_ICON.get(entry["tag"], "")
        text_widget.insert(tk.END, icon + entry["text"] + "\n", entry["tag"])
    text_widget.see(tk.END)
    text_widget.config(state="disabled")


# ==========================================================================
# 메인 애플리케이션
# ==========================================================================
class Application(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PvP 전투 관리 프로그램")
        self.geometry("1360x840")
        self.configure(bg=COLORS["bg"])
        self.minsize(1180, 720)

        self.game = GameManager()

        self.container = tk.Frame(self, bg=COLORS["bg"])
        self.container.pack(fill="both", expand=True)

        self.current_frame = None
        self.show_db_frame()

    def _switch(self, frame_cls, *args):
        if self.current_frame is not None:
            self.current_frame.destroy()
        self.current_frame = frame_cls(self.container, self, *args)
        self.current_frame.pack(fill="both", expand=True)

    def show_db_frame(self):
        self._switch(CharacterDBFrame)

    def show_team_setup_frame(self):
        self._switch(TeamSetupFrame)

    def show_battle_frame(self, battle):
        self._switch(BattleFrame, battle)


# ==========================================================================
# ⚙ 전투 수식 설정 다이얼로그 (운영진 전용)
# ==========================================================================
class FormulaDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("전투 수식 설정 (운영진 전용)")
        self.configure(bg=COLORS["bg_panel"])
        self.geometry("620x680")
        self.transient(parent)
        self.grab_set()

        tk.Label(self, text="⚙ 전투 수식 설정 (운영진 전용)", font=FONT_SUB,
                  bg=COLORS["bg_panel"], fg=COLORS["accent"]).pack(pady=(14, 4), padx=16, anchor="w")
        tk.Label(
            self,
            text="현재 프로그램에 적용되어 있는 모든 전투 수식입니다. 숫자를 수정하고 '저장'을 누르면\n"
                 "이후 전투부터 즉시 반영되며 formulas.json에 저장되어 다음 실행 시에도 유지됩니다.",
            font=FONT_SMALL, bg=COLORS["bg_panel"], fg=COLORS["text_dim"], justify="left",
        ).pack(padx=16, pady=(0, 10), anchor="w")

        outer = tk.Frame(self, bg=COLORS["bg_panel"])
        outer.pack(fill="both", expand=True, padx=16)

        canvas = tk.Canvas(outer, bg=COLORS["bg_panel"], highlightthickness=0)
        scrollbar = tk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=COLORS["bg_panel"])
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.vars = {}
        for field in config.FORMULA_FIELDS:
            row = tk.Frame(inner, bg=COLORS["bg_panel_alt"], padx=10, pady=8)
            row.pack(fill="x", pady=3)
            left = tk.Frame(row, bg=COLORS["bg_panel_alt"])
            left.pack(side="left", fill="x", expand=True)
            tk.Label(left, text=field["label"], font=FONT_NORMAL, bg=COLORS["bg_panel_alt"],
                      fg=COLORS["text"]).pack(anchor="w")
            tk.Label(left, text=field["desc"], font=FONT_TINY, bg=COLORS["bg_panel_alt"],
                      fg=COLORS["text_dim"], wraplength=420, justify="left").pack(anchor="w")

            var = tk.StringVar(value=str(config.get_formula_value(field["key"])))
            self.vars[field["key"]] = var
            tk.Entry(row, textvariable=var, width=10, bg=COLORS["bg"], fg=COLORS["text"],
                      insertbackground=COLORS["text"], relief="flat", justify="center"
                      ).pack(side="right", ipady=4)

        btn_row = tk.Frame(self, bg=COLORS["bg_panel"])
        btn_row.pack(fill="x", pady=12, padx=16)
        styled_button(btn_row, "저장", self._on_save, bg=COLORS["accent"], fg="#1b1e26").pack(side="right")
        styled_button(btn_row, "닫기", self.destroy).pack(side="right", padx=8)

    def _on_save(self):
        values = {}
        for field in config.FORMULA_FIELDS:
            raw = self.vars[field["key"]].get().strip()
            try:
                values[field["key"]] = field["type"](raw)
            except ValueError:
                show_error(self, f"'{field['label']}' 값이 올바르지 않습니다: {raw}")
                return
        config.save_formula_overrides(values)
        messagebox.showinfo("저장 완료", "전투 수식이 저장되었습니다.\n이후 전투부터 즉시 적용됩니다.")
        self.destroy()


# ==========================================================================
# 1) 캐릭터 데이터베이스 화면
# ==========================================================================
class CharacterDBFrame(tk.Frame):
    def __init__(self, parent, app: Application):
        super().__init__(parent, bg=COLORS["bg"])
        self.app = app
        self.db = app.game.db
        self.selected_name = None

        self._build_header()
        self._build_body()
        self._refresh_list()

    # ------------------------------------------------------------------
    def _build_header(self):
        header = tk.Frame(self, bg=COLORS["bg"])
        header.pack(fill="x", padx=24, pady=(20, 10))

        tk.Label(header, text="캐릭터 데이터베이스", font=FONT_TITLE,
                 bg=COLORS["bg"], fg=COLORS["accent"]).pack(side="left")

        styled_button(header, "다음 : 팀 편성 →", self.app.show_team_setup_frame,
                      bg=COLORS["accent"], fg="#1b1e26", width=16).pack(side="right")
        styled_button(header, "⚙ 전투 수식 설정 (운영진 전용)", lambda: FormulaDialog(self),
                      bg=COLORS["btn_bg"]).pack(side="right", padx=8)
        styled_button(header, "🎲 더미 데이터 생성", self._on_generate_dummy,
                      bg=COLORS["btn_bg"]).pack(side="right", padx=8)

        tk.Label(header, text=f"(저장 위치: {self.db.path})", font=FONT_SMALL,
                  bg=COLORS["bg"], fg=COLORS["text_dim"]).pack(side="right", padx=12)

    def _build_body(self):
        body = tk.Frame(self, bg=COLORS["bg"])
        body.pack(fill="both", expand=True, padx=24, pady=(0, 20))

        # ---- 왼쪽 : 일괄 붙여넣기 ----
        left = tk.Frame(body, bg=COLORS["bg_panel"], padx=16, pady=16)
        left.pack(side="left", fill="both", expand=True, padx=(0, 12))

        tk.Label(left, text="붙여넣기로 일괄 등록", font=FONT_SUB,
                 bg=COLORS["bg_panel"], fg=COLORS["text"]).pack(anchor="w")
        tk.Label(
            left,
            text=f"예시)\n메이\n체력 2\n공격 3\n방어 1\n이능 3\n정신 2\n민첩 3\n행운 2\n"
                 f"(선택) 역할 탱커 / 딜러 / 힐러\n(선택) 색상 #5b8def\n\n"
                 f"※ 스탯 최대치 : 공격·방어 {config.STAT_CAPS['공격']}, 나머지 {config.STAT_CAPS['체력']} "
                 f"(초과 입력 시 자동으로 최대치로 조정됩니다)\n여러 명을 이어서 붙여넣을 수 있습니다.",
            font=FONT_SMALL, bg=COLORS["bg_panel"], fg=COLORS["text_dim"], justify="left",
        ).pack(anchor="w", pady=(4, 10))

        self.paste_text = tk.Text(
            left, height=15, bg=COLORS["bg_panel_alt"], fg=COLORS["text"],
            insertbackground=COLORS["text"], relief="flat", font=FONT_NORMAL, padx=8, pady=8,
        )
        self.paste_text.pack(fill="both", expand=True)

        styled_button(left, "일괄 등록", self._on_bulk_register,
                      bg=COLORS["accent2"], width=14).pack(anchor="e", pady=(10, 0))

        # ---- 오른쪽 : 등록된 캐릭터 목록 + 수정/삭제 ----
        right = tk.Frame(body, bg=COLORS["bg_panel"], padx=16, pady=16)
        right.pack(side="left", fill="both", expand=True, padx=(12, 0))

        tk.Label(right, text="등록된 캐릭터 (포지션순 : 탱커 → 딜러 → 힐러)", font=FONT_SUB,
                 bg=COLORS["bg_panel"], fg=COLORS["text"]).pack(anchor="w")

        list_frame = tk.Frame(right, bg=COLORS["bg_panel"])
        list_frame.pack(fill="both", expand=True, pady=(8, 10))

        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side="right", fill="y")

        self.listbox = tk.Listbox(
            list_frame, bg=COLORS["bg_panel_alt"], fg=COLORS["text"],
            selectbackground=COLORS["accent2"], relief="flat", font=FONT_NORMAL,
            yscrollcommand=scrollbar.set, activestyle="none", selectmode="extended",
        )
        self.listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.listbox.yview)
        self.listbox.bind("<<ListboxSelect>>", self._on_select)

        # ---- 편집 폼 ----
        form = tk.Frame(right, bg=COLORS["bg_panel"])
        form.pack(fill="x")

        tk.Label(form, text="이름", font=FONT_SMALL, bg=COLORS["bg_panel"],
                 fg=COLORS["text_dim"]).grid(row=0, column=0, sticky="w", pady=2)
        self.name_var = tk.StringVar()
        tk.Entry(form, textvariable=self.name_var, bg=COLORS["bg_panel_alt"],
                 fg=COLORS["text"], insertbackground=COLORS["text"], relief="flat"
                 ).grid(row=0, column=1, columnspan=3, sticky="ew", pady=2, ipady=3)

        tk.Label(form, text="역할", font=FONT_SMALL, bg=COLORS["bg_panel"],
                 fg=COLORS["text_dim"]).grid(row=1, column=0, sticky="w", pady=2)
        self.role_var = tk.StringVar(value=config.DEFAULT_ROLE)
        role_menu = ttk.Combobox(form, textvariable=self.role_var, values=config.ROLES,
                                  state="readonly", width=10)
        role_menu.grid(row=1, column=1, sticky="w", pady=2)

        tk.Label(form, text="색상", font=FONT_SMALL, bg=COLORS["bg_panel"],
                 fg=COLORS["text_dim"]).grid(row=1, column=2, sticky="w", pady=2)
        self.color_var = tk.StringVar(value="")
        color_cell = tk.Frame(form, bg=COLORS["bg_panel"])
        color_cell.grid(row=1, column=3, sticky="w", pady=2)
        self.color_swatch = tk.Label(color_cell, text="  ", bg=COLORS["bg_panel_alt"],
                                       relief="flat", width=3)
        self.color_swatch.pack(side="left", padx=(0, 4))
        styled_button(color_cell, "선택", self._on_pick_color, bg=COLORS["btn_bg"],
                      font=FONT_TINY).pack(side="left")
        styled_button(color_cell, "지움", self._on_clear_color, bg=COLORS["btn_bg"],
                      font=FONT_TINY).pack(side="left", padx=(4, 0))

        self.stat_vars = {}
        for i, stat in enumerate(config.STAT_KEYS):
            r = 2 + i // 2
            c = (i % 2) * 2
            cap = config.STAT_CAPS[stat]
            tk.Label(form, text=f"{stat} (0~{cap})", font=FONT_SMALL, bg=COLORS["bg_panel"],
                      fg=COLORS["text_dim"]).grid(row=r, column=c, sticky="w", pady=2)
            var = tk.StringVar(value="0")
            var.trace_add("write", self._update_total)
            self.stat_vars[stat] = var
            tk.Spinbox(form, from_=0, to=cap, textvariable=var, width=5, bg=COLORS["bg_panel_alt"],
                        fg=COLORS["text"], insertbackground=COLORS["text"], relief="flat", buttonbackground=COLORS["bg_panel_alt"]
                        ).grid(row=r, column=c + 1, sticky="w", pady=2, ipady=2)

        for c in range(4):
            form.grid_columnconfigure(c, weight=1)

        self.total_label = tk.Label(right, text="스탯 총합 : 0", font=FONT_SUB,
                                      bg=COLORS["bg_panel"], fg=COLORS["accent"])
        self.total_label.pack(anchor="w", pady=(8, 0))
        self._update_total()

        btn_row = tk.Frame(right, bg=COLORS["bg_panel"])
        btn_row.pack(fill="x", pady=(10, 0))
        styled_button(btn_row, "추가 / 수정 저장", self._on_save,
                      bg=COLORS["accent"], fg="#1b1e26").pack(side="left")
        styled_button(btn_row, "삭제", self._on_delete,
                      bg=COLORS["danger"]).pack(side="left", padx=8)
        styled_button(btn_row, "새로 작성", self._on_clear_form).pack(side="left")

        btn_row2 = tk.Frame(right, bg=COLORS["bg_panel"])
        btn_row2.pack(fill="x", pady=(6, 0))
        styled_button(btn_row2, "선택 삭제", self._on_delete_selected,
                      bg=COLORS["danger"], font=FONT_SMALL).pack(side="left")
        styled_button(btn_row2, "전체 삭제", self._on_delete_all,
                      bg=COLORS["danger"], font=FONT_SMALL).pack(side="left", padx=8)

    # ------------------------------------------------------------------
    def _update_total(self, *args):
        if not hasattr(self, "total_label"):
            return  # 위젯 생성 도중(총합 라벨이 아직 없을 때) 발생하는 이벤트는 무시
        total = 0
        for k in config.STAT_KEYS:
            var = self.stat_vars.get(k)
            if var is None:
                continue
            try:
                total += int(var.get() or 0)
            except ValueError:
                pass
        self.total_label.config(text=f"스탯 총합 : {total}")

    def _refresh_list(self):
        self.listbox.delete(0, tk.END)
        for name in self.db.all_names_by_position():
            data = self.db.get(name)
            total = config.stat_total(data["stats"])
            self.listbox.insert(tk.END, f"{name}   [{data['role']}]   총합 {total}")

    def _on_bulk_register(self):
        text = self.paste_text.get("1.0", tk.END)
        if not text.strip():
            messagebox.showwarning("알림", "붙여넣을 텍스트가 없습니다.")
            return
        registered, errors = self.db.parse_bulk_text(text)
        self._refresh_list()

        msg_parts = []
        if registered:
            msg_parts.append(f"등록 완료 ({len(registered)}명): " + ", ".join(registered))
        if errors:
            msg_parts.append("확인 필요:\n" + "\n".join(errors))
        if msg_parts:
            show_copyable_message(self, "일괄 등록 결과", "\n\n".join(msg_parts),
                                    kind="error" if not registered else "info")
        if registered:
            self.paste_text.delete("1.0", tk.END)

    def _on_select(self, event):
        sel = self.listbox.curselection()
        if not sel:
            return
        name = self.db.all_names_by_position()[sel[0]]
        data = self.db.get(name)
        self.selected_name = name
        self.name_var.set(name)
        self.role_var.set(data["role"])
        for k in config.STAT_KEYS:
            self.stat_vars[k].set(str(data["stats"].get(k, 0)))
        color = data.get("color") or ""
        self.color_var.set(color)
        self.color_swatch.config(bg=color if color else COLORS["bg_panel_alt"])

    def _on_pick_color(self):
        initial = self.color_var.get() or "#5b8def"
        result = colorchooser.askcolor(color=initial, title="캐릭터 색상 선택", parent=self)
        if result and result[1]:
            self.color_var.set(result[1])
            self.color_swatch.config(bg=result[1])

    def _on_clear_color(self):
        self.color_var.set("")
        self.color_swatch.config(bg=COLORS["bg_panel_alt"])

    def _on_save(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("알림", "이름을 입력해주세요.")
            return
        try:
            stats = {k: int(self.stat_vars[k].get() or 0) for k in config.STAT_KEYS}
        except ValueError:
            show_error(self, "스탯은 숫자로 입력해주세요.")
            return
        role = self.role_var.get()
        color = self.color_var.get().strip() or None
        warns = self.db.add_or_update(name, role, stats, color=color)
        self._refresh_list()
        msg = f"'{name}' 캐릭터가 저장되었습니다."
        if warns:
            msg += "\n\n" + "\n".join(warns)
        messagebox.showinfo("완료", msg)

    def _on_generate_dummy(self):
        count = simpledialog.askinteger(
            "더미 데이터 생성", "생성할 더미 캐릭터 수를 입력하세요.\n(이름 extra1, extra2... / 스탯·직군 무작위 자유 배분)",
            initialvalue=6, minvalue=1, maxvalue=200, parent=self,
        )
        if not count:
            return
        created = self.db.generate_dummy_characters(count)
        self._refresh_list()
        messagebox.showinfo("완료", f"더미 캐릭터 {len(created)}명이 생성되었습니다.\n" + ", ".join(created))

    def _on_delete_selected(self):
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showwarning("알림", "삭제할 캐릭터를 목록에서 선택해주세요. (Ctrl/Shift로 여러 명 선택 가능)")
            return
        all_names = self.db.all_names_by_position()
        names = [all_names[i] for i in sel]
        if messagebox.askyesno("선택 삭제 확인", f"선택한 {len(names)}명을 삭제하시겠습니까?\n" + ", ".join(names)):
            self.db.delete_many(names)
            self._refresh_list()
            self._on_clear_form()

    def _on_delete_all(self):
        if not self.db.all_names():
            messagebox.showinfo("알림", "등록된 캐릭터가 없습니다.")
            return
        if messagebox.askyesno("전체 삭제 확인", "등록된 캐릭터를 전부 삭제하시겠습니까? 이 작업은 되돌릴 수 없습니다."):
            count = self.db.delete_all()
            self._refresh_list()
            self._on_clear_form()
            messagebox.showinfo("완료", f"{count}명이 모두 삭제되었습니다.")

    def _on_delete(self):
        name = self.name_var.get().strip()
        if not name or not self.db.exists(name):
            messagebox.showwarning("알림", "삭제할 캐릭터를 목록에서 선택해주세요.")
            return
        if messagebox.askyesno("삭제 확인", f"'{name}' 캐릭터를 삭제하시겠습니까?"):
            self.db.delete(name)
            self._refresh_list()
            self._on_clear_form()

    def _on_clear_form(self):
        self.selected_name = None
        self.name_var.set("")
        self.role_var.set(config.DEFAULT_ROLE)
        for k in config.STAT_KEYS:
            self.stat_vars[k].set("0")
        self.color_var.set("")
        self.color_swatch.config(bg=COLORS["bg_panel_alt"])
        self.listbox.selection_clear(0, tk.END)


# ==========================================================================
# 2) 팀 편성 화면
# ==========================================================================
class TeamSetupFrame(tk.Frame):
    SLOTS = ["A", "B", "C"]

    def __init__(self, parent, app: Application):
        super().__init__(parent, bg=COLORS["bg"])
        self.app = app
        self.db = app.game.db

        self.entry_vars = {"1팀": {}, "2팀": {}}

        self._build_header()
        self._build_body()

    def _build_header(self):
        header = tk.Frame(self, bg=COLORS["bg"])
        header.pack(fill="x", padx=24, pady=(20, 4))

        styled_button(header, "← 데이터베이스로", self.app.show_db_frame).pack(side="left")
        tk.Label(header, text="팀 편성", font=FONT_TITLE,
                 bg=COLORS["bg"], fg=COLORS["accent"]).pack(side="left", padx=20)
        styled_button(header, "전투 시작 →", self._on_start,
                      bg=COLORS["accent"], fg="#1b1e26", width=14).pack(side="right")
        styled_button(header, "🎲 무작위 배치", self._on_random_assign,
                      bg=COLORS["btn_bg"]).pack(side="right", padx=8)

        tk.Label(
            self,
            text="※ 선공 팀은 두 팀의 민첩 합산으로 자동 결정됩니다 (동점일 경우 1d100).",
            font=FONT_SMALL, bg=COLORS["bg"], fg=COLORS["text_dim"],
        ).pack(anchor="w", padx=26, pady=(0, 6))

    def _build_team_block(self, parent, team_label, color):
        block = tk.Frame(parent, bg=COLORS["bg_panel"], padx=18, pady=18)
        tk.Label(block, text=team_label, font=FONT_TITLE, bg=COLORS["bg_panel"],
                  fg=color).pack(anchor="w", pady=(0, 10))

        names = self.db.all_names_by_position()

        for slot in self.SLOTS:
            row = tk.Frame(block, bg=COLORS["bg_panel"])
            row.pack(fill="x", pady=6)
            tk.Label(row, text=slot, font=FONT_SUB, width=3, bg=COLORS["bg_panel"],
                      fg=COLORS["text_dim"]).pack(side="left")
            var = tk.StringVar()
            self.entry_vars[team_label][slot] = var
            combo = ttk.Combobox(row, textvariable=var, values=names, state="readonly",
                                   font=FONT_NORMAL)
            combo.pack(side="left", fill="x", expand=True, ipady=4, padx=6)
        return block

    def _build_body(self):
        body = tk.Frame(self, bg=COLORS["bg"])
        body.pack(fill="both", expand=True, padx=24, pady=(0, 20))

        if not self.db.all_names():
            tk.Label(body, text="등록된 캐릭터가 없습니다. 먼저 데이터베이스 화면에서 캐릭터를 등록해주세요.",
                      font=FONT_NORMAL, bg=COLORS["bg"], fg=COLORS["danger"]).pack(pady=40)
            return

        team1 = self._build_team_block(body, "1팀", COLORS["team_a"])
        team1.pack(side="left", fill="both", expand=True, padx=(0, 12))

        team2 = self._build_team_block(body, "2팀", COLORS["team_b"])
        team2.pack(side="left", fill="both", expand=True, padx=(12, 0))

    def _on_random_assign(self):
        names = self.db.all_names()
        if len(names) < 6:
            messagebox.showwarning("알림", "무작위 배치를 하려면 최소 6명의 캐릭터가 등록되어 있어야 합니다.")
            return
        chosen = random.sample(names, 6)
        for i, slot in enumerate(self.SLOTS):
            self.entry_vars["1팀"][slot].set(chosen[i])
        for i, slot in enumerate(self.SLOTS):
            self.entry_vars["2팀"][slot].set(chosen[3 + i])

    def _on_start(self):
        names_1 = [self.entry_vars["1팀"][s].get().strip() for s in self.SLOTS]
        names_2 = [self.entry_vars["2팀"][s].get().strip() for s in self.SLOTS]

        if any(not n for n in names_1 + names_2):
            messagebox.showwarning("알림", "모든 칸에서 드롭다운으로 캐릭터를 선택해주세요.")
            return

        not_exist = [n for n in names_1 + names_2 if not self.db.exists(n)]
        if not_exist:
            show_error(self, "존재하지 않는 캐릭터입니다.\n" + ", ".join(sorted(set(not_exist))))
            return

        try:
            battle = self.app.game.start_battle(names_1, names_2)
        except BattleError as e:
            show_error(self, str(e))
            return

        explain = "\n".join(l["text"] for l in battle.operator_log if l["tag"] == "system")
        messagebox.showinfo("선공 결정", explain)

        self.app.show_battle_frame(battle)


# ==========================================================================
# 대상 선택 다이얼로그 (공격 / 힐 / 타인방어 대상 선택)
# ==========================================================================
class TargetDialog(tk.Toplevel):
    def __init__(self, parent, title, characters, on_pick):
        super().__init__(parent)
        self.title(title)
        self.configure(bg=COLORS["bg_panel"])
        self.geometry("320x380")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        tk.Label(self, text=title, font=FONT_SUB, bg=COLORS["bg_panel"],
                  fg=COLORS["text"]).pack(pady=(16, 8))

        list_frame = tk.Frame(self, bg=COLORS["bg_panel"])
        list_frame.pack(fill="both", expand=True, padx=16, pady=8)

        for c in characters:
            if not c.is_alive:
                hp_text = "사망/도주"
            elif c.status == "downed":
                hp_text = f"{c.current_hp}/{c.max_hp} (빈사)"
            else:
                hp_text = f"{c.current_hp}/{c.max_hp}"
            btn = styled_button(
                list_frame,
                f"{c.name}  ({c.role})  HP {hp_text}",
                lambda name=c.name: self._pick(name, on_pick),
                bg=COLORS["btn_bg"],
            )
            btn.pack(fill="x", pady=4)

        styled_button(self, "취소", self.destroy, bg=COLORS["bg_panel_alt"]).pack(pady=(4, 12))

    def _pick(self, name, on_pick):
        self.destroy()
        on_pick(name)


# ==========================================================================
# 3) 전투 화면
# ==========================================================================
class BattleFrame(tk.Frame):
    def __init__(self, parent, app: Application, battle):
        super().__init__(parent, bg=COLORS["bg"])
        self.app = app
        self.battle = battle

        # 라운드 타이머 상태
        self.time_left = config.ROUND_TIME_LIMIT_SECONDS
        self._last_round_seen = battle.round_no
        self._timeout_alerted = False

        self._build_header()
        self._build_body()
        self.refresh()
        self._tick()

    # ------------------------------------------------------------------
    def _build_header(self):
        header = tk.Frame(self, bg=COLORS["bg"])
        header.pack(fill="x", padx=20, pady=(14, 4))

        self.turn_label = tk.Label(header, text="", font=FONT_TITLE,
                                     bg=COLORS["bg"], fg=COLORS["accent"])
        self.turn_label.pack(side="left")

        self.timer_label = tk.Label(header, text="", font=("맑은 고딕", 16, "bold"),
                                      bg=COLORS["bg"], fg=COLORS["text"])
        self.timer_label.pack(side="left", padx=24)

        styled_button(header, "다음 턴 →", self._on_next_turn,
                      bg=COLORS["accent2"], width=12).pack(side="right")
        styled_button(header, "↩ 행동 취소", self._on_undo,
                      bg=COLORS["danger"]).pack(side="right", padx=8)
        styled_button(header, "새 전투 (팀 편성으로)", self.app.show_team_setup_frame,
                      bg=COLORS["btn_bg"]).pack(side="right", padx=8)

    def _build_body(self):
        body = tk.Frame(self, bg=COLORS["bg"])
        body.pack(fill="both", expand=True, padx=20, pady=(4, 16))

        # 왼쪽 : 1팀
        self.panel_a = tk.Frame(body, bg=COLORS["bg_panel"], padx=14, pady=14, width=330)
        self.panel_a.pack(side="left", fill="y")
        self.panel_a.pack_propagate(False)

        # 가운데 : 로그 (운영진용 / 러너 공유용 2단)
        center = tk.Frame(body, bg=COLORS["bg"])
        center.pack(side="left", fill="both", expand=True, padx=12)

        self.pub_log_text, self.pub_copy_btn = self._build_log_panel(
            center, "📋 러너 공유 로그 (결과만)", top=True, log_kind="public",
        )
        self.op_log_text, self.op_copy_btn = self._build_log_panel(
            center, "🛠 운영진 로그 (모든 수식 표시)", top=False, log_kind="operator", collapsible=True,
        )

        # 오른쪽 : 2팀
        self.panel_b = tk.Frame(body, bg=COLORS["bg_panel"], padx=14, pady=14, width=330)
        self.panel_b.pack(side="right", fill="y")
        self.panel_b.pack_propagate(False)

    def _build_log_panel(self, parent, title, top, log_kind, collapsible=False):
        wrap = tk.Frame(parent, bg=COLORS["bg_panel"], padx=12, pady=10)
        wrap.pack(fill="both", expand=True, pady=(0, 10) if top else (0, 0))

        head = tk.Frame(wrap, bg=COLORS["bg_panel"])
        head.pack(fill="x")

        toggle_btn = None
        if collapsible:
            toggle_btn = styled_button(head, "▼", lambda: None, bg=COLORS["btn_bg"], font=FONT_SMALL)
            toggle_btn.pack(side="left", padx=(0, 6))

        tk.Label(head, text=title, font=FONT_SUB, bg=COLORS["bg_panel"],
                  fg=COLORS["text"]).pack(side="left")
        copy_btn = styled_button(head, "현재 턴 복사", lambda: None, bg=COLORS["btn_bg"], font=FONT_SMALL)
        copy_btn.pack(side="right")

        log_frame = tk.Frame(wrap, bg=COLORS["bg_panel"])
        log_frame.pack(fill="both", expand=True, pady=(8, 0))
        scrollbar = tk.Scrollbar(log_frame)
        scrollbar.pack(side="right", fill="y")
        text = tk.Text(
            log_frame, bg=COLORS["bg_panel_alt"], fg=COLORS["text"], relief="flat",
            font=FONT_LOG, state="disabled", yscrollcommand=scrollbar.set, wrap="word",
            padx=10, pady=8,
        )
        text.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=text.yview)
        setup_log_tags(text)

        if collapsible:
            state = {"collapsed": False}

            def toggle():
                if state["collapsed"]:
                    log_frame.pack(fill="both", expand=True, pady=(8, 0))
                    wrap.pack_configure(fill="both", expand=True)
                    toggle_btn.config(text="▼")
                else:
                    log_frame.pack_forget()
                    wrap.pack_configure(fill="x", expand=False)
                    toggle_btn.config(text="▶")
                state["collapsed"] = not state["collapsed"]

            toggle_btn.config(command=toggle)

        def do_copy():
            # 요청 2 : 전체 로그가 아니라 "현재 턴"에 해당하는 구간만 복사합니다.
            if log_kind == "operator":
                entries = self.battle.operator_log[self.battle.turn_op_start:]
            else:
                entries = self.battle.public_log[self.battle.turn_pub_start:]
            # 화면에 표시되는 것과 동일하게, 태그별 아이콘도 함께 포함해서 복사합니다.
            lines = [LOG_TAG_ICON.get(e["tag"], "") + e["text"] for e in entries]
            content = "\n".join(lines).strip()
            self.clipboard_clear()
            self.clipboard_append(content)
            copy_btn.config(text="복사됨 ✓")
            self.after(1200, lambda: copy_btn.config(text="현재 턴 복사"))

        copy_btn.config(command=do_copy)
        return text, copy_btn

    # ------------------------------------------------------------------
    def _build_team_panel(self, panel, team_label, color):
        for w in panel.winfo_children():
            w.destroy()

        tk.Label(panel, text=team_label, font=FONT_TITLE, bg=COLORS["bg_panel"],
                  fg=color).pack(anchor="w", pady=(0, 10))

        members = self.battle.team_members(team_label)
        is_current_team = self.battle.current_turn_team == team_label
        is_forced_team = (
            self.battle.forced_target is not None
            and self.battle.forced_target_team == team_label
        )

        for c in members:
            row = tk.Frame(panel, bg=COLORS["bg_panel_alt"], padx=10, pady=8)
            row.pack(fill="x", pady=6)

            # 이름 줄
            name_row = tk.Frame(row, bg=COLORS["bg_panel_alt"])
            name_row.pack(fill="x")
            if getattr(c, "color", None):
                tk.Label(name_row, text="●", font=FONT_SUB, bg=COLORS["bg_panel_alt"],
                          fg=c.color).pack(side="left")
            name_color = {
                "dead": COLORS["dead"], "fled": COLORS["fled"], "downed": COLORS["downed"],
                "fleeing": COLORS["fleeing"],
            }.get(c.status, COLORS["text"])
            tk.Label(name_row, text=c.name, font=FONT_SUB,
                      bg=COLORS["bg_panel_alt"], fg=name_color).pack(side="left")
            tk.Label(name_row, text=f" [{c.role}]", font=FONT_SMALL,
                      bg=COLORS["bg_panel_alt"], fg=COLORS["text_dim"]).pack(side="left")

            info_icon = tk.Label(name_row, text=" ⓘ", font=FONT_SMALL,
                                   bg=COLORS["bg_panel_alt"], fg=COLORS["accent2"], cursor="question_arrow")
            info_icon.pack(side="left")
            stat_lines = "\n".join(f"{k} {v}" for k, v in c.stats.items())
            Tooltip(info_icon, f"{c.name}  [{c.role}]\n{stat_lines}\n총합 {c.stat_total}")

            if c.status == "downed":
                tk.Label(name_row, text=" ☠ 빈사", font=FONT_SMALL,
                          bg=COLORS["bg_panel_alt"], fg=COLORS["downed"]).pack(side="left")
            if self.battle.forced_target is c:
                tk.Label(name_row, text=f" 🎯 어그로×{self.battle.forced_target_count}", font=FONT_SMALL,
                          bg=COLORS["bg_panel_alt"], fg=COLORS["aggro"]).pack(side="left")
            total_shields = len(c.defense_grants) + c.aggro_defense_credits
            if total_shields:
                tk.Label(name_row, text=f" 🛡×{total_shields}", font=FONT_SMALL,
                          bg=COLORS["bg_panel_alt"], fg=COLORS["accent2"]).pack(side="left")
            if c.dodging_this_round:
                tk.Label(name_row, text=" 🌀회피", font=FONT_SMALL,
                          bg=COLORS["bg_panel_alt"], fg=COLORS["accent2"]).pack(side="left")
            if c.has_acted and c.is_alive:
                tk.Label(name_row, text=" ✔", font=FONT_SMALL,
                          bg=COLORS["bg_panel_alt"], fg=COLORS["hp_full"]).pack(side="right")

            # 강제 대상(어그로) 경고
            if is_forced_team and self.battle.forced_target is c:
                tk.Label(row, text=f"⚠ 상대의 다음 공격 {self.battle.forced_target_count}회가 강제되는 대상입니다",
                          font=FONT_TINY, bg=COLORS["bg_panel_alt"], fg=COLORS["danger"]).pack(anchor="w")
            if c.protecting_ally:
                tk.Label(row, text=f"🛡 {c.protecting_ally} 방어 중", font=FONT_TINY,
                          bg=COLORS["bg_panel_alt"], fg=COLORS["accent2"]).pack(anchor="w")
            if c.pending_attacks:
                tk.Label(row, text=f"⏳ 대기 중인 공격 {len(c.pending_attacks)}건 (자신의 턴에 정산됩니다)",
                          font=FONT_TINY, bg=COLORS["bg_panel_alt"], fg=COLORS["danger"]).pack(anchor="w")
            if c.role == config.ROLE_HEALER and not c.has_acted and c.is_alive:
                tk.Label(row, text="✳ 힐러는 상대의 후공 턴으로 행동을 미룰 수 있습니다", font=FONT_TINY,
                          bg=COLORS["bg_panel_alt"], fg=COLORS["text_dim"]).pack(anchor="w")

            bar = HPBar(row, width=270, height=16)
            bar.pack(fill="x", pady=(6, 6))
            bar.draw(c.current_hp, c.max_hp, c.status)

            # 힐러라도 '힐' 이외의 행동은 자기 팀 턴에서만 가능합니다.
            can_act = is_current_team and c.is_alive and not c.has_acted
            is_second_phase = self.battle.current_turn_team != self.battle.round_first_team
            can_heal = (
                c.is_alive and not c.has_acted
                and (is_current_team or (c.acts_on_any_turn() and is_second_phase))
            )
            actions = set(c.available_actions())

            primary_row = tk.Frame(row, bg=COLORS["bg_panel_alt"])
            primary_row.pack(fill="x")

            if config.ACTION_ATTACK in actions:
                self._make_action_btn(primary_row, "공격", can_act, COLORS["danger"],
                                        lambda ch=c: self._on_attack(ch))
            if config.ACTION_SELF_DEFEND in actions:
                self._make_action_btn(primary_row, "본인방어", can_act, COLORS["accent2"],
                                        lambda ch=c: self._on_self_defend(ch))
            if config.ACTION_DEFEND in actions:
                self._make_action_btn(primary_row, "방어", can_act, COLORS["accent2"],
                                        lambda ch=c: self._on_defend(ch))
            if config.ACTION_TAUNT in actions:
                self._make_action_btn(primary_row, "공격유도", can_act, COLORS["aggro"],
                                        lambda ch=c: self._on_taunt(ch))
            if config.ACTION_DODGE in actions:
                self._make_action_btn(primary_row, "회피", can_act, COLORS["accent2"],
                                        lambda ch=c: self._on_dodge(ch))
            if config.ACTION_HEAL in actions:
                self._make_action_btn(primary_row, "힐", can_heal, COLORS["hp_full"],
                                        lambda ch=c: self._on_heal(ch))

            secondary_row = tk.Frame(row, bg=COLORS["bg_panel_alt"])
            secondary_row.pack(fill="x", pady=(4, 0))
            self._make_action_btn(secondary_row, "시간 초과", can_act, COLORS["btn_bg"],
                                    lambda ch=c: self._on_timeout(ch), font=FONT_TINY)
            self._make_action_btn(secondary_row, "도주", can_act, COLORS["btn_bg"],
                                    lambda ch=c: self._on_flee(ch), font=FONT_TINY)

    def _make_action_btn(self, parent, text, enabled, color, command, font=None):
        btn = styled_button(
            parent, text, command,
            bg=color if enabled else COLORS["btn_bg"],
            state="normal" if enabled else "disabled",
            font=font or FONT_NORMAL,
        )
        btn.pack(side="left", padx=2, fill="x", expand=True)
        return btn

    # ------------------------------------------------------------------
    def refresh(self):
        self.turn_label.config(text=f"현재 턴 : {self.battle.current_turn_label()}")
        self._build_team_panel(self.panel_a, self.battle.TEAM_A, COLORS["team_a"])
        self._build_team_panel(self.panel_b, self.battle.TEAM_B, COLORS["team_b"])
        render_log(self.op_log_text, self.battle.operator_log)
        render_log(self.pub_log_text, self.battle.public_log)

        if self.battle.finished:
            self._show_result_once()

    _result_shown = False

    def _show_result_once(self):
        if self._result_shown:
            return
        self._result_shown = True
        if self.battle.winner:
            messagebox.showinfo("전투 종료", f"{self.battle.winner}이(가) 승리했습니다!")
        else:
            messagebox.showinfo("전투 종료", "무승부입니다.")

    # ------------------------------------------------------------------
    # 라운드 타이머
    # ------------------------------------------------------------------
    def _tick(self):
        if not self.winfo_exists():
            return

        if self.battle.round_no != self._last_round_seen:
            self._last_round_seen = self.battle.round_no
            self.time_left = config.ROUND_TIME_LIMIT_SECONDS
            self._timeout_alerted = False

        if not self.battle.finished:
            self.time_left = max(0, self.time_left - 1)
            if self.time_left == 0 and not self._timeout_alerted:
                self._timeout_alerted = True
                messagebox.showwarning(
                    "라운드 제한시간 초과",
                    "이번 라운드 제한시간(5분)이 지났습니다.\n"
                    "아직 행동하지 않은 캐릭터는 '시간 초과' 처리해주세요.",
                )

        mins, secs = divmod(self.time_left, 60)
        color = COLORS["danger"] if self.time_left <= 30 else COLORS["text"]
        self.timer_label.config(text=f"⏱ {mins:02d}:{secs:02d}", fg=color)
        self.after(1000, self._tick)

    # ------------------------------------------------------------------
    # 행동 콜백
    # ------------------------------------------------------------------
    def _on_attack(self, attacker):
        own_label = self.battle.team_label_of(attacker)
        enemy_label = self.battle.enemy_team_label(own_label)
        targets = [c for c in self.battle.team_members(enemy_label) if c.is_alive]
        if not targets:
            show_error(self, "대상이 존재하지 않습니다.")
            return

        def pick(target_name):
            try:
                self.battle.perform_attack(attacker.name, target_name)
            except BattleError as e:
                show_error(self, str(e))
            self.refresh()

        TargetDialog(self, f"{attacker.name}의 공격 대상 선택", targets, pick)

    def _on_self_defend(self, actor):
        try:
            self.battle.perform_self_defend(actor.name)
        except BattleError as e:
            show_error(self, str(e))
        self.refresh()

    def _on_defend(self, tanker):
        own_label = self.battle.team_label_of(tanker)
        targets = [c for c in self.battle.team_members(own_label) if c.is_alive]
        if not targets:
            show_error(self, "대상이 존재하지 않습니다.")
            return

        def pick(target_name):
            try:
                self.battle.perform_defend(tanker.name, target_name)
            except BattleError as e:
                show_error(self, str(e))
            self.refresh()

        TargetDialog(self, f"{tanker.name}의 방어 대상 선택 (본인 또는 아군)", targets, pick)

    def _on_taunt(self, tanker):
        own_label = self.battle.team_label_of(tanker)
        targets = [c for c in self.battle.team_members(own_label) if c.is_alive]
        if not targets:
            show_error(self, "대상이 존재하지 않습니다.")
            return

        def pick(target_name):
            try:
                self.battle.perform_taunt(tanker.name, target_name)
            except BattleError as e:
                show_error(self, str(e))
            self.refresh()

        TargetDialog(self, f"{tanker.name}의 공격유도 대상 선택 (본인 또는 아군)", targets, pick)

    def _on_dodge(self, actor):
        try:
            self.battle.perform_dodge(actor.name)
        except BattleError as e:
            show_error(self, str(e))
        self.refresh()

    def _on_heal(self, healer):
        own_label = self.battle.team_label_of(healer)
        targets = [c for c in self.battle.team_members(own_label) if c.is_alive]
        if not targets:
            show_error(self, "대상이 존재하지 않습니다.")
            return

        def pick(target_name):
            try:
                self.battle.perform_heal(healer.name, target_name)
            except BattleError as e:
                show_error(self, str(e))
            self.refresh()

        TargetDialog(self, f"{healer.name}의 회복 대상 선택", targets, pick)

    def _on_timeout(self, actor):
        if not messagebox.askyesno("확인", f"{actor.name}을(를) 시간 초과 처리하시겠습니까?"):
            return
        try:
            self.battle.perform_timeout(actor.name)
        except BattleError as e:
            show_error(self, str(e))
        self.refresh()

    def _on_flee(self, actor):
        if not messagebox.askyesno("확인", f"{actor.name}을(를) 도주 처리하시겠습니까?\n(이후 전투에 참여할 수 없습니다)"):
            return
        try:
            self.battle.perform_flee(actor.name)
        except BattleError as e:
            show_error(self, str(e))
        self.refresh()

    def _on_next_turn(self):
        try:
            self.battle.advance_turn()
        except BattleError as e:
            show_error(self, str(e))
        self.refresh()

    def _on_undo(self):
        try:
            self.battle.undo_last()
        except BattleError as e:
            show_error(self, str(e))
        self.refresh()
