# Test package for OneDragon-Helper

# 不在此处做 import 期 config_workflow()：包被 import 即写仓库 config/ 属隐式全局
# 副作用，且掩盖了「谁真的依赖生成物」。已实证源码测试对生成物
# （config.yml/schedule.yml/weekly.yml）零依赖——各读盘测试自建临时文件或 mock
# 路径。真依赖者自行显式补齐：test_cli（setUpModule）、
# exe/test_image_formats_exe（setUpModule，脚本根目录解析）。
