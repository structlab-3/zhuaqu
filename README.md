# 通用监控 + 规则匹配 + 回复草稿生成框架（基于现有 Price Tracker）

## 1. 项目目标

在现有 `amazon_price_tracker` 代码基础上，抽象出一套通用框架，用来：

- 周期性监控目标数据源（网页 / API / 数据库等）；
- 对新数据执行规则匹配（关键词、条件表达式等）；
- 为命中的数据生成“回复草稿”或“处理建议”；
- 将结果输出为结构化数据（JSON / 数据库），并预留接口给后续的自动回复/通知系统。

当前阶段不直接在第三方平台上自动发言，只做到：**监控 + 命中判定 + 草稿生成**。

---

## 2. 总体架构

整体分为 4 层，尽量与现有 Price Tracker 设计保持一致：

1. **数据源适配层（Sources）**
   - 负责从不同渠道获取原始数据（HTML / JSON）。
   - 示例：
     - `WebPageSource`：使用 requests / Selenium 抓取网页（类似现在的 `AmazonScraper`）。
     - `ApiSource`：从 REST API 拉取数据。  
     - `FileSource`：从本地文件 / 日志读取。

2. **解析与标准化层（Parsers / Normalizers）**
   - 将不同数据源返回的原始数据，解析成统一的“事件/需求”结构：
     ```jsonc
     {
       "id": "external-id-or-url-hash",
       "source": "apify_forum",
       "url": "https://...",
       "title": "用户问题标题",
       "content": "用户问题正文",
       "created_at": "2025-11-20T00:00:00Z",
       "metadata": { "tags": ["amazon", "price"], "lang": "en" }
     }
     ```
   - 这一层类似现在从 HTML 中提取 `title / price / rating` 的逻辑，但改成提取“需求文本”。

3. **规则引擎层（Rule Engine）**
   - 输入：标准化后的“事件/需求”。
   - 输出：命中结果 + 匹配到的规则列表。
   - 规则形式：
     - 简单关键词匹配：包含某些词/短语；
     - 条件表达式：例如 `source == "apify_forum" AND "amazon" in content AND "price" in content`；
     - 可配置阈值：如最小文本长度、语言过滤。
   - 规则配置示例（JSON/YAML）：
     ```jsonc
     {
       "id": "amazon_price_need",
       "description": "用户在问和亚马逊价格监控相关的需求",
       "conditions": [
         {"type": "contains", "field": "content", "value": "Amazon"},
         {"type": "contains_any", "field": "content", "values": ["price tracker", "price monitoring", "价格监控"]}
       ]
     }
     ```

4. **回复草稿生成层（Draft Generator）**
   - 对命中的事件，根据规则 ID 和事件内容生成“回复草稿”。
   - 初期可以使用模板 + 变量：
     ```text
     模板 ID: amazon_price_need_zh
     模板内容:
     你好，我看到你在 {source} 上提到「{title}」...
     我这边有一个基于 Selenium + 代理的 Amazon Price Tracker，支持 {features}...
     ```
   - 进阶阶段可接入大模型（LLM）API，根据 `title + content + rule` 生成自然语言回复。
   - 输出结构：
     ```jsonc
     {
       "event_id": "xxx",
       "rule_id": "amazon_price_need",
       "draft_text": "Hello ...",
       "lang": "en",
       "created_at": "2025-11-20T00:00:00Z"
     }
     ```

---

## 3. 与现有 Price Tracker 的关系

可以复用和借鉴的部分：

- **抓取层**：`core/amazon_scraper.py` 中关于代理、User-Agent、Selenium 反检测、等待加载的逻辑，可抽象到通用 `WebPageSource`；
- **数据库层**：`utils/database.py` 的 SQLite 封装可扩展，用于存储事件、规则和草稿；
- **日志与调试**：保存 HTML / 截图的机制，可用于调试“需求抓取”是否正确；
- **CLI/GUI 经验**：`main.py` 和 `gui.py` 的多语言 CLI/GUI 设计，可以照搬，用于配置监控任务、规则和测试生成草稿。  

与价格监控的区别：

- Price Tracker：抓的是“商品页面”，输出价格表；
- 新框架：抓的是“需求/帖子/Issue/评论列表”，输出“待回复事件 + 草稿”。

---

## 4. 核心数据结构设计

1. **Event（被监控的需求/帖子）**
   ```jsonc
   {
     "id": "string",          // 唯一标识（可用 URL+站点哈希）
     "source": "string",      // 站点/来源标识
     "url": "string",
     "title": "string",
     "content": "string",
     "created_at": "ISO8601",
     "lang": "en|zh|...",
     "metadata": { "tags": [], "raw": {} }
   }
   ```

2. **Rule（匹配规则）**
   ```jsonc
   {
     "id": "string",
     "description": "string",
     "enabled": true,
     "conditions": [
       { "type": "contains", "field": "content", "value": "Amazon" },
       { "type": "contains_any", "field": "content", "values": ["price tracker", "价格监控"] }
     ],
     "target_lang": "en"
   }
   ```

3. **Draft（回复草稿）**
   ```jsonc
   {
     "id": "string",
     "event_id": "string",
     "rule_id": "string",
     "lang": "en",
     "draft_text": "string",
     "created_at": "ISO8601",
     "status": "pending | approved | sent"
   }
   ```

---

## 5. 最小可用功能（MVP 范围）

MVP 阶段只做本地跑通：

1. **单一数据源**：
   - 例如：从本地 `sample_forum.html` 文件或指定 URL 抓取帖子列表，并解析成 Event 列表。

2. **规则匹配**：
   - 支持简单 `contains` / `contains_any` 条件；
   - 在命令行打印命中的事件及命中的规则 ID。

3. **模板式草稿生成**：
   - 为每条命中事件生成一条文本草稿，写入 JSON 或 SQLite。

4. **CLI 命令**：
   - `python main.py monitor --config config.json`  
     - 读取数据源配置 → 拉取数据 → 解析 → 匹配 → 生成草稿 → 保存结果。

5. **与现有 GUI 的简单联动（可选）**：
   - 在 GUI 中加一个 Tab，用于选择一个事件并预览草稿。

---

## 6. 后续扩展方向

- 更多数据源：GitHub Issues、Reddit/论坛、Apify Actor issues、自己网站工单系统等（前提是遵守各站点 ToS）。
- 语言检测与多语言草稿：自动识别事件语言，选择对应模板或调用 LLM 翻译。
- 半自动发送：将草稿推送到一个“待审核队列”，你点确认后再通过官方 API 发出。
- 完整服务化：
  - 打包为 Apify Actor，输入为 JSON 配置，输出为 dataset；
  - 或暴露 REST API，让外部系统推送新事件进来，返回草稿建议。

---

## 7. 安全与合规注意事项

- 只在允许自动化访问/集成的系统中使用（例如你自己控制的服务、明确开放 API 的平台）。
- 禁止用来大规模群发垃圾信息或违反站点使用条款的自动回复。
- 推荐默认采用“人工确认后发送”的工作流，框架只负责“监控 + 草稿”。

---

后续如你愿意，我们可以在 `code7` 里继续：

1. 新建一个最小可用的 `monitor_main.py`；
2. 写一份 `config.sample.json`；
3. 做一个简单的本地 HTML 示例，演示从“伪论坛页面”抓需求并生成草稿。

