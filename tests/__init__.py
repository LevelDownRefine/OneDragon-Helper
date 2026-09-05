# Test package for OneDragon-Helper

from src.config.generate_config import config_workflow

# 测试前复刻首启产物：运行时首次启动由 config_workflow() 自动从模板生成
# config.yml / schedule.yml / weekly.yml 并对齐各脚本 config；CI / 测试环境不跑
# GUI，不会生成这些文件。读取它们的测试在缺失时会断言崩溃，故在此补齐，
# 避免『本地有、CI 无』的绿红不一致。复刻首启语义而非简单拷贝，对齐更彻底。
config_workflow()
