"""卡牌内容包：七类卡牌定义的统一入口。

包化整合（2026-10-07）：原先 sts/content/ 下平铺的 cards.py /
silent_cards.py / defect_cards.py / watcher_cards.py / colorless_cards.py /
curses_cards.py 收拢为本包，按类别一文件一模块（七文件，含 _base 公共层）：

- ``_base.py``     CardDef 不可变模板 + 跨职业共享私有助手（_strike_play 等）
- ``ironclad.py``  铁甲战士
- ``silent.py``    静默
- ``defect.py``    故障
- ``watcher.py``   观者
- ``colorless.py`` 无色卡 35 张（含 Hand of Greed）
- ``curses.py``    诅咒
- ``status.py``    状态卡（WOUND/BURN/DAZED/SLIMED/VOID，中立卡）

对外接口 = 本包根命名空间：``from sts.content.cards import SHIV``、
``from sts.content import cards`` 等用法与包化前的平铺 cards.py 完全
一致（原 __getattr__ 惰性 re-export 兜底被此处的 eager re-export 取代，
任意导入顺序均可用）。旧 ``sts.content.silent_cards`` 等子模块路径已
删除，引用一律改指包根或本包子模块。
"""

from __future__ import annotations

from sts.content.cards._base import (
    CardDef,
    _defend_play,
    _exhaust_from_hand,
    _strike_play,
    _upgrade_in_place,
)
from sts.content.cards.ironclad import _STRIKE_CARD_NAMES
from sts.content.cards.ironclad import *  # noqa: F401,F403
from sts.content.cards.curses import *  # noqa: F401,F403
from sts.content.cards.colorless import *  # noqa: F401,F403
from sts.content.cards.silent import *  # noqa: F401,F403
from sts.content.cards.watcher import *  # noqa: F401,F403
from sts.content.cards.defect import *  # noqa: F401,F403
from sts.content.cards.status import *  # noqa: F401,F403
