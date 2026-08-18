"""QML 脚本列表的 QAbstractListModel。

Qt 对动态列表的成熟做法：用 QAbstractListModel 替代 JS 数组/ QVariantList，
ListView 通过 beginMoveRows/endMoveRows/beginInsertRows 等信号**精确**响应
重排/增删，不依赖属性 notify 的数组比较——拖拽重排后 UI 一定刷新。

角色：
- displayName / char / color / scriptName
- 图标走 image://scripticon/<scriptName>：以 script_name 这个**稳定标识**为
  cache key（而非行 index），否则重排后行 index 不变、每格图标仍是启动时的旧图标。
"""
from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt


class GameListModel(QAbstractListModel):
    # 角色 id（Qt.UserRole 之后避免与内置角色冲突）
    DisplayNameRole = Qt.UserRole + 1
    CharRole = Qt.UserRole + 2
    ColorRole = Qt.UserRole + 3
    ScriptNameRole = Qt.UserRole + 4

    def __init__(self, games: list | None = None, parent=None):
        super().__init__(parent)
        self._games: list = list(games or [])

    # ── QAbstractListModel 接口 ─────────────────────────────────────────
    def rowCount(self, parent=None) -> int:
        if parent is None:
            parent = QModelIndex()
        if parent.isValid():
            return 0
        return len(self._games)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._games):
            return None
        game = self._games[index.row()]
        if role == self.DisplayNameRole:
            return game["display_name"]
        if role == self.CharRole:
            return game["char"]
        if role == self.ColorRole:
            return game["color"]
        if role == self.ScriptNameRole:
            return game["script_name"]
        if role == Qt.DisplayRole:
            return game["display_name"]
        return None

    def roleNames(self) -> dict:
        return {
            self.DisplayNameRole: b"displayName",
            self.CharRole: b"char",
            self.ColorRole: b"color",
            self.ScriptNameRole: b"scriptName",
        }

    # ── 数据同步接口（由 QmlBridge 调用）───────────────────────────────
    @property
    def games(self) -> list:
        """内部条目列表（只读；与 QmlBridge._games 保持一致）。"""
        return self._games

    def set_games(self, games: list):
        """整体重置（加载 config / 增删后重建）。beginResetModel 让 ListView 完全重建。"""
        self.beginResetModel()
        self._games = list(games)
        self.endResetModel()

    def move(self, src: int, dst: int):
        """重排：src 移到 dst 位置（ListView 精确刷新）。"""
        if src == dst or not (0 <= src < len(self._games) and 0 <= dst < len(self._games)):
            return
        self.beginMoveRows(
            QModelIndex(),
            src,
            src,
            QModelIndex(),
            dst + 1 if dst > src else dst,
        )
        game = self._games.pop(src)
        self._games.insert(dst, game)
        self.endMoveRows()

    def append(self, game: dict):
        """末尾追加（添加脚本）。"""
        row = len(self._games)
        self.beginInsertRows(QModelIndex(), row, row)
        self._games.append(game)
        self.endInsertRows()

    def pop(self, index: int) -> dict:
        """移除指定项（ListView 精确刷新）。"""
        if not (0 <= index < len(self._games)):
            raise IndexError(index)
        self.beginRemoveRows(QModelIndex(), index, index)
        game = self._games.pop(index)
        self.endRemoveRows()
        return game
