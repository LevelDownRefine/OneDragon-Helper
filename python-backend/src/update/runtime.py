"""助手启动闸门，绑定当前应用的进程和包规则。"""

from functools import partial

from updater.runtime import application_lease as core_application_lease

from src.update.policy import POLICY

application_lease = partial(core_application_lease, policy=POLICY)
