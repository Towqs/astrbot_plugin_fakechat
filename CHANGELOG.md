# 更新日志

## v0.5.6
- 修复 /sadstory_aistyle 和 /sadstory_aitpl 报错 AttributeError: get_registered_star_tools_manager
- 改用 llm_generate 直接生成+解析 JSON，不再依赖已废弃的 func_tools_mgr 参数
- 移除不再需要的 @filter.llm_tool() 方法（llm_add_writing_style、llm_add_story_template）

## v0.5.5
- 统一模板管理：templates/ 目录下的文件模板在初始化时自动导入数据库，所有模板统一通过数据库管理
- 修复 /sadstory_usetpl 无法操作文件模板的问题（文件模板现在也能启用/禁用）
- 修复 /sadstory_listtpl 显示序号与实际 ID 不一致导致用户操作失败的问题
- 简化模板列表显示：去掉混乱的双编号，统一使用数据库 ID
- 简化 /sadstory_deltpl：统一用数据库 ID 删除，不再需要区分文件名和 ID

## v0.5.4
- 修复 WebUI 配置导入：改用 AstrBotConfig 参数接收配置，导入后 save_config() 持久化
- 清理所有用户可见文案中的"故事"字样，统一为"伪装聊天"
- 更新 _conf_schema.json 所有 hint 描述

## v0.5.3
- 修复 WebUI 配置导入：改用 AstrBotConfig 参数接收配置（而非 context.get_config）
- 导入后调用 save_config() 持久化清空操作
- 修复配置读取使用内存缓存而非实时数据的问题

## v0.5.2
- 新增 WebUI 导入调试日志，排查 template_list 数据格式问题
- 修复 metadata.yaml 版本号与 main.py 不一致的问题
- 全局重命名：「伤感故事」→「伪装聊天」

## v0.4.3
- 修复共享状态并发风险：`_generate_story` 中对用户池使用拷贝，避免 shuffle 污染原始列表
- 修复 bystander fallback：未知 speaker 回退到主角而非 random.choice(bystanders)，避免空列表异常
- 修复冷却并发绕过：通过检查后立即预占冷却，防止并发请求同时通过
- 修复虚拟用户模式与素材群拉取冲突：虚拟模式下跳过所有群成员拉取
- 新增主题长度限制：用户输入主题截断至100字，防止 token 滥用

## v0.4.1
- WebUI 支持通过 template_list 添加写作风格和故事模板（保存后自动导入数据库）
- 每次触发 /sadstory 时自动检查并导入 WebUI 新数据
- _reload_config 保持同步，WebUI 导入逻辑独立为 async 方法

## v0.4.0
- 写作风格和故事模板改用 SQLite 数据库存储，彻底绕开 WebUI template_list 的兼容性问题
- 新增 /sadstory_delstyle 指令：删除写作风格
- 所有风格/模板操作永久生效，不再是"仅本次运行"
- 从 _conf_schema.json 移除 template_list 字段，避免格式校验冲突
- 新增 db.py 数据库模块
- 新增 aiosqlite 依赖

## v0.3.7
- 修复 template_list 旧数据冲突：字段名改为 writing_styles / story_refs，避免旧字符串数据导致校验失败

## v0.3.6
- 新增 `/sadstory_config` 指令：一次性查看所有配置状态（参数、角色、写作风格、故事模板）
- 修复 `/sadstory_usestyle` 和 `/sadstory_usetpl` 切换状态后被 reload 覆盖的 bug

## v0.3.5
- 优化 WebUI 配置体验：写作风格和故事模板改用 template_list 类型，每个字段独立显示，不再需要手写「名字|是|内容」格式
- 数字配置（冷却时间、消息条数、网友数量）全部加滑块
- 配置项重新排序，描述文案更口语化
- 兼容旧格式配置数据

## v0.3.4
- 新增 Prompt 风格模板管理系统：LLM prompt（口语化/文学风格等）可在 WebUI 后台直接查看和编辑
- 预置口语化、文学两个默认 prompt 风格模板，开箱即用
- 支持多风格共存：生成故事时从已启用的风格中随机选取
- 新增 `/sadstory_style` 命令：查看当前所有生成参数和 prompt 风格列表
- 新增 `/sadstory_addstyle` 命令：在群内添加新的 prompt 风格
- 新增 `/sadstory_usestyle 序号` 命令：切换 prompt 风格的启用/禁用状态
- prompt 模板支持变量占位符：{protagonist}、{bystanders}、{min_msg}、{max_msg}、{theme_line}、{reference_section}、{emoji_instruction}
- 无自定义风格启用时自动回退到内置默认风格

