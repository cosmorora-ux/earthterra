# -*- coding: utf-8 -*-
"""
main.py
=======
프로그램 실행 진입점입니다.
    python main.py
로 실행합니다.
"""

from gui import Application


def main():
    app = Application()
    app.mainloop()


if __name__ == "__main__":
    main()
