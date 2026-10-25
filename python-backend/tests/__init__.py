# Test package for OneDragon-Helper

# 不在此处做 import 期 config_workflow()：包被 import 即写仓库 config/ 属隐式全局
# 副作用，且掩盖了「谁真的依赖生成物」。已实证源码测试对生成物
# （config.yml/schedule.yml/weekly.yml）零依赖——各读盘测试自建临时文件或 mock
# 路径。CLI 测试从模板生成独立临时配置；打包图片测试使用固定解码夹具。

# 生成配置绊线：源码测试读取真实生成配置（本地存在、CI 缺失）时立即失败，
# 让此类违规在本地暴露而非拖到 CI。详见 support/config_tripwire.py。
from tests.support.config_tripwire import install as _install_config_tripwire

_install_config_tripwire()
