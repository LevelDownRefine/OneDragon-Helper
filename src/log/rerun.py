"""重跑：消费 monitor.parse_logs 产出的 rerun_list，对未正常退出的脚本二次运行。

依赖日志分析（``src.log.monitor.parse_logs``）先行产出 ``rerun_list``；本模块只负责
把名单里的脚本重新生成子链并以阻塞方式运行（等待重跑结束，便于后续邮件反映最终态）。
重跑由 ChainService 主流程（_rerun_round）调用，service 由调用方传入自身实例。
"""

import logging
from typing import TYPE_CHECKING

from src.config.subscript import get_script_name

if TYPE_CHECKING:
    from src.service.chain_service import ChainService

logger = logging.getLogger(__name__)


def rerun_failed(
    script_names: list[str],
    *,
    service: "ChainService",
    mute: bool = False,
) -> None:
    """对未正常退出的脚本重跑。

    复用 ``ChainService.run_chain_once``（生成+运行原子），以 ``chain_name="rerun"``
    生成仅含这些脚本的子链并阻塞运行（等到结束才返回），确保重跑在返回前完成，使后续
    邮件能反映重跑后的最终态。

    Args:
        script_names: 需重跑的脚本唯一标识（monitor 的 rerun_list）。
        service: 提供 ``load_config`` / ``run_chain_once`` 的服务实例
            （调用方必然传入自身，无惰性构造）。
        mute: 重跑期间是否静音（透传 ``--mute``）。
    """
    if not script_names:
        return
    all_config = service.load_config()
    known = {get_script_name(s) for s in all_config["script_list"]}
    keys = {n for n in script_names if n in known}
    if not keys:
        logger.warning("[rerun] rerun_list 中的脚本均不在 config，跳过重跑: %s", script_names)
        return
    logger.info("[rerun] 重跑 %d 个脚本: %s", len(keys), sorted(keys))
    # 复用 run_chain_once（生成+运行原子），阻塞等重跑结束，
    # 使后续邮件/关机基于重跑后的最终态。
    service.run_chain_once(keys, chain_name="rerun", mute=mute)