## v0.3.3
- 修复配置类型：回退 template_list 为 list 类型（AstrBot 可能不支持 template_list），确保 WebUI 正常显示
- 角色配置：主讲人QQ号、网友QQ号各一个 list，每条填一个QQ号，昵称自动从群获取
- 模板配置：每条格式 `模板名|是|内容`，兼容旧纯文本格式
- 新增口语化风格开关：关闭后使用文学化叙事风格
- 新增 @ 指定主讲人：`/sadstory @某人` 或引用消息指定主讲人

## v0.3.2
- 重构角色配置：拆为「主讲人QQ号」和「网友QQ号」两个独立列表，每条只填一个QQ号，点加号添加
- 昵称自动从群获取，无需手动填写
- 保留 @ 指定主讲人功能

## v0.3.1
- 新增 @ 指定主讲人：`/sadstory @某人` 或引用某人的消息后发 `/sadstory`，被指定的人将作为故事主讲人
- 自动获取被 @ 用户的群昵称和头像
- @ 指定优先级最高，高于后台配置的主讲人角色

## v0.3.0
- 重构角色配置：自定义用户改为列表类型，每条格式 `昵称:QQ号:角色`，支持指定主讲人/网友
- 主讲人优先：配置了主讲人角色后，故事主角固定从主讲人中选取
- 模板选择：后台模板支持启用/禁用控制，格式 `模板名|是/否|内容`
- 新增 `/sadstory_usetpl 序号` 命令：群内切换模板启用状态
- 修复模板开关可能无效的问题：增加 `_parse_bool` 兼容 WebUI 返回的各种 bool 格式
- 精简配置：移除群白名单、素材群黑名单/白名单，简化使用

## v0.2.9
- 新增 QQ 表情支持：故事消息中自动穿插 QQ 自带表情（流泪、大哭、叹气等），让聊天更真实
- LLM 生成时通过 [表情:名称] 标记，自动转换为 OneBot face 消息段
- 新增「启用QQ表情」开关，可在 WebUI 中控制
- 内置 50+ 常用表情映射（伤感、日常、社交场景）

## v0.2.8
- 修复 _parse_list/_parse_int 参数类型问题，兼容 WebUI 返回的 int 类型
- 修复 group_users 重复追加导致用户池膨胀的 bug
- sadstory_listtpl 同时显示后台配置模板和文件模板
- 故事生成失败时提示用户池不足的可能原因

## v0.2.7
- 新增 WebUI 后台模板管理：在插件配置中直接增删改故事模板
- 模板来源合并：WebUI 配置中的模板 + templates/ 目录下的文件模板同时生效
- 两种导入方式并存：后台编辑 or 群内 /sadstory_addtpl 命令

## v0.2.6
- 修复上下文污染：LLM 调用从 `tool_loop_agent` 改为 `llm_generate`，不再携带群聊历史
- 每次生成故事都是独立的 LLM 请求，不受之前对话内容影响

## v0.2.5
- 新增「启用故事模板参考」开关，可在 WebUI 中控制是否注入模板
- 新增 `/sadstory_addtpl 模板名` 命令：群内直接发消息导入模板，无需后台操作
- 新增 `/sadstory_listtpl` 命令：查看当前所有模板
- 新增 `/sadstory_deltpl 模板名` 命令：删除指定模板

## v0.2.4
- 新增「使用虚拟角色」开关：开启用假昵称+灰色头像，关闭则用真实群成员
- 自定义用户支持中文冒号（`：`）分隔，兼容输入习惯
- 增加配置加载和用户池日志，方便排查问题
- 非虚拟模式下未配置任何用户时自动从当前群拉取真实成员

## v0.2.3
- 修复头像和昵称显示问题：未配置素材群时自动从当前群拉取真实成员
- 修复合并转发 content 格式：改为消息段数组格式，符合 NapCat 规范
- 移除假用户兜底逻辑，确保始终使用真实 QQ 用户

## v0.2.2
- 彻底修复群消息识别问题：改用 `AiocqhttpMessageEvent` 替代通用 `AstrMessageEvent`
- 使用 `event.get_group_id()` 原生方法获取群号
- 参考 astrbot_plugin_qqadmin 插件的正确实现方式

## v0.2.1
- 尝试修复群号提取（未生效）

## v0.2.0
- 新增故事模板系统，支持从 `templates/` 目录加载参考素材
- 新增自定义 LLM 模型配置
- WebUI 可视化配置（`_conf_schema.json`）

## v0.1.0
- 初始版本，基础伪装聊天生成与合并转发发送
