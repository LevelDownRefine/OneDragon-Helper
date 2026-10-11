"""发布工具和助手共用的包接口，绑定助手发布规则。"""

from functools import partial

from updater import package

from src.update.policy import POLICY

managed_path = partial(package.managed_path, policy=POLICY)
safe_target = partial(package.safe_target, policy=POLICY)
manifest_frontend = partial(package.manifest_frontend, policy=POLICY)
parse_manifest = partial(package.parse_manifest, policy=POLICY)
verify_installation = partial(package.verify_installation, policy=POLICY)
load_manifest = partial(package.load_manifest, policy=POLICY)
write_manifest = partial(package.write_manifest, policy=POLICY)
unpack_package = partial(package.unpack_package, policy=POLICY)
