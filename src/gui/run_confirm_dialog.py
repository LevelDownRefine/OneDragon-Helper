"""「启动全部」前的运行确认弹窗（RunConfirmDialog）。

按生命周期三段组织（单列纵向，与原「运行前动作」一张 group 含多个 checkbox 行的
风格一致）：运行前配置（关闭残留进程 / 静音）· 运行中配置（重跑）·
运行后配置（邮件通知 / 开启声音 / 自动关机）。运行选项的勾选控件统一由
:class:`src.gui.run_options_editor.RunOptionsEditor` 提供，本弹窗只负责标题、
底部按钮与确认收集。

对外接口：
- ``RunConfirmDialog``：运行确认弹窗，构造签名含 enabled_count 与
  ``RunOptions``（初始勾选值，经 AppService.load_run_options 取自 schedule.yml），
  ``run_options`` 返回用户改后的 ``RunOptions``；取消（reject）不返回、不落盘。
"""

from PySide6.QtWidgets import QLabel, QVBoxLayout

from src.gui.dialogs import TEXT, FormDialogBase, make_font
from src.gui.run_options_editor import RunOptionsEditor
from src.service.schedule import RunOptions


class RunConfirmDialog(FormDialogBase):
    """「启动全部」前的确认弹窗，按生命周期三段（运行前/中/后配置）排列七项勾选。

    复用 ``FormDialogBase`` 的样式与控件构造；accept 后经 ``run_options`` 属性返回
    勾选项，写盘由调用方经 ``AppService.save_schedule`` 委托 ``src.service.schedule.save_schedule``
    （写 schedule.yml）。取消（reject）不返回、不落盘。
    """

    def __init__(
        self,
        enabled_count: int,
        options: RunOptions,
        parent=None,
        *,
        settings_only: bool = False,
    ):
        super().__init__(parent)
        self.settings_only = settings_only
        self.setWindowTitle("运行选项" if settings_only else "确认运行")

        self._run_options = None  # accept 后供调用方读取勾选项

        self.setMinimumWidth(400)
        self.init_ui(options, enabled_count)

    def init_ui(self, options: RunOptions, enabled_count: int) -> None:
        """构造布局：确认文案 + 运行选项编辑器（三段生命周期配置）+ 底部按钮行。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        hint = QLabel(
            "保存后用于每日计划、自动启动和手动运行"
            if self.settings_only
            else f"即将运行 {enabled_count} 个脚本，是否继续？"
        )
        hint.setFont(make_font(size=11, bold=True))
        hint.setStyleSheet(f"color: {TEXT}; background: transparent;")
        layout.addWidget(hint)

        self.editor = RunOptionsEditor(options)
        layout.addWidget(self.editor)

        layout.addStretch()
        layout.addLayout(
            self._make_footer(
                "保存" if self.settings_only else "确认运行",
                self._on_accept,
                left_widgets=(),
            )
        )

    @property
    def run_options(self) -> RunOptions | None:
        """accept 后的勾选项（RunOptions）；取消时返回 None。

        避免遮蔽 QDialog.result()（基类结果码方法）。"""
        return self._run_options

    def _on_accept(self) -> None:
        """确认运行：收集勾选项并 accept。"""
        self._run_options = self.editor.run_options
        self.accept()
