# 更新日志

## v0.6.18
- 修复 reload_users 锁内网络 I/O 问题，先拉取数据再上锁写入
- 修复 sadstory 冷却状态残留问题，使用 try/finally 确保失败时回滚冷却
- db.py 所有读操作添加并发保护，防止连接被关闭时读取异常
- db.py init() 添加旧连接释放，防止重复调用时资源泄漏

## v0.6.17
- 修复并发锁粒度过大问题，网络请求移出锁外执行
- 修复虚拟用户模式下自定义主角昵称为空的问题
- 修复 JSON 提取算法对字符串内容不安全的问题（区分字符串内外）
- db.py 所有写操作统一事务锁保护
- db.py close() 添加并发保护

## v0.6.16
- 修复 self.user_pool 并发竞态问题，改为局部变量传入 _generate_story
- 修复配置变更实时性问题，sadstory 命令入口先刷新配置
- 修复虚拟用户模式脏状态风险
- 添加 _fetch_group_users (30s) 和 AI 生成 (120s) 超时控制
- 优化 JSON 提取逻辑，从 O(n²) 改为 O(n) 括号栈匹配
- 修复 @主角解析去重问题，避免同一用户触发双主角模式
- 日志降级为 debug，避免泄露群消息内容
- db.py 添加事务锁保护，防止并发事务污染
- rollback 添加异常保护，避免覆盖原始错误栈

## v0.6.15
- 修复 db.py toggle_style/toggle_template 事务缺少 commit 导致状态不落盘的问题
- 用户池按 user_id 去重，避免重复角色分配异常
- 添加网络请求超时控制：get_group_member_info 10s、llm_generate 120s
- 修复最小消息数约束校验，使用 story_min_messages 替代硬编码 2
- 改进异常处理日志，添加更多上下文信息

## v0.6.14
- 修复 @ 艾特未被解析为 At 组件时双主角失效的问题
- 从 Plain 文本提取 @ 昵称并在用户池中模糊匹配

## v0.6.12
- @指定的主角强制注入用户池（避免主角不在池中导致生成失败）
- theme 去除 @ 改用 re.sub(r'@\S+', ...) 更可靠
- 增加 @ 主角获取日志

## v0.6.11
- 用户池从全局单份改为按 group_id 分组存储（group_users_map），解决多群串台问题
- 删除已无调用处的 _resolve_qq_lists 方法

## v0.6.10
- 清洗 LLM 输出中混入的 bot 日志（时间戳正则匹配）
- JSON 解析成功后立即停止扩展，要求至少 2 条消息

## v0.6.9
- JSON 解析改回渐进式（带 50000 上限），content 含 `}` 时不再误截断

## v0.6.8
- 双主角模式支持无旁观者（仅两人）场景
- JSON 解析改为 O(n) 括号栈匹配，替代 O(n²) 逐字符扩展
- 配置参数加范围校验：消息数 1~100、旁观者 0~20、cooldown ≥ 0，min/max 互纠
- 冷却计时改用 time.monotonic()，不受系统时钟影响
- ai_add_style 加 5000 字上限截断
- cooldown_map 惰性清理过期项，防止内存膨胀
- toggle_style/toggle_template 改为 BEGIN IMMEDIATE 原子事务

## v0.6.7
- reload_users 命令加 _group_users_lock 保护，移除冗余 _reload_config 调用

## v0.6.6
- 移除 sadstory 命令的冗余 _reload_config 调用，防止并发下用户池被意外重置
- _fetch_group_users 加锁保护（_group_users_lock），防止并发写入冲突
- _import_file_templates 的 add_template 返回 None 时正确跳过计数

## v0.6.5
- ai_add_style/add_template 的 UNIQUE 冲突返回 None 未处理
- ai_add_template 缺少内容上限（10000字）检查

## v0.6.4
- db.py 所有写操作（toggle/delete）添加操作上下文日志

## v0.6.3
- _import_webui_data 加并发锁，防止多请求重复写入
- JSON 提取改为渐进式解析，替代贪婪正则
- 角色模糊匹配改为最长匹配优先，避免短昵称误命中
- 主题 @ 去除改用精确字符串处理，替代脆弱正则
- 移除 list_templates/add_template 命令中的冗余 _reload_config 调用

## v0.6.2
- StarTools 导入路径改为 astrbot.api.star，符合框架规范
- 移除 _generate_story 内重复 import re
- _clear_cooldown 改为异步加锁，与 _check_and_set_cooldown 保持一致
- 模板内容上限 10000 字，风格内容上限 5000 字
- 数据库 name 字段添加 UNIQUE 约束，防止重复命名
- 添加/风格命令重复名称时返回友好提示

## v0.6.1
- 代码质量审核修复：
  - 角色映射改用 nickname + user_id 双 key，新增模糊匹配兜底，解决重名冲突
  - JSON 解析加固：正则提取 + 回退机制 + 错误日志
  - 双主角模式下检测自定义风格是否支持 {protagonist_a}/{protagonist_b}，不支持则回退内置
  - 修复失败也进冷却问题：改为成功才设置冷却
  - 新增 asyncio.Lock 解决冷却检查竞态条件
  - 移除强制主角持久化到全局用户池，避免跨群身份串用
  - 新增消息条数二次裁剪约束
  - 数据库连接保护：新增 _ensure_conn() 检查 + init 异常处理
  - 清理未使用参数 tpl_name

## v0.6.0
- 优化双主角提示词模板：强调真实对话结构，改为问答互动形式
- 双主角口语化风格：要求一问一答、互相回应，形成连续对话链
- 双主角文学风格：强调一来一往、互诉心事，形成连续情感对话
- 更新对话示例，展示真实的聊天互动节奏

## v0.5.9
- 修复双主角模式 Bug：LLM 返回占位符角色名（"主角A"、"主角B"）导致角色映射失败
- 优化双主角提示词：明确要求使用实际昵称，添加具体示例，禁止使用占位符
- 现在双主角模式下两个被 @ 的用户都能正确在聊天记录中发言

## v0.5.8
- 新增「允许使用的QQ号」配置：在 WebUI 中设置可使用指令的用户列表，留空则所有人可用
- 修复权限控制：移除无效的 permission=True，改用自定义 QQ 号白名单校验
- 所有指令统一使用新的权限检查，未授权用户静默忽略

## v0.5.7
- 新增双主角模式：`/sadstory @A @B [主题]` 同时艾特两个人，两人作为主角互动对话，围观网友穿插评论
- 新增双主角专用提示词模板（口语化/文学风格），引导 LLM 生成两人之间的对话场景
- 重构 At 解析器：支持提取最多 2 个被 @ 用户，向后兼容单 @ 和无 @ 用法

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
