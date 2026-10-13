# Conda 环境选择版验收

2026-09-10 更新。部署默认列出现有的非 base、已安装 Python 的 Conda 环境，用户按编号选择。另有 N 新建专用环境与 Q 取消选项；命令行可用 -EnvName 明确指定环境。

所有项目依赖检查、安装、索引准备及启动均使用 `conda run --prefix 所选环境 python ...`。启动器只接受 Conda 部署记录，不再自动选择 PATH Python 或旧 venv。已有环境可能按项目要求调整依赖，因此菜单会提醒共用环境的影响。

实际通过菜单选择现有 qwen 环境，部署成功；健康检查显示解释器为该环境的 python.exe。部署记录中的 environment_kind 为 conda。对照部署前后的 base conda-meta，166 个文件的名称与 SHA256 均未改变。

回归测试：23 passed，包含禁止指定 base、拒绝旧 venv 启动记录、迁移路径检查，以及原产品测试。已有环境选择与部署流程已实测；全新电脑安装 Miniconda、N 新建环境分支尚未在本轮实机执行。

上一版实际使用的是由 base Python 创建的独立 venv，并非将项目依赖装进 base。此次按用户要求改为明确选择 Conda 环境。旧 venv 保留，不自动删除，也不会再被新启动器使用。

日志位于本机 logs/deploy-20260910-214831.log；个人日志与 .runtime 不包含在交付包内。当前操作入口与参数以根目录 一键部署说明.md 为准，旧的 -Python/-UseExistingEnvironment 参数已移除。
