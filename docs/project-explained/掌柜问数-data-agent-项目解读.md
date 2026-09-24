# 掌柜问数 data-agent · 项目解读（面向前端开发者）

> 这份文档是给「会写前端、但没碰过 Python 后端 / MySQL / Elasticsearch / Kibana / Qdrant / embedding / Docker」的你写的。
>
> 目标只有一个：**让你能从头读到尾，读完知道这个项目在干什么、代码长什么样、现在做到哪一步了。**
> 所以你会看到大量的类比和图示，专业名词第一次出现时都会用大白话解释一遍。
>
> 全文只讲**仓库里真实存在的东西**，所有引用都标了 `文件路径:行号`。凡是代码里还没有的，一律明确标注 **【尚未实现】**，不会替你脑补。
>
> **关于行号的基准**：文中所有 `文件:行号` 引用都以**当前工作树**为准（不是某个历史提交）。其中 `app/services/meta_knowledge_service.py` 相对最后一次提交有 **1 行偏移**（工作树 40 行 / HEAD 39 行），如果你用 `git show HEAD:` 去对照，这个文件的行号会整体差 1 行；其余文件的行数与提交版本一致。

---

## 目录

1. [开篇：这个项目到底是个啥](#1-开篇这个项目到底是个啥)
2. [先破除畏难：#你熟悉的-vs-这个项目](#2-先破除畏难你熟悉的-vs-这个项目)
3. [项目全景：两个库、三种存储、五个容器](#3-项目全景两个库三种存储五个容器)
4. [两条数据流：离线建库 与 在线问答](#4-两条数据流离线建库-与-在线问答)
5. [代码详解：按依赖顺序读一遍](#5-代码详解按依赖顺序读一遍)
6. [基础设施详解：docker 目录里都是什么](#6-基础设施详解docker-目录里都是什么)
7. [项目现状与待办：已实现 / 仅 demo / 空壳 TODO](#7-项目现状与待办已实现--仅-demo--空壳-todo)
8. [已知问题与提醒](#8-已知问题与提醒)
9. [附录 A：术语表](#附录-a术语表)
10. [附录 B：怎么把这个项目跑起来](#附录-b怎么把这个项目跑起来)

---

## 1. 开篇：这个项目到底是个啥

如果有人让你介绍一个新同事，你会说「他是做什么的、有什么本事」。那这个项目可以这样介绍：

> **它叫「掌柜问数」。它的本事是：让不会写 SQL 的人，用中文提问就能查数据。**
>
> 你打一句「华东地区去年销售额多少」，它就自己去搞清楚：销售额是哪个字段、华东是哪个字段的哪个值、去年该怎么过滤，然后拼出一条 SQL 去数据库里查出来，把结果给你。

用前端同学更好懂的说法：

**它想给数据库套一个「会写 SQL 的翻译官」。** 你会说中文，数据库只懂 SQL，中间这个翻译官负责把中文翻成 SQL。

但这个翻译官**不是一个纯大模型**，而是一套**带知识库的系统**。为什么不直接问大模型？因为：

> 大模型**不认识你公司内部的业务黑话**。
>
> 用户说的是「华东大区去年**销售额**」，而数据库里的字段叫 `region_name`、`order_amount`——这两个名字之间**没有任何字面联系**。如果把建表语句（DDL）直接贴给大模型让它写 SQL，它是猜不准的。

所以这个项目的核心思路是：

> **先把「业务黑话 ↔ 数据库字段」的对应关系整理成一份 AI 能检索的资料（这叫「元数据知识库」），再让 AI 基于这份资料去写 SQL。**
>
> **而整个项目当前的全部工作，都在做前面这一步——建知识库。**

### 1.1 上游已经准备好了一份「假想的业务数据」

为了让后续能验证，仓库里已经放了一个小型电商数仓的样例：

| 表 | 是什么 | 示例数据行数 | 建表位置 |
|---|---|---|---|
| `dim_region` | 地区维度表 | 6 | `docker/mysql/dw.sql:9-15` |
| `dim_customer` | 客户维度表 | 20 | `docker/mysql/dw.sql:27-33` |
| `dim_product` | 商品维度表 | 15 | `docker/mysql/dw.sql:60-66` |
| `dim_date` | 日期维度表 | 90 | `docker/mysql/dw.sql:88-95` |
| `fact_order` | **订单事实表** | 115 | `docker/mysql/dw.sql:192-201` |

样例数据分别在 `docker/mysql/dw.sql:18-23`、`:36-55`、`:69-83`、`:98-187`、`:204-318`。

然后，业务侧手写了一份「这份数据的中文含义说明书」：`conf/meta_config.yaml`（176 行），里面写清了每张表、每个字段的中文描述和**业务别名**。比如：

```yaml
# conf/meta_config.yaml:12-16
     - name: province
       role: dimension
       description: 订单所属的省份名称。
       alias: [省份, 省, 所在省份]
       sync: true
```

```yaml
# conf/meta_config.yaml:160-164
     - name: order_amount
       role: measure
       description: 订单金额。
       alias: [销售额, 订单金额, 收入]
       sync: false
```

这份 yaml 一共描述了 **5 张表、24 个字段、2 个指标**（指标见 `conf/meta_config.yaml:166-176`）。

> **这份 yaml 是整个项目的「钥匙」**，第 4 节会讲为什么。

### 1.2 三句话先记住

1. **它在干什么**：做一个「用中文问数据」的 AI 助手，用户问一句话，系统自己翻译成 SQL 去查数仓。
2. **它的核心设计**：不能把表结构直接丢给大模型（模型不懂业务黑话），所以要**先建一个元数据知识库**。
3. **它现在的进度**：**基础设施和配置全齐了，核心业务逻辑一行都还没写。** 典型的「骨架搭好、等你填肉」阶段。

---

## 2. 先破除畏难：你熟悉的 vs 这个项目

你看到 MySQL / Elasticsearch / Kibana / Qdrant / embedding / Docker 这六个词就头晕，这很正常——**它们听起来像六个不同的世界，其实你全都见过，只是换了行业名字。**

先把这张表看一遍，畏难情绪能降一半：

| 你会听到的词 | 它在这个项目里是什么 | 你前端世界里的对应物 | 一句话记忆 |
|---|---|---|---|
| **MySQL** | 关系型数据库，数据存在「表」里，用 SQL 查 | 一堆互相能 JOIN 的 **Excel 工作表**；`CREATE TABLE` 像定义 TS interface | **真正存数据的地方** |
| **Elasticsearch（ES）** | 专门做「文本搜索」的引擎，擅长中文分词、关键词匹配 | 加强版的「全文检索」：你写过的手搓搜索 `list.filter(x => x.title.includes(q))` 的**专业版**（提前建好倒排索引，不遍历） | **一个超强的搜索框** |
| **Kibana** | ES 的官方**网页版可视化控制台** | 相当于 **DevTools 面板** / MongoDB Compass / Navicat；纯调试用 | **给 ES 装的「管理后台」** |
| **Qdrant** | **向量数据库**，存的是「语义向量」，按语义相近程度找最像的 | 语义模糊匹配：搜「大区」能命中 `region_name`，即使**一个字都不一样** | **按「意思像不像」搜索的库** |
| **embedding** | 把一句话变成一串数字（**1024 个**浮点数），意思相近的句子数字也相近 | 像把字符串「编码」成一串定长数组，但要求**「意思像 → 数组也像」** | **文本 → 数字的翻译机** |
| **Docker** | 把「程序 + 运行环境」打包成镜像，一条命令拉起全部服务 | 像把 `node_modules` + Node 运行时一起打包，交付后不用配环境就能跑 | **环境打包工具** |

看完这张表，再记住**它们为什么要一起出现**：

> 想让机器理解「华东地区去年销售额多少」这句话，需要三种不同的**「找」**的能力：
>
> - **按语义找**（用户说「大区」，怎么知道指的是 `region_name`？）→ 用 **Qdrant + embedding**
> - **按关键词找**（用户说「华东」，怎么知道这个词真的存在、是哪张表的值？）→ 用 **Elasticsearch**
> - **精确地存下来**（表叫什么、字段什么含义、指标怎么算？）→ 用 **MySQL**
>
> 而 **Docker** 负责把上面这三个「服务」一键跑起来，**Kibana** 是给你调试 Elasticsearch 用的。

### 2.1 六个概念的最小知识（够用就行）

下面每个概念给一个「能看懂文档」的程度，不必深究：

**① MySQL —— 存数据的库**

数据按「表」组织。一张表 = 表头（列）+ 一堆行。

| 概念 | 解释 | 前端类比 |
|---|---|---|
| 数据库（database） | 一个命名空间，里面装很多表 | 一个大模块 / 命名空间 |
| 表（table） | 一类数据的集合，列结构固定 | 一个数组 `[{}, {}, ...]` |
| 行（row） | 一条具体数据 | 数组里的一个对象 |
| 列（column） | 一个字段 | 对象的 key，但有**固定类型** |
| 主键（primary key） | 能唯一标识一行的字段 | 列表渲染的 `key`，但更强：不重复、不能为空 |

真例子（`docker/mysql/dw.sql:9-15`）：

```sql
CREATE TABLE dim_region
(
    region_id   VARCHAR(20) PRIMARY KEY,   -- 主键
    province    VARCHAR(50),               -- 普通列
    region_name VARCHAR(50),
    country     VARCHAR(50)
);
```

对应的数据（`docker/mysql/dw.sql:18-23`）第一行就是 `('R001', '广东省', '华南', '中国')`，
翻译成 JS 就是 `{ region_id: 'R001', province: '广东省', region_name: '华南', country: '中国' }`。

**② SQL —— 用来操作数据库的语言**

长这样（这句是**通用示例**，仓库里目前还没有真实的查询语句）：

```sql
SELECT d.region_name, SUM(f.order_amount) AS gmv
FROM fact_order f
JOIN dim_region d ON f.region_id = d.region_id
GROUP BY d.region_name
ORDER BY gmv DESC;
```

读法跟 JS 对照：`FROM fact_order f` 像 `const f = fact_order`；`JOIN ... ON` 像用 `Map` 按 key 合并对象；`GROUP BY` 就是 `groupBy`；`SUM` 就是 `reduce`。

**这个项目要干的事，本质就是把中文问题翻译成上面这种 SQL。**

**③ Elasticsearch —— 专门搜文本的库**

MySQL 查 `WHERE product_name LIKE '%手机%'` 有个致命问题：它只能做**字符子串匹配**。数据里是 `iPhone 15 Pro`，里面**没有「手机」这两个字**，所以查不到。

ES 的做法是：建索引时把文本**切成词**，并记录「每个词出现在哪些文档」——这叫做**倒排索引**：

```
苹果   → [文档1, 文档7, 文档9]
手机   → [文档1, 文档3]
华为   → [文档3, 文档5]
```

搜「华为手机」就直接拿两个词的表求交集，**不用扫任何一行**。不过 ES **不理解近义词**——搜「华东」命中「华东」，但它不知道「华东」和「大区」是有关联的。

**④ Qdrant + embedding —— 按意思搜**

embedding 把句子变成 1024 个数字：

| 句子 | 变成（示意，真实是 1024 个数） |
|---|---|
| 「怎么退款」 | `[0.82, 0.11, -0.35, ...]` |
| 「我要退货」 | `[0.80, 0.13, -0.31, ...]` |
| 「今天天气真好」 | `[-0.44, 0.91, 0.02, ...]` |

规律是：**意思相近的句子，数字串也相近。** 所以「用户说『大区』→ 命中 `region_name`」这种**字面完全不像但语义相近**的匹配，只能靠这套。

Qdrant 就是**专门存这些数字串、并回答「哪个最像」的数据库**（MySQL 干这个很慢，后面第 6 章会讲原因）。

**⑤ Docker —— 一条命令跑起 5 个服务**

没有 Docker，你得手敲 5 条又长又容易写错的 `docker run`。有了 `docker-compose.yaml`，一次配置、一条命令全起来。

⚠️ 先纠正一个最常见的误解：**Docker 容器 ≠ 虚拟机。**

| | 虚拟机（VMware） | Docker 容器 |
|---|---|---|
| 里面跑什么 | 一整套操作系统（**自带内核**） | 只跑一个程序 + 它的依赖库 |
| 内核 | 自带一个 | **和宿主机共用同一个** |
| 体积 | 几 GB 起 | 几十 MB 到几百 MB |
| 启动 | 几十秒到几分钟 | 通常 1 秒内 |

所以容器不是「小电脑」，而是**一个被隔离起来、自带全部依赖的进程**。

（Windows 上的一个细节：容器共享的是 **Linux** 内核，Windows 没有，所以 Docker Desktop 会在后台起一个轻量 Linux 虚拟机提供这个内核。**但容器本身仍然不是虚拟机**——一台虚拟机里可以跑成百上千个容器。）

**⑥ Kibana —— 打工人调试用的网页工具**

ES 里存的是 JSON 文档，不像 MySQL 那样随手找个客户端就能看。Kibana 就是它的网页管理界面，进去有个 **Dev Tools** 页面，可以手敲查询语句看结果。**它不参与任何业务逻辑**——全仓库搜 `kibana`，只会命中 `docker/docker-compose.yaml` 里的几行配置。

---

## 3. 项目全景：两个库、三种存储、五个容器

这一节回答三个问题：**为什么要有两个库？为什么要有三种存储？五个容器各干什么？**

### 3.1 为什么不能把表结构直接丢给大模型

这是理解整个项目分层设计的钥匙，花 2 分钟看明白，后面全都顺了。

> 先给你一个「项目有多小」的直观印象：仓库第一方源码一共只有 **29 个 `.py` 文件 + 3 个 yaml + 2 个 sql**，而且其中 **14 个 `.py` 是 0 字节的空 `__init__.py`**，**真正有内容的只有 15 个**。（这个数字排除了 `.venv/` 和 `.git/`。）
> **所以不要被「29 个文件」吓到——你要读的其实只有 15 个。**

**直觉方案（错的）**：把 5 张表的建表语句全贴进 prompt，让大模型看着写 SQL。

**为什么不行**：大模型不认识「业务黑话」。用户说的是：

> 「华东**大区**去年**销售额**多少？」

而它需要生成的是对 `region_name = '华东'`、`order_amount`、`year = 2025` 的操作。这中间要做两层翻译：

| 用户说的话 | 数据库里的东西 | 谁来负责翻译 |
|---|---|---|
| 华东 | `dim_region.region_name = '华东'` | 维度字段的**真实取值**必须提前索引（`conf/meta_config.yaml:21`） |
| 销售额 | `fact_order.order_amount` | 字段的**业务别名**（`conf/meta_config.yaml:163`） |
| 大区 | `dim_region.region_name` | 字段别名 + **语义**相近（`conf/meta_config.yaml:21`） |
| 去年 | `dim_date.year` | 字段别名 + 时间维度（`conf/meta_config.yaml:96-100`） |
| 「先按地区汇总再算平均」 | JOIN 关系 + 指标定义 | 指标/口径知识（`conf/meta_config.yaml:166-176`） |

所以项目引入了**元数据知识库（meta knowledge）**：把所有「业务黑话 ↔ 物理字段」的对应关系提前整理好，存进三个地方。

### 3.2 为什么需要两个库：`dw` 和 `meta`

两个库在**同一个 MySQL 容器**里（都是 `localhost:3308`，配置见 `conf/app_config.yaml:12-24`、`:19-24`），但职责完全不同：

| | `meta` 库 | `dw` 库 |
|---|---|---|
| 全称 | metadata，**元数据** | data warehouse，**数据仓库** |
| 存什么 | **关于数据的数据**：表叫什么、字段什么意思、别名是什么、指标怎么算 | 真正的**业务数据**：一行行订单、一个个客户 |
| 打个比方 | 图书馆的**索引卡片**（告诉你「烹饪类在第 3 排」，卡片本身不是书） | 书架上**真正的书** |
| 建表文件 | `docker/mysql/meta.sql`（**4 张表**，表是空的） | `docker/mysql/dw.sql`（5 张表 + 115 行样例数据） |
| 谁写入 | 由本项目脚本生成（**【尚未实现】**） | 上游业务系统 / ETL；本项目**只读** |
| 谁查询 | 链路 A 写入、链路 B 读取 | 链路 B 最后一步执行 SQL 的地方 |
| 代码里的连接单例 | `meta_mysql_client_manager`（`app/clients/mysql_client_manager.py:24`） | `dw_mysql_client_manager`（`app/clients/mysql_client_manager.py:25`） |

**为什么必须分开？** 举个例子：用户问「上个月华南的销售额是多少」，机器需要知道「华南」对应哪个字段、「销售额」对应哪个公式。**这些信息不是数据，而是「关于数据的知识」**：

- 难道写死在代码里？那换一个数据库、换一个业务就得改代码，**产品没法复用**；
- 难道从表结构反推？**做不到**。看到 `order_amount` 这个字段名，机器不可能自己推出它中文叫「销售额/订单金额/收入」，也不知道「销售额」还要套一个 `SUM()`。

**一句话**：`meta` 库是给 **AI** 看的（帮它理解 `dw` 里有什么），`dw` 库是给 **用户** 看的（最终答案的数据来源）。

### 3.3 为什么需要三种存储：MySQL + Qdrant + ES

| 存储 | 负责哪种「找」 | 具体干什么 | 为什么非它不可 |
|---|---|---|---|
| **MySQL `meta` 库** | 结构化地记住 | 精确地存表/字段/指标/关联关系，方便查询和人工核对 | 数据量小、关系明确，用关系型库最合适 |
| **Qdrant** | **按语义找** | 把字段描述和别名做成向量存起来 | 用户说「大区」，字面和 `region_name` 毫无关系，只能靠语义 |
| **Elasticsearch** | **按关键词找** | 把维度字段的**真实取值**（华东、华南、黄金、苹果……）灌进去 | 用户说「华东」，要能确认这个值真的存在、属于哪个字段 |

> **分工一句话**：**Qdrant 负责「猜你指的是哪个字段」，ES 负责「确认你提的值真的存在」，MySQL meta 库负责「结构化地记住这一切」。**

### 3.4 五个 Docker 容器各干什么

容器清单来自 `docker/docker-compose.yaml:1-80`。**注意：跑在 Docker 里的只有这 5 个基础设施服务，Python 业务代码（`app/`）是跑在你本机上的**——证据是 `conf/app_config.yaml:13` 连库用的是 `host: localhost`，如果业务代码也在容器里，这里就该写容器名 `mysql` 了。

| # | 服务名 | 是什么 | 宿主端口 → 容器端口 | 一句话职责 | 代码连着它吗 |
|---|---|---|---|---|---|
| 1 | `mysql` | 关系型数据库 | **3308** → 3306（`docker-compose.yaml:12`） | 同时装 `dw` 库（业务数据）和 `meta` 库（元数据） | ✅ `app/clients/mysql_client_manager.py:24-25` |
| 2 | `elasticsearch` | 全文检索引擎 | **9200** → 9200（`:31`） | 中文分词 + 关键词检索，索引名 `data_agent` | ✅ `app/clients/es_client_manager.py:11-20` |
| 3 | `kibana` | ES 的网页界面 | **15601** → 5601（`:44`） | **纯人工调试**，看 ES 里的数据 | ❌ **没有任何代码连它** |
| 4 | `qdrant` | 向量数据库 | **6333** → 6333（HTTP）、**6334** → 6334（gRPC）（`:55-56`） | 存语义向量，回答「最像的 N 条」 | ✅ `app/clients/qdrant_client_manager.py:12-24` |
| 5 | `embedding` | 文本转向量服务（TEI） | **8081** → 80（`:67`） | 文本进来，1024 个数字出去 | ❌ **只有配置，没有客户端代码** |

⚠️ **端口号请务必记准**（新手最容易错的地方）：

- **Kibana 是 `15601`，不是它默认的 5601**。`docker/docker-compose.yaml:44` 写的是 `"15601:5601"`，也就是说**宿主机上的 5601 是访问不到的**，浏览器要开 `http://localhost:15601`。
- MySQL 是 `3308`（不是默认的 3306）、ES 是 `9200`、Qdrant 是 `6333`/`6334`、embedding 是 `8081`。

### 3.5 一张架构全景图

```mermaid
flowchart TB
    subgraph CODE["你本机上的 Python 代码（app/）"]
        YAML["conf/meta_config.yaml<br/>手写业务元数据<br/>5 张表 / 24 个字段 / 2 个指标"]
        SCRIPT["app/scripts/build_meta_knowledge.py:14<br/>命令行入口 build()"]
        SVC["MetaKnowledgeService.build()<br/>app/services/meta_knowledge_service.py:10"]
        MGR["app/clients/ 三个连接管理器<br/>mysql:24-25 / qdrant:24 / es:20"]
        REPO["MetaMySQLRepository<br/>app/repositories/mysql/meta/<br/>只有 __init__，无任何方法"]
    end

    subgraph DOCKER["Docker 里的 5 个服务"]
        subgraph MYSQLBOX["MySQL 容器 · localhost:3308"]
            META[("meta 库<br/>4 张元数据表<br/>docker/mysql/meta.sql")]
            DW[("dw 库<br/>5 张业务表 + 115 行数据<br/>docker/mysql/dw.sql")]
        end
        QDRANT[("Qdrant · localhost:6333<br/>语义召回")]
        ES[("Elasticsearch · localhost:9200<br/>索引 data_agent + IK 分词")]
        KIBANA["Kibana · localhost:15601<br/>ES 调试面板"]
        EMB["embedding · localhost:8081<br/>BAAI/bge-large-zh-v1.5<br/>文本 → 1024 维向量"]
    end

    subgraph ONLINE["在线问答链路 —— 【尚未实现】"]
        USER["用户提问：<br/>华东地区去年销售额多少"]
        RETRIEVE["元数据召回<br/>语义 + 关键词"]
        LLMQ["LLM 生成 SQL"]
        EXEC["执行 SQL"]
        ANS["返回答案"]
    end

    YAML --> SCRIPT --> SVC
    SVC --> MGR
    SVC --> REPO
    REPO -.->|"2.1 写 meta 库 ❌ 未实现"| META
    MGR -.->|"2.2 建向量索引 ❌ 未实现"| QDRANT
    MGR -.->|"2.3 建全文索引 ❌ 未实现"| ES
    EMB -.->|"embedding 客户端不存在 ❌"| QDRANT
    ES -.-> KIBANA

    USER -.-> RETRIEVE
    RETRIEVE -.->|"语义召回 ❌"| QDRANT
    RETRIEVE -.->|"关键词召回 ❌"| ES
    RETRIEVE -.-> LLMQ
    LLMQ -.-> EXEC
    EXEC -.->|"查数仓 ❌ 执行代码未写"| DW
    EXEC --> ANS

    classDef done fill:#d4f8d4,stroke:#2e7d32,color:#000
    classDef shell fill:#fff4cc,stroke:#b58900,color:#000
    classDef empty fill:#ffe0e0,stroke:#c62828,color:#000
    classDef infra fill:#e3f2fd,stroke:#1565c0,color:#000

    class YAML,SCRIPT,MGR done
    class SVC,REPO shell
    class ONLINE,USER,RETRIEVE,LLMQ,EXEC,ANS empty
    class MYSQLBOX,QDRANT,ES,KIBANA,EMB,META,DW infra
```

**图例**：🟩 绿 = 已实现可用；🟨 黄 = 有骨架但核心为空；🟥 红 = 完全没有实现；🟦 蓝 = 基础设施（Docker 服务 + 已初始化好的数据）。
**实线** = 代码里真实存在的调用；**虚线** = 目标设计 / 尚未实现。

---

## 4. 两条数据流：离线建库 与 在线问答

项目有两条链路：一条**离线**（建知识库），一条**在线**（回答问题）。

| | 链路 A：离线建库 | 链路 B：在线问答 |
|---|---|---|
| 谁来触发 | 你手动跑一条命令 | 用户在页面上提问 |
| 干什么 | 把 `meta_config.yaml` 变成 AI 能检索的知识库 | 把中文问题翻译成 SQL，查数仓，返回答案 |
| 代码状态 | **骨架已搭好，5 个核心步骤全是空** | **一行代码都没有** |
| 涉及文件 | `app/scripts/build_meta_knowledge.py`、`app/services/meta_knowledge_service.py` | 无 |

### 4.1 链路 A：离线建库（骨架完整，内部为空）

触发方式就是一条命令：

```bash
python -m app.scripts.build_meta_knowledge -c conf/meta_config.yaml
```

> 参数 `-c/--conf` 定义在 `app/scripts/build_meta_knowledge.py:31`，启动调用在 `:36`。
> **必须从项目根目录跑**，否则 `from app.xxx import ...` 会失败（因为 `app` 是包名）。

逐步走一遍：

**① 读手写业务元数据**

`conf/meta_config.yaml`（176 行）= 5 张表 / 24 个字段 / 2 个指标，全是人工写的中文业务含义。

**② 组装对象（已实现）**

`app/scripts/build_meta_knowledge.py:14` 的 `build()` 函数做四件事：

```python
# app/scripts/build_meta_knowledge.py:14-21
async def build(config_path: Path):
    meta_mysql_client_manager.init()                       # :15 建 MySQL 连接池（连 meta 库）
    async with meta_mysql_client_manager.session_factory() as session:   # :16 开一个数据库会话
        meta_mysql_repository = MetaMySQLRepository(session)             # :17 包成 repository
        meta_knowledge_service = MetaKnowledgeService(meta_mysql_repository)  # :18 依赖注入
        await meta_knowledge_service.build(config_path)                   # :19 ← 核心逻辑，目前是空的

    await meta_mysql_client_manager.close()                # :21 关连接池
```

这段是**全项目最值得看懂的一段**，因为它展示了各层怎么组装：

```
① init() 建连接池
      ↓
② async with session_factory() 开会话     ← 用完自动关，连接归还池子
      ↓
③ MetaMySQLRepository(session)            ← 仓储层：拿会话，负责读写（当前是空壳）
      ↓
④ MetaKnowledgeService(repository)        ← 服务层：拿仓储，负责业务
      ↓
⑤ await service.build(config_path)        ← 真正干活（目前是空转）
      ↓
⑥ close() 关掉连接池
```

**③ 核心逻辑（【尚未实现】）**

`app/services/meta_knowledge_service.py:10` 的 `build()` 里，只有配置读取（`:12-16`）是真代码：

```python
# app/services/meta_knowledge_service.py:12-18
context = OmegaConf.load(config_path)                                    # 读 yaml
schema = OmegaConf.structured(MetaConfig)                                # dataclass 当 schema
meta_config: MetaConfig = OmegaConf.to_object(OmegaConf.merge(schema, context))  # 校验 + 转对象
print(meta_config.metrics)                                               # :18 调试残留，唯一真正「输出东西」的一行
```

剩下的 5 个 TODO 全都没写：

```
# app/services/meta_knowledge_service.py:20-38
2.1 表信息 / 字段信息 → 写 meta 库（table_info / column_info）   :22-27  ❌ 循环体是 pass
2.2 字段信息 → 建向量索引（写 Qdrant）                          :29     ❌ 只有一行注释
2.3 指定维度字段取值 → 建全文索引（写 ES）                       :31-32  ❌ 里面只有一个多余的 pass
3.1 指标信息 → 写 meta 库（metric_info / column_metric）         :36     ❌ 只有一行注释
3.2 指标信息 → 建向量索引                                       :37     ❌ 只有一行注释
（3.1 与 3.2 共用 :38 的一个 pass）
```

> **验收结论**：这段代码现在跑完，除了 `:18` 那行 `print` 会把 2 个指标对象打到屏幕上，**不会向任何数据库写一个字节**。
> 作者自己在源码里留下的 TODO 编号（2.1 / 2.2 / 2.3 / 3.1 / 3.2）就是接下来要实现的任务清单。

**这条链路最终要产出的三份数据**（也就是「元数据知识库」）：

| 产出 | 放哪儿 | 内容 | 用途 | 状态 |
|---|---|---|---|---|
| 表/字段/指标结构化信息 | MySQL `meta` 库 4 张表（`docker/mysql/meta.sql`） | 表名、字段名、类型、角色、描述、别名 | 精确查询、人工核对、给 LLM 拼上下文 | ❌ 未实现 |
| 字段语义向量 | Qdrant 的一个 collection | 每条 = 一段字段描述文本的 1024 维向量 | 语义召回：「大区」→ `region_name` | ❌ 未实现 |
| 维度取值全文索引 | ES 的 `data_agent` 索引（`conf/app_config.yaml:39`） | `sync: true` 字段的真实取值 | 关键词召回：「华东」→ 确认值存在 | ❌ 未实现 |

**一个小插曲——`sync: true/false` 是什么？**

`conf/meta_config.yaml` 里 24 个字段每个都带一个 `sync: true/false`，我数过：`sync: true` 共 10 个，`sync: false` 共 14 个。

- **`sync: true` 的 10 个，全是「需要被筛选/分组的中文维度」**：`province`(:16)、`region_name`(:22)、`country`(:28)、`customer_name`(:44)、`gender`(:50)、`member_level`(:56)、`product_name`(:72)、`category`(:78)、`brand`(:84)、`quarter`(:106)。
- **`sync: false` 的 14 个里，11 个是主键 / 外键 / 度量值**：`region_id`(:10)、`customer_id`(:38)、`product_id`(:66)、`date_id`(:94)、`order_id`(:128)、`customer_id`(:134)、`product_id`(:140)、`date_id`(:146)、`region_id`(:152)、`order_quantity`(:158)、`order_amount`(:164)。
- **另外 3 个才是特例**：`dim_date` 的 `year`(:100)、`month`(:112)、`day`(:118)——它们的 `role` 是 `dimension`（本来就是维度，不是主键/外键/度量），却被标成了 `sync: false`。**这 3 个疑似是标记问题**，与 8.6 节的待确认项是同一件事，两处口径一致。

所以合理的推断是：**`sync: true` 的字段，将来要把它的全部取值抽出来灌进 ES**。

### 4.2 链路 B：在线问答（【尚未实现】）

**这条链路在仓库里一行代码都没有。** 下面是从现有配置和依赖**反推**出来的目标设计，每一步都标了证据来源：

```
用户在页面输入：「华东地区去年销售额多少」
    │
    ▼
① 【未实现】HTTP 接口收到问题
     证据：pyproject.toml 装了 fastapi，但仓库里没有任何 FastAPI 应用代码
    │
    ▼
② 【未实现】元数据召回
     ├─ 语义召回：问题向量 → 查 Qdrant → 命中 fact_order.order_amount / dim_region.region_name
     │   证据：配置了 qdrant（conf/app_config.yaml:26-29）+ embedding 服务（:31-34）
     └─ 关键词召回：问题里的「华东」→ 查 ES → 确认是 dim_region.region_name 的取值
         证据：ES 索引名 data_agent（conf/app_config.yaml:39）+ IK 中文分词插件（docker/elasticsearch/Dockerfile:5-8）
    │
    ▼
③ 【未实现】拼 prompt 交给 LLM 生成 SQL
     证据：conf/app_config.yaml:41-44 配了 llm（model_name / api_key / base_url），
           但 app/clients/ 下只有 mysql / qdrant / es 三个 manager，没有 LLM 客户端
    │
    ▼
④ 【未实现】执行 SQL：连 dw 库跑查询
     证据：连接器已就绪（app/clients/mysql_client_manager.py:25 的 dw_mysql_client_manager），
           但 app/repositories/mysql/dw/ 目录里只有一个 0 字节的 __init__.py，没有任何执行代码
    │
    ▼
⑤ 【未实现】把结果集返回前端渲染（表格/图表）
```

⚠️ **特别提醒**：`dw_mysql_client_manager` 的存在让第 ④ 步看起来很近，但从「能连上库」到「能安全执行 LLM 生成的 SQL」还隔着三件事——**SQL 校验白名单、查询超时/行数限制、结果结构化**。这三件事目前都是空白。

### 4.3 两条链路的关系（一句话）

> **链路 A 是「备课」，链路 B 是「上课」。** 现在的情况是：教材（`meta_config.yaml`）写好了、教室（Docker 基础设施）装修好了，但**备课笔记一个字没写，课也还没开始上**。

---

## 5. 代码详解：按依赖顺序读一遍

这一节是主体。我按**依赖顺序**来讲（被依赖的先讲）：`conf` → `core` → `clients` → `models` → `repositories` → `services` → `scripts` → `main.py`。

先给你一张全项目的「代码地图」，排除 `.venv/`（Python 依赖目录，相当于 `node_modules`）和 `.git/` 之后，第一方代码就这么点：

| 层 | 文件 | 行数 | 真实状态 |
|---|---|---|---|
| 配置 | `app/conf/app_config.py` | 72 | ✅ 完整可用 |
| 配置 | `app/conf/meta_config.py` | 29 | ✅ 完整可用 |
| 日志 | `app/core/log.py` | 28 | ✅ 完整可用 |
| 连接 | `app/clients/mysql_client_manager.py` | 41 | ✅ 可用（末尾含 demo） |
| 连接 | `app/clients/es_client_manager.py` | 51 | ✅ 可用（末尾含 demo） |
| 连接 | `app/clients/qdrant_client_manager.py` | 68 | ✅ 可用（末尾含 demo） |
| 模型 | `app/models/base.py` | 4 | ✅ **公共基类，不对应表** |
| 模型 | `app/models/table_info.py` 等 4 个 | 18~42 | ✅ 对应 4 张表 |
| 仓储 | `app/repositories/mysql/meta/meta_mysql_repository.py` | 7 | 🟡 空壳，一个方法都没有 |
| 仓储 | `app/repositories/es/`、`qdrant/`、`mysql/dw/` | — | ❌ 只有 0 字节 `__init__.py` |
| 服务 | `app/services/meta_knowledge_service.py` | 40 | 🟡 **核心文件，但 build() 里是 pass** |
| 入口 | `app/scripts/build_meta_knowledge.py` | 36 | ✅ 真正的命令行入口 |
| 入口 | `main.py` | 5 | ❌ **不是入口**，只是日志 demo |

**一句话总结**：**能跑的是「连上各种服务」，不能跑的是「干业务活」。**

### 5.1 conf 层：配置是怎么读进来的

#### 5.1.1 `app/conf/app_config.py`（72 行）

这个文件的使命只有一句话：**把 `conf/app_config.yaml` 变成一个带类型检查的 Python 对象，供全项目 import。**

**第一段：声明「配置长什么样」**

```python
# app/conf/app_config.py:6-12
@dataclass
class File:
  enable: bool
  level: str
  path: str
  rotation: str
  retention: str
```

- **`@dataclass` 是什么**：一个 Python 装饰器（装饰器 = 「给函数/类套一层外挂改它的行为」，类似 JS 的 `@decorator` 或高阶组件）。你只写字段和类型，Python 自动帮你生成构造函数 `__init__`、打印用的 `__repr__`、比较用的 `__eq__`。
- **它在干什么**：声明「日志文件配置」应该有哪些字段、什么类型。**注意它只声明，不带值。**
- **前端类比**：等同于你写了个 TypeScript 的 `interface File { enable: boolean; level: string; ... }`。

这个文件一共声明了 **9 个 dataclass**：

| # | 类名 | 行号 | 管什么 |
|---|---|---|---|
| 1 | `File` | `:6-12` | 日志文件出口（开关、级别、路径、轮转、保留） |
| 2 | `Console` | `:14-17` | 日志控制台出口 |
| 3 | `LoggingConfig` | `:19-22` | 把上面两个拼起来 |
| 4 | `DBConfig` | `:25-31` | 数据库连接（meta 和 dw 各用一次） |
| 5 | `QdrantConfig` | `:33-37` | 向量库连接 + 向量维度 |
| 6 | `EmbeddingConfig` | `:39-43` | embedding 服务 |
| 7 | `ESConfig` | `:45-49` | Elasticsearch |
| 8 | `LLMConfig` | `:51-55` | 大模型（**注意：全仓库没人用它**） |
| 9 | `AppConfig` | `:57-65` | 总装类，把 7 块配置拼起来 |

```python
# app/conf/app_config.py:57-65
@dataclass
class AppConfig:
  logging: LoggingConfig
  db_meta: DBConfig
  db_dw: DBConfig
  qdrant: QdrantConfig
  embedding: EmbeddingConfig
  es: ESConfig
  llm: LLMConfig
```

`AppConfig` 的字段名，必须和 `conf/app_config.yaml` 里的**顶级 key 一模一样**——这是类型校验能生效的前提。

**第二段：读 yaml + 校验 + 转对象（`:67-70`，只有 4 行，但很关键）**

```python
# app/conf/app_config.py:67-70
config_file = Path(__file__).parents[2] / 'conf' / 'app_config.yaml'
context = OmegaConf.load(config_file)
schema = OmegaConf.structured(AppConfig)
app_config: AppConfig = OmegaConf.to_object(OmegaConf.merge(schema, context))
```

逐行拆：

| 行 | 代码 | 在干什么 | 前端类比 |
|---|---|---|---|
| 67 | `Path(__file__).parents[2]` | `__file__` = 当前文件路径，`parents[2]` = 往上退两级（`app/conf/` → `app/` → 项目根） | `path.resolve(__dirname, '../..')` |
| 68 | `OmegaConf.load(...)` | 把 yaml 文字读成 **DictConfig**：能用点号访问的字典（`cfg.a.b`） | `JSON.parse` + 点号访问 |
| 69 | `structured(AppConfig)` | 把 dataclass 变成 **schema**：字段名清单 + 类型约束 + 默认值 | `zod` 的 schema 定义 |
| 70 | `merge(schema, context)` | **schema 打底，yaml 覆盖** | `{...defaults, ...userConfig}` |
| 70 | `to_object(...)` | 把 DictConfig 转成**真正的 Python 对象** | 从 plain object 转成 class 实例 |

**这个模式为什么值得记住**：如果 yaml 里把 `port` 写成字符串 `"3308"`，或者把 `db_meta` 拼错成 `dbmeta`，第 70 行会**直接抛错**，而不是等到运行时才发现。这就是「schema 打底 + 外部配置覆盖 + 类型不对立即报错」。**≈ TypeScript interface + zod。**

**第三段：全局单例（第 70 行的副产品）**

- `app_config` 写在模块顶层。Python 的规矩是「一个模块只被 import 一次」，所以第 70 行整个过程**只执行一次**，之后 `from app.conf.app_config import app_config` 拿到的永远是同一个对象。
- **前端类比**：就像 `export const appConfig = {...}` 的模块级常量。
- **代价**：**import 这个模块的瞬间就会去读文件**。文件路径错了，import 就炸。这是 Python 里常见的「import 有副作用」现象。

第 72 行是一句被注释掉的 `# print(...)`，调试残留。

#### 5.1.2 `app/conf/meta_config.py`（29 行）

这是**业务元数据**配置的类型定义，结构和 `app_config.py` 完全同构，但含义不同：`app_config` 管的是「连哪儿」，`meta_config` 管的是「业务上表/字段/指标叫什么、是什么意思」。

```python
# app/conf/meta_config.py:4-10
@dataclass
class ColumnConfig:
  name: str
  role: str
  description: str
  alias: list[str]
  sync: bool
```

4 个类的嵌套关系：

```
MetaConfig
├── tables: Optional[list[TableConfig]]
│              └── columns: list[ColumnConfig]
└── metrics: Optional[list[MetricConfig]]
```

（定义见 `app/conf/meta_config.py:12-17`、`:19-24`、`:26-29`。）

要点：

- `list[ColumnConfig]`（`:17`）是 Python 3.9+ 的泛型写法，等价 TS 的 `ColumnConfig[]`。
- `Optional[...] = None`（`:28-29`）= 「这个字段可以没有」= TS 的 `tables?: TableConfig[]`。
- **`MetaConfig` 的字段名必须和 `conf/meta_config.yaml` 的顶级 key 对齐**（该 yaml 里只有 `tables` 和 `metrics`）。
- 这里**没有**调用 `OmegaConf.merge`，而是等真正要读的时候（在 `meta_knowledge_service.build()` 里）才读。对比一下就知道：**`app_config.py` 是「import 即加载」，`meta_config.py` 是「按需加载」。**

### 5.2 core 层：日志系统

#### `app/core/log.py`（28 行）

整体干的事：**把 loguru 的默认输出清掉，再按配置装上「控制台」和「文件」两个出口。**

**第一段：日志格式模板（`:8-13`）**

```python
# app/core/log.py:8-13
log_format = (
  "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
  "<level>{level: <8}</level> | "
  "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
  "<level>{message}</level>"
)
```

- `{xxx}` 是占位符，输出时替换成真实值。
- `<green>`、`<cyan>` 是**终端彩色标记**，只影响控制台显示，文件里是纯文本。
- `{level: <8}` 里的 `<8` = 「左对齐补空格到 8 位」，让日志竖向对齐——和 `padEnd(8)` 一个意思。
- 格式串本身是**相邻字符串字面量自动拼接**（Python 的特性），外面的 `(...)` 只是为了让多行书写合法。
- **为什么这么写**：格式统一定义在一处，两个出口复用。

**第二段：清空默认 handler + 注册两个出口（`:15-28`）**

```python
# app/core/log.py:15-28（节选）
logger.remove()
if app_config.logging.console.enable:
  logger.add(sink=sys.stdout, level=app_config.logging.console.level, format=log_format)
if app_config.logging.file.enable:
  path = Path(app_config.logging.file.path)
  path.mkdir(parents=True, exist_ok=True)
  logger.add(sink=path / "app.log", level=..., rotation=..., retention=..., encoding="utf-8")
```

- **`logger.remove()`**：loguru 开箱自带一个「输出到 stderr」的 handler，不先 `remove()` 就会**重复打印两遍**。这是 loguru 的固定套路。
- **`sink`**：日志往哪儿写。可以是 `sys.stdout`、文件路径、甚至一个函数。对应前端：`console.log` vs 写文件。
- **`level=INFO`**：只输出 INFO 及以上（DEBUG < INFO < WARNING < ERROR）。相当于日志的「音量阈值」。
- **`path.mkdir(parents=True, exist_ok=True)`**：建目录，中间层级一起建、已存在也不报错。等价 `fs.mkdirSync(dir, { recursive: true })`。
- **`rotation="10 MB"`**：单文件超过 10MB 就换新文件（滚动日志）。
- **`retention="7 days"`**：只保留 7 天，更老的删掉。
- **`encoding="utf-8"`**：写文件用 UTF-8，否则 Windows 上中文会乱码。
- **`rotation` / `retention` 的值来自 `conf/app_config.yaml:6-7`**——改配置就能改行为，不用改代码。

**第三段：一个有味道的细节**

`app/core/log.py` 只有定义，**没有任何地方调用它**。它是被谁「顺便执行」的？

看 `app/scripts/build_meta_knowledge.py:7` 有 `from app.core.log import logger`——**这一行 import 才是日志系统被安装的时机**。也就是日志系统的启动完全依赖「有人记得 import 它」。而那个脚本**从头到尾没用 logger 打任何日志**，所以这次 import 属于「为了副作用而 import」。

### 5.3 clients 层：三个「客户端管理器」

`app/clients/` 下三个文件是**同一个套路的三份变体**：

> 类里存一个 `config`、一个 `client`（初始为 `None`）；`init()` 建连接；`close()` 关连接；文件末尾创建一个**模块级单例**，再挂一段 `if __name__ == "__main__":` 的测试代码。

先解释两个贯穿全文的 Python 概念：

- **`async` / `await`**：异步函数写在 `async def` 里，调用时**不会立刻执行**，而是返回一个「协程对象」（相当于 JS 的 Promise）；必须 `await` 它（或在 `asyncio.run()` 里跑）才会真正执行。语法和 JS 几乎一样，但 Python 是**显式事件循环**——入口必须有一个 `asyncio.run(...)`「点火」。
- **`if __name__ == "__main__":`**：意思是「只有直接运行这个文件时才执行下面的代码，被别人 import 时跳过」。**这三个文件里的测试块都只是 demo，不是业务代码。**

⚠️ **一个贯穿三个文件的隐患，先说一次**：

> 模块级单例 `xxx_client_manager = XxxClientManager(...)` 在 **import 的那一刻就构造了对象**，但它内部的 `client` 还是 `None`——因为 `init()` 没人自动调。
> 谁忘了调 `init()` 就直接用 `manager.client`，就会拿到 `None`，报一个很难看的 `AttributeError`。
> 这是典型的「**能在 import 时构造、却不能保证被初始化**」的设计缺陷。

#### 5.3.1 `app/clients/mysql_client_manager.py`（41 行）

**第一段：连接串拼接（`:12-13`）**

```python
# app/clients/mysql_client_manager.py:12-13
def _get_url(self):
    return f"mysql+asyncmy://{self.config.user}:{self.config.password}@{self.config.host}:{self.config.port}/{self.config.database}?charset=utf8mb4"
```

`f"..."` 是 **f-string**（格式化字符串），`{expr}` 会被替换成变量值——等价 TS 的模板字符串 `` `${a}` ``。

源码注释里已经把这段 URL 逐段拆解了（`:15-16`），照着念：

```
mysql + asyncmy : // atguigu : Atguigu.123 @ localhost : 3308 / dw ? charset=utf8mb4
数据库  异步驱动     用户名       密码           主机      端口     库名    字符集
```

- `mysql`：协议名（告诉 SQLAlchemy 这是 MySQL）。
- `+asyncmy`：**用哪个驱动**。asyncmy 是 MySQL 的**异步**驱动。因为项目全程 async，所以必须用异步驱动——就像 Node 里选 `mysql2/promise` 而不是同步版。
- `atguigu:Atguigu.123`：用户名:密码，明文写在 `conf/app_config.yaml:15-16`。
- `localhost:3308`：主机和端口（**注意不是默认的 3306**）。
- `/dw`：要连的库名。
- `?charset=utf8mb4`：字符集。**必须 utf8mb4**——历史上有一种叫 `utf8` 的 MySQL 编码其实只能存 3 字节字符，会导致 emoji 报错。

**第二段：`init()` 建引擎和会话工厂（`:17-19`）**

```python
# app/clients/mysql_client_manager.py:18-19
self.engine = create_async_engine(self._get_url(), pool_size=10, pool_pre_ping=True)
self.session_factory = async_sessionmaker(self.engine, autoflush=True, expire_on_commit=False)
```

这里有两个非常关键、也最容易混的概念：

| 概念 | 是什么 | 前端类比 |
|---|---|---|
| **engine（引擎）+ 连接池** | 一个「连接池」容器。建立 TCP 连接很贵，所以提前开好一批放池里复用 | 一个配置好的 **axios 实例**（有 baseURL、拦截器，复用它发请求） |
| **session（会话）** | 一次业务操作的工作上下文，真正执行 SQL 的载体，用完就关、归还连接 | 一次**请求上下文**（拿到 `ctx`，用完释放） |

参数解释：

- `pool_size=10`：池里最多保留 10 个长连接。
- `pool_pre_ping=True`：**每次从池里取连接前先 ping 一下**。因为 MySQL 默认 **8 小时**没活动的连接会被服务器单方面掐断，池里可能躺着已死的连接；先 ping 就能发现并换一根。
- `async_sessionmaker(...)`：一个**会话工厂**。注意它**不是 session 本身，而是「造 session 的机器」**。
- `autoflush=True`：某些操作前自动把挂起的改动刷给数据库。
- `expire_on_commit=False`：提交后不让对象属性过期。默认 `True` 的话，commit 之后再读对象属性会再发一条 SQL 去重查——异步场景下容易踩坑，所以关掉。

**第三段：`close()` 与模块级单例（`:21-25`）**

```python
# app/clients/mysql_client_manager.py:21-25
async def close(self):
    await self.engine.dispose()

meta_mysql_client_manager = MySQLClientManager(app_config.db_meta)  # 元数据库
dw_mysql_client_manager = MySQLClientManager(app_config.db_dw)      # 数据仓库
```

- **`dispose()`** = 关掉整个连接池、释放所有连接。程序退出前该调，否则连接会泄漏。
- **同一个类实例化了两次**，只是喂了不同配置：`db_meta`（库名 `meta`）和 `db_dw`（库名 `dw`）。**这就是「一个类、两个实例」**——meta 库是「说明书」，dw 库是「数据本身」。

**第四段：`__main__` 测试块（`:27-41`）—— 是 demo**

```python
# app/clients/mysql_client_manager.py:31-35（节选）
async with dw_mysql_client_manager.session_factory() as session:
    sql = "select * from fact_order limit 10"
    result = await session.execute(text(sql))
    rows = result.mappings().fetchall()
```

- **`async with`（异步上下文管理器）**：进入代码块时自动准备资源，离开时自动清理（即使中途抛异常）。等价于「自动 `try/finally`」。
- `session_factory()` 后面加 `()` = **调用工厂造一个 session**。
- **`text("裸 SQL")`**：把字符串包成 SQLAlchemy 认识的对象。不包直接传字符串会报错。
- `.mappings()`：让结果行支持**按列名取值**（像字典）；`.fetchall()`：一次取全部结果行。
- ⚠️ **注意这个测试块查的是 `fact_order`，属于 `dw` 库**——这是给「数据仓库」做连通性验证的 demo，不是业务逻辑。

#### 5.3.2 `app/clients/es_client_manager.py`（51 行）

**ES = Elasticsearch**，一个专门做搜索和文本分析的数据库。它的「索引（index）」约等于「表」。

- `_get_url()`（`:11-12`）：拼 `http://host:port`，比 MySQL 简单得多，因为 ES 就是 HTTP 服务。
- `init()`（`:14-15`）：`AsyncElasticsearch(hosts=[...])`——注意 **`hosts` 是个列表**。
- 单例（`:20`）：`es_client_manager = ESClientManager(app_config.es)`。

`__main__` 里的三段（`:26-49`）是 ES 最基本的三件事，**跟本项目业务无关**：

```python
# app/clients/es_client_manager.py:28-46（节选）
await client.indices.create(index="books")         # ① 建"表"（索引）
await client.index(index="books", document={...})  # ② 插一条文档
resp = await client.search(index="books")          # ③ 查
```

- ES 的数据单位叫 **document（文档）**，就是一条 JSON，类比「一行记录」。
- ⚠️ **索引名写死成 `books`**，而配置里真正的索引名是 `data_agent`（`conf/app_config.yaml:39`）；数据是英文书籍《Snow Crash》，和本项目毫无关系。**这是语法 demo，不是业务代码。**

#### 5.3.3 `app/clients/qdrant_client_manager.py`（68 行）

**Qdrant** 是**向量数据库**：存的是「一串数字」（向量），按「语义相似度」找最接近的若干条。

三个关键概念：

- `AsyncQdrantClient`：和 Qdrant 服务器通话的客户端。
- `VectorParams(size=..., distance=...)`：描述「这块地儿的向量多长、怎么算相似」。`distance=Distance.COSINE` 表示**余弦相似度**——简单说就是「看向量方向像不像，不看长度」。
- `PointStruct`：插入时的「一条记录」，含 `id`（主键）、`vector`（向量本体）、`payload`（附加 JSON，相当于元数据）。

`__main__` 测试块（`:34-66`）——**是 demo**：

```python
# app/clients/qdrant_client_manager.py:39-42
await client.create_collection(
    collection_name="test_collection_async",
    vectors_config=VectorParams(size=4, distance=Distance.COSINE),
)
```

⚠️ **一个必须指出的不一致**：这里 `size=4`（测试向量只有 4 维），而配置里 `conf/app_config.yaml:29` 写的是 `embedding_size: 1024`。

- 源码注释（`:28-29`）自己也承认了：「测试用的向量维度，与下面 demo 数据保持一致 / 正式建集合时应该用 `app_config.qdrant.embedding_size`（这里是 1024）」。
- **后果**：如果照这个 demo 建了集合，以后存 1024 维的真实 embedding 会**直接报维度不匹配**。真实流程必须用 1024。

其余细节：

- `collection_exists` / `delete_collection`（`:37-38`）：让脚本能重复运行，先删掉上次的测试集合。
- `wait=True`（`:46`）：等写入真正落盘再返回，避免「刚写完就查不到」。
- `query_points(..., limit=2, with_payload=False)`（`:56-62`）：检索，要最相似的 2 条，不返回附加信息。
- 第 55 行注释解释了一个**优先级坑**：必须先 `await client.query_points(...)` 拿到响应对象，**再**取 `.points`；不能写成 `await client.query_points(...).points`。
- `try/finally`（`:35-66`）：无论成功失败都在 `finally` 里 `close()`，防连接泄漏。`close()` 里还多做了一步 `self.client = None`（`:21`）——这是三个 manager 里唯一把关闭做得比较严谨的。
- 第 68 行 `asyncio.run(test())` = **「点火」**。**Python 里没有这一步，任何 `async def` 都不会被执行。**

### 5.4 models 层：Python 类 ↔ 数据库表

先讲清这一层解决什么问题。

**ORM 是什么**：Object-Relational Mapping，对象关系映射。它让你**用操作对象的方式操作数据库表**，不用手写 SQL 字符串。你定义一个 Python 类，声明「我对应哪张表、每个属性对应哪个字段」，ORM 帮你把类翻译成 SQL。

**前端类比**：非常接近 Prisma schema 或 Drizzle 的 table 定义。

> ⚠️ **先纠正一个容易搞错的数量**：`app/models/` 下共 **5 个 `.py` 文件 = 1 个公共基类 + 4 个 ORM 实体类**。
> 只有 **4 个实体类对应数据库的 4 张表**，`app/models/base.py` **不对应任何表**。
> （网上/文档里常说的「5 个 ORM 类」是不准确的。）

#### 5.4.1 `app/models/base.py`（4 行）

```python
# app/models/base.py:1-4
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
  pass
```

- **在干什么**：定义一个空的基类，后面 4 个实体类都继承它（例如 `app/models/table_info.py:4` 的 `from app.models.base import Base`）。
- **为什么这么写**：`DeclarativeBase` 是 SQLAlchemy 2.0 的新式写法。继承它的类会自动登记进 ORM 的「元数据注册表」，ORM 才知道「世界上有这些表」。
- **`pass` 是什么**：Python 里表示「这里什么都不做」的占位语句（因为语法要求类体不能为空）。等价 TS 的空 `{}`。
- **前端类比**：一个抽象的公共 `BaseModel`，本身没字段，只给子类统一身份。

#### 5.4.2 四个实体类

四个文件长一个样，先看一个完整的：

```python
# app/models/table_info.py:6-24（节选）
class TableInfoMySQL(Base):
  __tablename__ = "table_info"

  id: Mapped[str] = mapped_column(
    String(64),
    primary_key=True,
    comment="表编号"
  )
  name: Mapped[str | None] = mapped_column(String(128), comment="表名称")
```

拆开讲：

- **`__tablename__`**：告诉 ORM 这个类对应**哪张表**。名字必须和 `docker/mysql/meta.sql` 里的表名完全一致。
- **`Mapped[T]`**：类型注解，声明属性类型，同时 ORM 据此推断「这一列是否允许为空」。这是 SQLAlchemy 2.0 风格的标志（旧式写法是 `Column(String(64))`）。
- **`Mapped[str | None]`** = 「可能为 None」→ ORM 映射成**允许 NULL 的列**。等价 TS 的 `string | null`。
- **`String(64)` / `Text` / `JSON`**：数据库字段类型。`Text` 是不限长文本，`String(n)` 是定长上限 n。
- **`primary_key=True`**：这是主键。
- **`comment="表编号"`**：字段注释，**给人看的**（DBA 打开数据库能看懂这列是啥），和 SQL 里的 `COMMENT '表编号'` 一一对应。
- **类名带 `MySQL` 后缀**：因为项目里可能还有 ES / Qdrant 里的同名概念，加后缀区分「这是 MySQL 里的那个」。

四个实体一句话概括：

| 类 | 表 | 干什么用 |
|---|---|---|
| `TableInfoMySQL` | `table_info` | 记录有哪些表、是事实表还是维度表 |
| `ColumnInfoMySQL` | `column_info` | 记录每个字段的类型、角色、示例、别名 |
| `MetricInfoMySQL` | `metric_info` | 记录指标（如 GMV）的定义与关联字段 |
| `ColumnMetricMySQL` | `column_metric` | 字段 ↔ 指标的多对多关系表 |

**特别说一句 `column_metric.py`（18 行）——联合主键的中间表**

```python
# app/models/column_metric.py:9-16（节选）
column_id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="列编号")
metric_id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="指标编号")
```

- 这个类**只有两个字段，而且两个都是 `primary_key=True`**。
- 意思是它的主键是 **`(column_id, metric_id)` 复合主键**：「同一对组合只能出现一次」。
- 这是**多对多关系的经典做法**：一个字段可以关联多个指标，一个指标也可以关联多个字段，光靠两张表表达不了，必须加一张「中间表」。
- **前端类比**：两个数组做多对多关联时，你不得不额外维护一个 `{ aId, bId }[]` 的映射表。

#### 5.4.3 与 `docker/mysql/meta.sql` 逐字段核对

结论：**4 张表全部逐字段一致——字段名、类型、主键、注释都对得上。** 这是本项目质量最好的一层。

`meta.sql` 的 4 张表分别定义在 `docker/mysql/meta.sql:8-14`（`table_info`）、`:19-29`（`column_info`）、`:32-39`（`metric_info`）、`:43-48`（`column_metric`），字段和 `app/models/` 下的 ORM 声明完全对应。

**两点值得知道的「没有」**：

- `column_info.table_id`（`docker/mysql/meta.sql:28`）**没有 `FOREIGN KEY` 约束**，模型里也就没有外键声明。也就是说「字段属于哪张表」这个关系**只靠约定，数据库不会帮你保证**。
- 模型里**没有**给 `Mapped` 字段写 `nullable=` 参数，而是靠 `str | None` 注解推断。SQL 里也没写 `NOT NULL`，两边一致：**除主键外全部允许为 NULL**。

**唯一一处细微差异（无功能影响）**：`metric_info.relevant_columns` 的注释措辞不同——`docker/mysql/meta.sql:37` 写「关联的列」，`app/models/metric_info.py:25` 写「关联字段」。只是文案不统一。

### 5.5 repositories 层：数据访问层（目前是空的）

**repository（仓储）是什么**：把「怎么读写数据库」从业务逻辑里隔出来的一层。业务代码只管调 `repository.xxx()`，不关心底下是 SQL 还是别的。

**前端类比**：就像你把 `fetch('/api/xxx')` 全部收进 `api/user.ts`，组件里只 `import { getUser }`。这一层就是后端的「api 封装文件」。

**`app/repositories/mysql/meta/meta_mysql_repository.py`（7 行，全文就这些）**

```python
# app/repositories/mysql/meta/meta_mysql_repository.py:4-6
class MetaMySQLRepository:
    def __init__(self, Session: AsyncSession):
        self.session = Session
```

- **一个方法都没有**。没有 `save_table()`、没有 `get_column()`，什么都没有。
- **这就是一个纯占位 / 空壳**。`MetaKnowledgeService.build()` 里那个双重循环之所以只能写 `pass`，很大原因就是这一层没提供任何可用方法。
- 小瑕疵：参数名写成了大写 `Session`（一般参数用小写 `session`），容易误导读者以为是个类名。

**三个空壳包**：下面这些目录里**只有一个 0 字节的 `__init__.py`**：

- `app/repositories/es/`
- `app/repositories/qdrant/`
- `app/repositories/mysql/dw/`

**`__init__.py` 是干什么的**：它把一个目录标记为「Python 包」，可以被 `import`。0 字节也完全合法。（顺带一提，项目根目录下的 `conf/` 里也有一个 `__init__.py`，但那里放的是 yaml 不是 Python 代码，基本是多余的。）

**结论**：这三处是**为后续实现预留的骨架**——ES 检索、向量检索、数仓查询都还没开始写。从目录结构能看出作者的规划：**仓储层按存储类型分包，再按 meta / dw 分库**。

### 5.6 services 层：项目最核心的文件（但目前是骨架）

#### `app/services/meta_knowledge_service.py`（40 行）

它在整个项目里的位置：

> 把 `conf/meta_config.yaml` 里**手写的业务元数据**变成「AI 能检索的知识库」——一部分进 MySQL 的 meta 库，一部分做成向量索引进 Qdrant，一部分做成全文索引进 ES。

**这就是整个「掌柜问数」的数据准备环节**：先让机器读懂你的表结构，它才可能把「华东上个月卖了多少」翻译成 SQL。

**第 1 段：构造函数（`:7-8`）**

```python
# app/services/meta_knowledge_service.py:7-8
def __init__(self, meta_mysql_repository: MetaMySQLRepository):
    self.meta_mysql_repository: MetaMySQLRepository = meta_mysql_repository
```

**依赖注入（Dependency Injection）**：service 不自己 new 一个 repository，而是**由外部把 repository 传进来**。好处是可以替换成 mock 或另一个实现，测试和替换都方便。

前端类比：`function UserService(apiClient) {...}` 这种把 client 当参数传进去的写法，而不是在函数内部写死一个实例。

**第 2 段：读配置（`:10-18`）**

```python
# app/services/meta_knowledge_service.py:10-18（节选）
async def build(self, config_path: Path) -> MetaConfig:
    context = OmegaConf.load(config_path)
    schema = OmegaConf.structured(MetaConfig)
    meta_config: MetaConfig = OmegaConf.to_object(OmegaConf.merge(schema, context))
    print(meta_config.metrics)
```

- 这 4 行和 `app/conf/app_config.py:67-70` 的套路**一模一样**（load → structured → merge → to_object），区别是这里读 `meta_config.yaml`、目标类是 `MetaConfig`，而且是**运行时按传入路径读**。
- `-> MetaConfig` 是**返回类型注解**。
- ⚠️ **`print(meta_config.metrics)`（第 18 行）是明显的调试残留**：直接把指标列表打到标准输出，格式是 Python 的 `repr`，不走 `logger`。**这是当前项目里唯一一处「能输出东西」的代码。**

**第 3 段：双重 for 循环里只有 `pass`（`:20-27`）**

```python
# app/services/meta_knowledge_service.py:21-27
if meta_config.tables:
    # 2.1 将表信息和字段信息保存meta数据库中
    for table in meta_config.tables:
        # table -> table_info
        for column in table.columns:
            # column -> column_info
            pass
```

- `if meta_config.tables:` 先判空。Python 里空列表是 falsy，等价于 `if (tables?.length)`。
- 双重循环的意图很清楚：**外层遍历表，内层遍历字段**，注释也标了 `table -> table_info`、`column -> column_info`。
- **但最内层是 `pass`。也就是说：循环跑完什么都没干，一次数据库写入都没有。**

**第 4 段：5 个 TODO，全部未实现（`:29-38`）**

| 编号 | 目标 | 状态 |
|---|---|---|
| 2.1 | 表信息和字段信息存进 meta 库（`table_info` / `column_info`） | ❌ 循环体是 `pass`（`:22-27`） |
| 2.2 | 字段信息建立**向量索引**（进 Qdrant） | ❌ 空的，只有一行注释（`:29`） |
| 2.3 | 指定维度字段取值建立**全文索引**（进 ES） | ❌ 空，只有一个多余的 `pass`（`:31-32`） |
| 3.1 | 指标信息存进 meta 库（`metric_info` / `column_metric`） | ❌ 只有一行注释（`:36`，与 3.2 共用 `:38` 的 `pass`） |
| 3.2 | 指标信息建立向量索引 | ❌ 只有一行注释（`:37`，与 3.1 共用 `:38` 的 `pass`） |

顺带一个**很容易看错的地方**：**第 32 行那个 `pass` 的缩进（12 个空格）和 `for table` 同级**，也就是它位于 `if meta_config.tables:` 块内、两个 `for` 循环之外。因为那个块里已经有 `for` 语句了，这个 `pass` 是**多余的死代码**（删掉不影响任何行为）。真正必需的 `pass` 只有两处：第 27 行和第 38 行。

**第 5 段：返回值（`:40`）**

```python
# app/services/meta_knowledge_service.py:40
return meta_config
```

读进来的配置原样返回。**注意**：调用它的地方（`app/scripts/build_meta_knowledge.py:19`）`await` 了但**没有接收返回值**，所以这个返回值实际上被丢掉了。

**本节总结（重要，别被文件名骗了）**

> `meta_knowledge_service.py` 虽有 40 行、看起来最像「核心业务」，但**它是一副骨架**：配置读取可用，`print` 是调试残留，**2.1 / 2.2 / 2.3 / 3.1 / 3.2 五个步骤全部未实现**。
> 这个项目的完成度到此为止——**它连通了所有基础设施，但还没开始做任何业务写入。**

### 5.7 scripts 层：项目真正的入口

#### `app/scripts/build_meta_knowledge.py`（36 行）

**这才是项目真正的入口**，不是根目录的 `main.py`。

**第 1 段：import（`:1-11`）**

```python
# app/scripts/build_meta_knowledge.py:1-11
import argparse
import asyncio

from pathlib import Path

from app.clients.mysql_client_manager import meta_mysql_client_manager
from app.core.log import logger
from app.repositories.mysql.meta import meta_mysql_repository
from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
from app.services import meta_knowledge_service
from app.services.meta_knowledge_service import MetaKnowledgeService
```

- **`argparse`** 是 Python 标准库，解析命令行参数，等价前端的 `commander` / `yargs`。
- **`asyncio`** 是 Python 的异步运行时，提供 `asyncio.run()` 这个「点火器」。
- **`Path`** 是路径对象，等价 Node 的 `path`。

⚠️ **这里有两行明显的冗余 import，而且作者自己显然也知道**：

- **第 8 行** import 的是**模块**，第 9 行紧接着 import 同一模块里的**类**。第 8 行**整个文件里从没被使用**。
- **第 10 行**同理，第 11 行已经 import 了类，第 10 行多余。

这两行属于「一开始先 import 模块、后来改成 import 类，旧行忘了删」的典型残留。

⚠️ **第 7 行的 `logger` 也是「导入了却没用」**：整个 36 行里没有调用过任何日志方法。它唯一的实际作用是**副作用**——import `app.core.log` 会把 loguru 的 handler 装好。

**第 2 段：`build()` 组装链路（`:14-21`）**

```python
# app/scripts/build_meta_knowledge.py:14-21
async def build(config_path: Path):
    meta_mysql_client_manager.init()
    async with meta_mysql_client_manager.session_factory() as session:
        meta_mysql_repository = MetaMySQLRepository(session)
        meta_knowledge_service = MetaKnowledgeService(meta_mysql_repository)
        await  meta_knowledge_service.build(config_path)

    await meta_mysql_client_manager.close()
```

（本节前面 4.1 已经画过这条组装链路图，这里只补两个坑。）

- 注意 ⑥ `close()` 的位置在 `async with` **外面**：必须等会话关闭后再关池子，顺序反了会报错。
- ⚠️ **变量名有遮蔽（shadowing）问题**：第 17 行 `meta_mysql_repository = MetaMySQLRepository(session)` 把**导入的模块名**当成了局部变量名；第 18 行的 `meta_knowledge_service` 同理。这里恰好没造成 bug（后面用的是类名），但这是很危险的习惯——**如果之后有人想用 `meta_knowledge_service.某个模块级常量`，就会拿到一个实例而不是模块，报出莫名其妙的错误。**
- 小问题：`build()` 没有 `return`，所以调用方拿不到 service 的返回值。

**第 3 段：命令行入口（`:23-36`）**

```python
# app/scripts/build_meta_knowledge.py:23-36（节选）
if __name__ == "__main__":
    parser = argparse.ArgumentParser(...)
    parser.add_argument( '-c','--conf') #接受一个值的选项
    args = parser.parse_args()
    config_path = args.conf
    asyncio.run(build(Path(config_path)))
```

- `argparse.ArgumentParser()` 创建解析器；`add_argument('-c', '--conf')` 声明一个「需要带值的选项」，短名 `-c`、长名 `--conf`。
- **⚠️ 一个真实的缺陷（容易踩）**：`-c/--conf` 是以 `-` 开头的「可选参数」，argparse 的规则是**可选参数默认可不传**。第 31 行**没有写 `required=True`**，所以不传 `-c` 时 argparse **不会报错**，而是让 `args.conf` 变成 `None`，问题要等到最后一行 `Path(None)` 才以 `TypeError` 的形式炸出来——**报错位置离原因很远**。正确修法是：`parser.add_argument('-c', '--conf', required=True)`。
- **`asyncio.run(build(...))` 就是全项目的「点火」**：它创建事件循环、把协程跑起来、结束后关闭循环。
- 正确的启动命令（必须从**项目根目录**跑）：

```bash
python -m app.scripts.build_meta_knowledge -c conf/meta_config.yaml
```

### 5.8 根目录 `main.py`（5 行）——请务必不要误会它

```python
# main.py:1-5
from loguru import logger

logger.info("starting……")
logger.warning("warning……")
logger.error("error……")
```

- **这 5 行只是 loguru 三条日志级别的演示**，用来验证「日志能不能打出来」。
- **它不是项目的程序入口。** 真正的入口是 `app/scripts/build_meta_knowledge.py`。
- **它甚至没有用项目自己的日志配置**：它直接 `from loguru import logger`，没有 import `app.core.log`，所以 `conf/app_config.yaml` 里配的 `rotation`、`retention`、文件路径**在这里全部不生效**，它用的是 loguru 出厂默认设置（直接打印到 stderr）。
- **前端类比**：这个文件就像一个 `scratch.js` 或 `playground.tsx`——写来试一下 API 怎么用，跟应用真正的入口（`index.tsx` / `main.ts`）没关系。

### 5.9 一段真实数据是怎么串起来的

为了让你对「维度表 + 事实表」有体感，拿 `docker/mysql/dw.sql:204` 这一条真实订单走一遍：

```
('ORD20250101001', 'C001', 'P001', 20250101, 'R001', 1, 8999.00)
```

把 4 个外键拿去各维度表里查，翻译成人话：

| 字段 | 值 | 含义 | 查哪里 |
|---|---|---|---|
| `order_id` | ORD20250101001 | 订单号 | — |
| `customer_id` | C001 | **李伟**，男，黄金会员 | `dw.sql:36` |
| `product_id` | P001 | **iPhone 15 Pro**，手机数码，苹果 | `dw.sql:69` |
| `date_id` | 20250101 | 2025 年 1 月 1 日，Q1 | `dw.sql:98` |
| `region_id` | R001 | 广东省，**华南** | `dw.sql:18` |
| `order_quantity` | 1 | 买了 1 件（度量） | — |
| `order_amount` | 8999.00 | 花了 8999 元（度量） | — |

于是事实就是：「2025 年 1 月 1 日，华南地区的李伟买了一台 iPhone，花了 8999 元」。

**这就是星型模型的价值**：把一句业务事实拆成「一笔交易记录 + 4 个指针」，避免重复存储。如果不用星型模型，你得在订单表里把「李伟/男/黄金/iPhone 15 Pro/手机数码/苹果/广东省/华南/中国/2025/Q1」全部抄一遍——115 行订单就要抄 115 遍。

### 5.10 那「华东地区去年销售额」最后会变成什么 SQL？

结合上面所有的概念，用户问的这句话，目标是变成这样一条 SQL（**通用示例**，仓库里还没有真实查询代码）：

```sql
SELECT SUM(f.order_amount) AS 销售额
FROM fact_order f
JOIN dim_region d ON f.region_id = d.region_id
JOIN dim_date   t ON f.date_id   = t.date_id
WHERE d.region_name = '华东'
  AND t.year = 2025;
```

它是怎么推出来的？——**每一步都靠 `meta_config.yaml` 里的信息**：

| 中文片段 | 落地 | 依据 |
|---|---|---|
| 华东 | `dim_region.region_name = '华东'` | 字段别名「地区/区域/大区」（`conf/meta_config.yaml:21`）+ 真实取值来自 `dw.sql:19`（R002 浙江省 → 华东） |
| 去年 | `dim_date.year = 2025` | 字段别名「年/年份」（`conf/meta_config.yaml:96-100`）+ `dw.sql` 里只有 2025 一年的数据 |
| 销售额 | `SUM(fact_order.order_amount)` | 字段别名「销售额/订单金额/收入」（`conf/meta_config.yaml:163`）+ GMV 指标定义（`conf/meta_config.yaml:167-171`） |
| 两个 JOIN | `f.region_id = d.region_id`、`f.date_id = t.date_id` | `role: foreign_key` 的声明（`conf/meta_config.yaml:130-152`） |

**这一小段就是整个项目的「北极星」**：链路 A 的所有工作，都是为了让上面这张表里的「依据」可以被机器检索到。

### 5.11 一个必须说清楚的知识点：外键 = 逻辑外键，不是数据库约束

讲 `fact_order` 的时候我说 `customer_id` / `product_id` / `date_id` / `region_id` 是「外键」。**但必须补一句严谨的说明**：

> **这两个 SQL 文件里，除了 PRIMARY KEY，没有定义任何 FOREIGN KEY 约束，也没有创建其他索引。**

具体看 `docker/mysql/dw.sql:192-201` 的建表语句，只有字段定义，**没有任何 `FOREIGN KEY ... REFERENCES ...`**；`docker/mysql/meta.sql` 同样如此（`meta.sql:28` 的 `table_id` 只是个普通列）。

所以准确的说法是：

- 这 4 个字段是**逻辑外键**——**业务上的约定**（「这个字段语义上指向哪张表的主键」），**不是数据库层面的强制约束**。
- 为什么这么设计？数仓/导数据场景里，数据库外键会让每次写入都额外查一次，批量导入明显变慢；所以通常**只在应用层/文档层保证一致性**。
- 那「这个字段是外键、指向哪张表」这件事记在哪里？**记在 `meta` 库里**——例如 `conf/meta_config.yaml:130-133` 明确写了 `customer_id` 的 `role: foreign_key`、描述是关联客户维度的外键。
- **这是本项目设计的一个缩影**：**数据（`dw` 库）和「对数据的描述」（`meta` 库）被分开了。**

### 5.12 「度量」和「维度」：一句话记住

- **维度（dimension）**= 用来**筛选、分组、打标签**的描述性属性（地区名、客户名、品类、品牌、季度）。
- **度量（measure）**= 能**求和、求平均**的数字（`order_quantity`、`order_amount`）。

`conf/meta_config.yaml` 里每个字段都标了 `role`（`primary_key` / `foreign_key` / `measure` / `dimension`），**这就是「度量 vs 维度」的机器可读定义**——机器读到 `role: measure` 就知道「这个字段可以 SUM」，读到 `role: dimension` 就知道「这个字段可以做分组/筛选」。

---

## 6. 基础设施详解：docker 目录里都是什么

这一节把 `docker/` 目录翻一遍。第 2 节已经解释过六个概念，这里**只讲「这个仓库具体怎么配的」**，不再重复概念本身。

`docker/` 目录一共有四类东西：

| 文件/目录 | 是什么 |
|---|---|
| `docker/docker-compose.yaml`（80 行） | **编排清单**——把 5 个服务一次配好 |
| `docker/elasticsearch/Dockerfile`（12 行）+ `plugins/*.zip` | 自建 ES 镜像（因为要装中文分词插件） |
| `docker/mysql/dw.sql`（318 行）、`docker/mysql/meta.sql`（48 行） | 容器首次启动时**自动执行**的建库脚本 |
| `docker/embedding/bge-large-zh-v1.5/`（约 1.3GB） | 本地 embedding 模型文件（**被 `.gitignore` 忽略，需自己准备**） |

### 6.1 五个服务逐个看

#### ① mysql（`docker/docker-compose.yaml:3-20`）

```yaml
mysql:
  image: mysql:8.0
  container_name: mysql
  restart: unless-stopped
  environment:
    MYSQL_ROOT_PASSWORD: Atguigu.123
    MYSQL_USER: atguigu
    MYSQL_PASSWORD: Atguigu.123
  ports:
    - "3308:3306"
  volumes:
    - mysql_data:/var/lib/mysql
    - ./mysql:/docker-entrypoint-initdb.d
  command:
    --character-set-server=utf8mb4
    --collation-server=utf8mb4_general_ci
```

- **用官方镜像 `mysql:8.0`**（`:4`），不需要自己构建。
- **环境变量创建了两个账号**（`:8-10`）：`root` 超级用户，以及业务代码要用的普通用户 `atguigu`（对应 `conf/app_config.yaml:15`）。
- **字符集强制 utf8mb4**（`:17-18`）——中文项目必配。`utf8mb4` 才是「能完整存下中文和 emoji」的编码。
- **`/docker-entrypoint-initdb.d` 是「魔法目录」**（`:15`）：MySQL 官方镜像有个约定——**如果数据目录是空的（第一次启动），会自动按文件名字母顺序执行这个目录下所有的 `.sql` 文件**。

  所以这个项目「一启动就自带数据」：`docker/mysql/dw.sql` 自动执行 → 建出 `dw` 库 + 5 张表 + 115 行数据；`docker/mysql/meta.sql` 自动执行 → 建出 `meta` 库 + 4 张空表。

  > ⚠️ **踩坑提醒**：这个自动导入**只在「第一次启动」有效**。你后来改了 `dw.sql` 再 `docker compose up`，**不会**重新执行——因为卷 `mysql_data` 已有数据，MySQL 认为「这不是第一次启动」。想重来必须删卷：`docker compose down -v`（**`-v` 会永久删掉库里的数据**，示例数据无所谓，真项目别乱按）。

#### ② elasticsearch（`:22-35`）

```yaml
elasticsearch:
  build: ./elasticsearch       # ← 自建镜像！
  environment:
    discovery.type: single-node
    xpack.security.enabled: "false"
    ES_JAVA_OPTS: "-Xms1g -Xmx1g"
  ports:
    - "9200:9200"
```

- **这里用的是 `build` 而不是 `image`**（`:23`）：说明这个 ES 是从 `docker/elasticsearch/Dockerfile` **现场构建**出来的。**第一次启动会更慢**（要下载基础镜像 + 装插件），这是正常的，别以为卡死了。
- **`single-node`**（`:27`）：ES 天生为「多台机器组集群」设计，开发机只有一台，显式告诉它「我就一个节点，别找了」。不写这条，ES 会一直尝试找其他节点，日志里刷一堆警告甚至起不来。
- **`xpack.security.enabled: false`**（`:28`）：ES 8.x 默认开启账号密码 + HTTPS，开发环境直接关掉，这样代码里 `http://localhost:9200` 裸着连就行（印证：`app/clients/es_client_manager.py:11-12` 拼的 URL 就是纯 http，没有任何认证信息）。
- **`ES_JAVA_OPTS: "-Xms1g -Xmx1g"`**（`:29`）：ES 是 Java 写的，这两个参数是 JVM 的「最小/最大堆内存」。**记住这个 1G**，后面算内存要用。

#### ③ kibana（`:37-48`）

```yaml
kibana:
  image: kibana:8.19.10
  environment:
    ELASTICSEARCH_HOSTS: http://elasticsearch:9200
  ports:
    - "15601:5601"
  depends_on:
    - elasticsearch
```

- 浏览器打开 **`http://localhost:15601`**（**注意是 15601**，`:44` 把容器里的 5601 映射到了宿主机的 15601），左侧菜单找 **Dev Tools**，可以手敲 ES 查询看结果——不用写任何 Python 就能验证「数据进 ES 了吗、分词切对了吗」。
- **`:42` 写的是 `http://elasticsearch:9200`，用「服务名」而不是 `localhost`**：因为**容器里的 `localhost` 指的是容器自己**。Docker Compose 会给每个服务建内部 DNS，容器之间直接用服务名互相访问。
  **对比**：本项目 Python 代码在**宿主机**上跑，所以 `conf/app_config.yaml:37` 用的是 `host: localhost`。**「谁和谁在同一个网络里」决定了你该写 `localhost` 还是服务名**——这是新手最容易混的一点。
- **`:45-46` 的 `depends_on`** 只保证「先启动 ES 容器，再启动 Kibana」，**不保证 ES 已经就绪**。第一次启动时 Kibana 可能报几次连不上，等几十秒自己就好。

#### ④ qdrant（`:50-60`）

```yaml
qdrant:
  image: qdrant/qdrant:v1.16
  ports:
    - "6333:6333"   # HTTP
    - "6334:6334"   # gRPC
  volumes:
    - qdrant_data:/qdrant/storage
```

- 两个端口：**6333 走 HTTP**（本项目代码用的是这个，见 `app/clients/qdrant_client_manager.py:12-13` 拼的 `http://host:port`），**6334 走 gRPC**（二进制协议，性能更好，项目没用）。
- 除了内存限制没写别的特殊配置，属于「开箱即用」。

#### ⑤ embedding（`:62-75`）

```yaml
embedding:
  image: ghcr.io/huggingface/text-embeddings-inference:cpu-1.8
  ports:
    - "8081:80"
  environment:
    MODEL_ID: /models/bge-large-zh-v1.5
    MAX_CONCURRENT_REQUESTS: "16"
    MAX_BATCH_TOKENS: "16384"
  volumes:
    - ./embedding/bge-large-zh-v1.5:/models/bge-large-zh-v1.5
```

- **`ghcr.io/huggingface/text-embeddings-inference`** 是 HuggingFace 官方的 **TEI（Text Embeddings Inference）** 服务镜像，作用是把「文本 → 向量」包装成一个 HTTP 服务。
  为什么不用 `pip install torch` 在 Python 里直接加载模型？因为那样**每次启动进程都要重新加载 1.3GB 模型**（几十秒）、还和业务代码抢内存。让独立服务加载一次，业务代码只管发 HTTP 请求。
- **`cpu-1.8` 后缀**说明是 **CPU 版本**（不是 GPU），所以在你的笔记本上就能跑。
- **`:67` 端口 `8081:80`**：TEI 容器内听 80，映射到宿主机 8081（对应 `conf/app_config.yaml:33`）。
- **`:73` 挂载**：把仓库里 `docker/embedding/bge-large-zh-v1.5/` 的模型文件挂进容器。**这就是为什么这个项目不需要联网下载模型**——模型已经躺在仓库目录里了。但这个目录被 `.gitignore` 忽略（`.gitignore:4`），所以**克隆仓库后它不会存在，需要你自己准备**。
- **`:70-71` 两个性能参数**：最多同时处理 16 个请求；一批最多 16384 个 token。这是防止并发太高把内存打爆的保护阈值。

### 6.2 三个命名卷（`:77-80`）

```yaml
volumes:
  mysql_data:
  es_data:
  qdrant_data:
```

末尾这三行是**声明**，配合前面各服务的挂载使用：

| 卷名 | 挂到哪儿 | 存什么 | 出处 |
|---|---|---|---|
| `mysql_data` | `/var/lib/mysql` | MySQL 的数据/账号/权限 | `docker-compose.yaml:14` |
| `es_data` | `/usr/share/elasticsearch/data` | ES 的索引数据 | `:33` |
| `qdrant_data` | `/qdrant/storage` | Qdrant 的向量数据 | `:58` |

**为什么要卷？** 因为**容器是用完即弃的**。如果你把 MySQL 容器删掉，容器内 `/var/lib/mysql` 里的数据也会跟着消失。挂在卷上之后，数据实际存在**宿主机的 Docker 管理目录**里；容器删了再重建，卷还在，数据还在。

> **类比**：容器像浏览器的**无痕窗口**，卷像你**同步到硬盘的用户目录**。窗口一关东西没了，但落在同步盘里的文件重开窗口照样在。

还有个区别值得说清：

- 以 `./` 开头的是**绑定挂载（bind mount）**：把宿主机上某个**具体目录**挂进去。如 `./mysql:/docker-entrypoint-initdb.d`（`:15`）、`./embedding/bge-large-zh-v1.5:...`（`:73`）。适合「初始化脚本 / 模型文件」这种**你源码里就有**的东西。
- `mysql_data:` 这种是**命名卷（named volume）**：由 Docker 自己管理存储位置。适合「数据库数据」这种**运行时生成、你不关心它具体存在哪**的东西。
- **注意 `embedding` 服务没有命名卷**——模型是只读的，服务本身不产生需要保留的数据。

### 6.3 Dockerfile：为什么要自己烤一个 ES 镜像

**根本原因：ES 默认的分词器不认识中文词。**

它按「一个字一个字」或「一整串不切」的方式处理中文，结果就是「中华人民共和国」被切成 `中`/`华`/`人`/`民`……全是单字，**「华人」这种词就搜不准**。

**IK 分词器**（`elasticsearch-analysis-ik`）就是中国人写的中文分词插件。因为官方 ES 镜像里**没有**它，所以必须自己构建。`docker/elasticsearch/Dockerfile` 全文只有 12 行：

```dockerfile
FROM elasticsearch:8.19.10                                          # :1

USER root                                                           # :3

COPY plugins/elasticsearch-analysis-ik-8.19.10.zip /tmp/            # :5

RUN /usr/share/elasticsearch/bin/elasticsearch-plugin install --batch \
    file:///tmp/elasticsearch-analysis-ik-8.19.10.zip               # :7-8

RUN chown -R elasticsearch:elasticsearch /usr/share/elasticsearch/plugins  # :10

USER elasticsearch                                                  # :12
```

**Dockerfile 就是「从一个基础镜像开始，一步步改」的脚本。** 逐行：

| 行 | 做什么 | 为什么 |
|---|---|---|
| `:1` | 以官方 `elasticsearch:8.19.10` 为基础 | 版本必须和 Kibana 的 `8.19.10`（`docker-compose.yaml:38`）**严格一致**，否则 Kibana 连不上 |
| `:3` | 切成 `root` 用户 | 因为下一步要往系统目录写文件。ES 官方镜像默认不是 root（安全考虑），必须显式提权 |
| `:5` | 把插件 zip 复制进镜像的 `/tmp/` | 源路径 `plugins/...` 是**相对路径**，相对于「构建上下文」，也就是 `docker-compose.yaml:23` 的 `build: ./elasticsearch`，实际文件在 `docker/elasticsearch/plugins/elasticsearch-analysis-ik-8.19.10.zip`（约 4.6MB） |
| `:7-8` | 调 ES 自带的命令安装这个 zip | `file://` = 从本地文件装；`--batch` = 不要交互式问我 yes/no（构建过程没人能回答） |
| `:10` | 把插件目录属主改成 `elasticsearch` | 上一步是 root 装的，属主是 root；不改的话普通用户跑 ES 时读不了插件 |
| `:12` | 切回 `elasticsearch` 用户 | **安全最佳实践**：容器里的程序不该以 root 跑 |

**这个 zip 里有什么？** 解压后共 22 个条目，关键的是这些词典文件：

```
config/main.dic            ← 主词典（几万个中文词）
config/surname.dic         ← 姓氏词典（「张」「李」等，为了人名分词准）
config/quantifier.dic      ← 量词（「个」「件」「台」）
config/stopword.dic        ← 停用词（「的」「了」这种没信息量的词）
config/IKAnalyzer.cfg.xml  ← 配置文件
elasticsearch-analysis-ik-8.19.10.jar  ← 插件本体
```

**「分词到底按什么切」完全由这些 `.dic` 词典决定**，所以 IK 后面还可以加自定义词典（把公司内部黑话、商品名塞进去）——这也是中文搜索经常需要「调词典」的原因。

### 6.4 两个初始化 SQL

#### `docker/mysql/dw.sql`（318 行）：星型模型

建 `dw` 库（`:3`）和 5 张表。所谓**星型模型（star schema）**，就是「中间一张事实表，四周发散若干维度表」，形状像星星：

```
        dim_date              dim_region
             \                    /
              \                  /
   dim_customer ——  fact_order  —— dim_product
```

规则只有两条：

- **维度表（dimension table）= 存「按什么角度看」**——描述性的文字属性，用来筛选/分组/打标签。它们通常很小、很少变（广东永远是广东）。
- **事实表（fact table）= 存「发生了什么」+ 可累加的数字**——外键（指向各维度）+ 度量。

```sql
-- docker/mysql/dw.sql:192-201
CREATE TABLE fact_order
(
    order_id       VARCHAR(30) PRIMARY KEY,   -- 主键
    customer_id    VARCHAR(20),   -- 逻辑外键 → dim_customer
    product_id     VARCHAR(20),   -- 逻辑外键 → dim_product
    date_id        INT,           -- 逻辑外键 → dim_date
    region_id      VARCHAR(20),   -- 逻辑外键 → dim_region
    order_quantity INT,           -- 度量：数量
    order_amount   FLOAT          -- 度量：金额
);
```

> **这条规律值得记一辈子**：**事实表 = 外键 + 度量；维度表 = 描述性文字。**
> （再说一次：这里的「外键」是**逻辑外键**，建表语句里**没有 `FOREIGN KEY` 约束**，见 5.11 节。）

**为什么专门要一张 `dim_date`？** 因为「按季度统计」这种需求非常常见。如果只存日期字符串，你得在 SQL 里写 `CASE WHEN month IN (1,2,3) THEN 'Q1' ...`；有了维度表，「季度」就是普通字段，直接 `GROUP BY quarter` 就行。**这正是维度表的通用价值：把计算、映射、枚举提前算好，让查询变简单。**

**为什么全仓库除了主键没有任何索引？** `docker/mysql/dw.sql` 全文搜 `INDEX` / `KEY`，只有主键那些。这是合理的——示例数据太小（`fact_order` 才 115 行），建不建索引都快。但数据量上去之后这种设计是要补索引的。

#### `docker/mysql/meta.sql`（48 行）：描述数据库的数据库

建 `meta` 库（`:2`）和 **4 张表**：

| 表 | 存什么 | 定义位置 |
|---|---|---|
| `table_info` | 每张表的编号 / 名称 / 类型（fact 还是 dim）/ 描述 | `meta.sql:8-14` |
| `column_info` | 每个字段的编号 / 名称 / 类型 / 角色 / 示例 / 描述 / 别名 / 属于哪张表 | `meta.sql:19-29` |
| `metric_info` | 业务指标（如 GMV）的编码 / 名称 / 描述 / 关联字段 / 别名 | `meta.sql:32-39` |
| `column_metric` | 「字段 ↔ 指标」的多对多关联表 | `meta.sql:43-48` |

以 `column_info` 为例（`docker/mysql/meta.sql:19-29`）：

```sql
CREATE TABLE column_info
(
    id          VARCHAR(64) PRIMARY KEY COMMENT '列编号',
    name        VARCHAR(128) COMMENT '列名称',
    type        VARCHAR(64) COMMENT '数据类型',
    role        VARCHAR(32) COMMENT '列类型(primary_key,foreign_key,measure,dimension)',
    examples    JSON COMMENT '数据示例',
    description TEXT COMMENT '列描述',
    alias       JSON COMMENT '列别名',
    table_id    VARCHAR(64) COMMENT '所属表编号'
);
```

- **`COMMENT`** 是 MySQL 的「列注释」，纯粹给人/工具看的，**等于把文档写进了数据库里**。
- **`role` 是设计的核心**：`primary_key` / `foreign_key` / `measure` / `dimension`，把「度量 vs 维度」变成了机器可读的数据。
- **`examples` / `alias` 用 `JSON` 类型**：MySQL 8 支持存 JSON（像 `["地区","区域","大区"]` 这样的数组）。**前端类比**：就像你在一个字段里直接存了个数组，而不用为它开一张关联表。
- ⚠️ **一处「规格缺口」**：`column_info` 有 `type`（数据类型）和 `examples`（数据示例）两列，但 `conf/meta_config.yaml` 里的字段只提供 `name / role / description / alias / sync`（对应 `app/conf/meta_config.py:5-10`），**不提供这两项数据**。也就是说**这两列的数据从哪来还没定**。合理推断是将来要从 `dw` 库的真实结构去探测（比如读 `information_schema`、抽样取值），但**相关代码尚未实现**——这里只指出缺口，不是结论。
- `table_id`（`meta.sql:28`）**是事实上的逻辑外键**，指向 `table_info.id`，表达「这个字段属于哪张表」；但**和 `dw.sql` 一样没有 `FOREIGN KEY` 约束**。

#### `column_metric`：联合主键是什么

```sql
-- docker/mysql/meta.sql:43-48
CREATE TABLE column_metric
(
    column_id VARCHAR(64) COMMENT '列编号',
    metric_id VARCHAR(64) COMMENT '指标编号',
    PRIMARY KEY (column_id, metric_id)
);
```

两个字段一起做主键，叫**联合主键**。含义是：单个 `column_id` 可以重复、单个 `metric_id` 也可以重复，但**这一对组合不能重复**。

**为什么要这样？** 因为指标和字段是**多对多**：GMV 用到 `order_amount`，将来可能还有别的指标也用 `order_amount`；反过来一个字段也可能被多个指标用到。多对多的标准解法就是**中间表**。

**前端类比**：像标签系统——一篇文章可以有多个标签、一个标签属于多篇文章，于是需要一张 `article_tag(article_id, tag_id)`，且这对组合唯一。

### 6.5 embedding 模型目录里都是什么

目录：`docker/embedding/bge-large-zh-v1.5/`（约 1.3GB，被 `.gitignore:4` 忽略）。

先回答「bge-large-zh-v1.5 是什么」：

- **bge** = **B**AAI **G**eneral **E**mbedding，由**智源研究院（BAAI）**训练的向量模型系列。
- `zh` = 中文版；`large` = 大号（约 3.26 亿参数）；`v1.5` = 改进版。

**它输出多少维？1024 维。** 三处互相印证：

1. `docker/embedding/bge-large-zh-v1.5/config.json:13` → `"hidden_size": 1024`
2. `docker/embedding/bge-large-zh-v1.5/1_Pooling/config.json:2` → `"word_embedding_dimension": 1024`
3. `conf/app_config.yaml:29` → `embedding_size: 1024`（Qdrant 建集合时必须用这个数）

| 文件 | 大小 | 作用 |
|---|---|---|
| `pytorch_model.bin` | **约 1242 MB** | **模型权重本体**——3.26 亿个学好的参数。整个目录 95% 的体积都在这 |
| `config.json` | 小 | **模型结构配置**：多少层、向量多长（`hidden_size: 1024`） |
| `tokenizer.json` | 约 0.4 MB | **分词器的完整定义**（词表 + 切词规则） |
| `vocab.txt` | 约 107 KB | **词表**：一行一个 token，共 21128 行（和 `config.json` 里的 `vocab_size: 21128` 对应） |
| `tokenizer_config.json` | 小 | 分词器**行为配置** |
| `special_tokens_map.json` | 小 | 5 个特殊 token 的名字：`[CLS]` `[SEP]` `[PAD]` `[MASK]` `[UNK]` |
| `1_Pooling/config.json` | 小 | **池化配置**——决定「怎么把一句话的多个 token 向量合成一个句子向量」 |
| `modules.json` | 小 | **处理流水线清单**：Transformer → Pooling → Normalize |
| `sentence_bert_config.json` | 小 | 一句话最长 512 个 token，超了截断 |
| `README.md` | 小 | 模型说明文档（427 行，含评测成绩和相似度分布提示） |

另外目录里还有三样东西，**和向量计算本身没关系**，但既然标题是「目录里都是什么」，一并说明：

| 其他条目 | 大小 | 作用 |
|---|---|---|
| `.gitattributes` | 约 1.5 KB | Git LFS（大文件追踪）声明，纯 Git 配置 |
| `config_sentence_transformers.json` | 约 124 B | 记录导出这个模型时用的库版本，给 `sentence-transformers` 读 |
| `.cache/`（内含 `.cache/huggingface/...`） | 小 | HuggingFace 下载时留下的元数据缓存，**功能上可忽略** |

**把它们串起来理解一次**（这就是「embedding 到底怎么把文本变成 1024 个数字」的答案）：

> 一段中文文本进来 → 用 `tokenizer.json` + `vocab.txt` 切成 token（最多 512 个）→ 送进 `pytorch_model.bin` 这个 BERT 模型 → 得到每个 token 的 1024 维向量 → 按 `1_Pooling/config.json` 取 `[CLS]` 那个向量当整句表示 → 归一化 → **输出 1024 个数字**。

**余弦相似度和「归一化」的关系**：把两个向量想成从原点出发的两支箭头，**余弦相似度衡量的是夹角，不是长度**——夹角 0° → 相似度 1（最像），90° → 0，反向 → -1。用夹角而不是直线距离，是因为「句子长短」会影响向量长度，而**方向**才代表意思。

`modules.json` 里最后那一步 **`Normalize`（归一化）**就是把长度压成 1；归一化之后余弦相似度就退化成简单的点积，算得更快。

> ⚠️ **一个非常实用的坑**（来自模型自己的 README）：BGE 系列模型的相似度分布集中在 **`[0.6, 1]`** 区间，所以「相似度 0.5 就算相似」是**错的**——0.5 在 BGE 里已经算很不像了。而且**真正有用的是「相对排序」，不是绝对值**（谁排第一才是关键）。

### 6.6 为什么不能用 MySQL 存向量，非要用 Qdrant

理论上你当然可以把 1024 个数字拼成字符串塞进 MySQL 一列，然后查询时全表捞出来、在 Python 里一条条算余弦相似度。**但代价是：**

| 问题 | MySQL 的做法 | Qdrant 的做法 |
|---|---|---|
| 怎么比 | 全表扫描 + 逐行算 | **ANN（近似最近邻）索引**，直接跳到最可能的那一片 |
| 复杂度 | 数据量 N → 算 N 次（O(N)） | 近似 O(log N) 级别 |
| 100 万条时 | 每条算 1024 次乘法 → 卡死 | 毫秒级返回 |
| 向量类型 | 数据库根本不认「向量」（MySQL 8 没有原生向量类型/距离算子） | 原生支持余弦/点积/欧氏距离 |

Qdrant 的核心技术叫 **HNSW**（一张多层跳跃图）——不必深究，只需知道：**它用「近似」换来了巨大的速度**，牺牲一点点精度换几百倍加速。对「找相似句子」这个场景，近似完全够用。

**前端类比**：这就是「模糊搜索时用倒排索引 vs 每次遍历整个数组」。数据小的时候二者没差别，数据一大就是「能用」和「不能用」的差别。

Qdrant 里几个概念，对照 MySQL 记：

| Qdrant 概念 | 含义 | MySQL 里的对应物 |
|---|---|---|
| `collection`（集合） | 一组向量的容器 | **表（table）** |
| `VectorParams(size=..., distance=...)` | 声明向量维度 + 用什么距离算相似 | 列的类型定义 |
| `PointStruct` | 一条记录 = `id` + `vector` + `payload` | **一行（row）** |
| `payload` | 附带的任意 JSON（`{"city": "Berlin"}`），可以做过滤 | 其他普通列 |
| `Distance.COSINE` | 用余弦相似度 | 排序规则 |
| `query_points(..., limit=2)` | 「找最像的 2 条」 | `ORDER BY similarity DESC LIMIT 2` |

### 6.7 内存是最大的坑：5 个容器要约 7.25 GB

| 服务 | mem_limit | cpus | 出处 |
|---|---|---|---|
| mysql | 768m | 1 | `docker/docker-compose.yaml:19-20` |
| elasticsearch | 2g | 2 | `:34-35` |
| kibana | 2g | 1.5 | `:47-48` |
| qdrant | 512m | 1 | `:59-60` |
| embedding | 2g | 2 | `:74-75` |
| **合计** | **约 7.25 GB** | **7.5 核** | |

这些配额是**有意压低的**（都是很「抠」的值，明显照开发机算过），目的是防止某个服务失控吃满你整台电脑。**但总量摆在那里：光这 5 个容器就要预留约 7.25GB 内存。**加上浏览器、编辑器、宿主机上的 Python，**建议开发机至少 16GB 内存。**

内存不够时的典型症状，**按发生顺序**：

1. 某个容器起来又立刻退出 → `docker compose ps` 看到 `Exited`；
2. ES 起不来 / 报 OOM（它是内存大户：2g 限制 + 1g Java 堆）；
3. Docker Desktop 整体卡死或被杀。

**排查第一步永远是看日志**：`docker compose logs -f elasticsearch`。

**内存吃紧时的两招**：

1. **不调 SQL 时把 Kibana 停掉**（`docker compose stop kibana`）——它占 2g，但**代码完全不需要它**，立刻省 2GB。
2. 只启动当前需要的服务：`docker compose up -d mysql qdrant`。

---

## 7. 项目现状与待办：已实现 / 仅 demo / 空壳 TODO

这一节是全文最该记住的部分。**读代码最怕被「看起来实现了」骗了**，所以我把每个文件按四档分清楚（已实现 / 骨架空壳 / 仅 demo / 规划中）。

### 7.1 ✅ 第一档：已实现且真正可用

| 项 | 证据 | 说明 |
|---|---|---|
| **配置加载体系** | `app/conf/app_config.py:6-70`、`app/conf/meta_config.py:4-29`、`conf/app_config.yaml`、`conf/meta_config.yaml` | 9 个 dataclass 定义结构 + OmegaConf 校验并转对象。**真的能跑**，字段名写错会直接报错 |
| **日志体系** | `app/core/log.py:8-28` | loguru 双写（stdout + `logs/app.log`），轮转/保留/utf-8 都配好了 |
| **三个外部服务的连接管理** | `app/clients/mysql_client_manager.py:6-25`、`app/clients/qdrant_client_manager.py:7-24`、`app/clients/es_client_manager.py:6-20` | 连接池 + 全局单例都写好了。MySQL 还配了 `pool_size=10`、`pool_pre_ping=True`（`mysql_client_manager.py:18`） |
| **Docker 基础设施 + 样例数据** | `docker/docker-compose.yaml:1-80`、`docker/mysql/dw.sql`（318 行）、`docker/mysql/meta.sql`（48 行）、`docker/elasticsearch/Dockerfile:1-12` | 5 个服务编排完整（含内存/CPU 限制）；MySQL 初始化 SQL 会自动执行；ES 预装 IK 插件；embedding 模型也在仓库里 |
| **业务元数据** | `conf/meta_config.yaml:1-176` | 这份手写 yaml 是**实打实的业务资产**，不是占位符 |
| **ORM 模型** | `app/models/` 下 4 个实体类 | 与 `docker/mysql/meta.sql` 的 4 张表**逐字段一致**，质量最好的一层（**但没有任何代码 import 它们**） |
| **命令行入口骨架** | `app/scripts/build_meta_knowledge.py:14-36` | 参数解析、依赖注入、`asyncio.run` 都通——但它调用的 service 是空的，所以**跑完等于什么都没干** |

### 7.2 🟡 第二档：有骨架，但核心是空壳

| 项 | 证据 | 缺什么 |
|---|---|---|
| **`MetaKnowledgeService.build()`** | `app/services/meta_knowledge_service.py:10-40` | 配置读取部分（`:12-16`）已实现；2.1（`:22-27`）是 `pass`、2.3（`:31-32`）里那个 `pass` 是多余的死代码；2.2（`:29`）只有一行注释；3.1 的注释在 `:36`、3.2 的注释在 `:37`，两者共用 `:38` 的那个 `pass`。唯一真正执行的是 `:18` 的一行 `print` |
| **`MetaMySQLRepository`** | `app/repositories/mysql/meta/meta_mysql_repository.py:4-6` | 只有 `__init__` 存了 session，**一个方法都没有** |
| **三个空壳包** | `app/repositories/es/`、`app/repositories/qdrant/`、`app/repositories/mysql/dw/` | 每个目录里只有 **0 字节的 `__init__.py`**，没有任何代码。这是**为后续实现预留的骨架** |

### 7.3 🧪 第三档：能跑通，但只是 demo（别当业务逻辑读）

三个 client 文件末尾都挂着 `if __name__ == "__main__":` 的独立测试块，用 `python 文件路径` 直接跑就能自测。**读代码时不要把它们当业务逻辑**：

| 文件 | demo 内容 | 为什么说是 demo |
|---|---|---|
| `app/clients/mysql_client_manager.py:27-41` | 连 `dw` 库跑 `select * from fact_order limit 10`，打印前三行类型和值 | 硬编码 SQL，只为验证连接池能用 |
| `app/clients/qdrant_client_manager.py:27-68` | 建一个 `test_collection_async` 集合、塞 4 个 4 维向量（Berlin/London/Moscow/New York）、按向量查最近 2 条 | ① 集合名带 `test_` ② **向量维度用的是 4，不是配置里的 1024**（`:41`）③ 数据是城市名，和本项目业务无关。作者自己在 `:28-29` 注释里写明「正式建集合时应该用 `app_config.qdrant.embedding_size`」 |
| `app/clients/es_client_manager.py:22-51` | 建 `books` 索引、写入《Snow Crash》这本书、查出来打印 | 索引名是 `books`，而配置里写的是 `data_agent`（`conf/app_config.yaml:39`）；数据是英文书籍，和本项目无关 |

**另外还有两个「看起来像入口其实不是」的东西**：

- `main.py:1-5`：只有 3 句 loguru 演示，**不是入口**，也不被任何东西引用。
- `app/models/*.py`：4 个实体 + 1 个基类都写得很认真，但**当前没有任何代码 import 它们**，属于「写好了但没接线的类型定义」。

### 7.4 📋 第四档：规划中，代码一行都没有

- **整个在线问答链路（链路 B）**：无 HTTP 接口、无召回逻辑、无 LLM 调用、无 SQL 执行、无结果返回。
- **embedding 客户端**：`app/clients/` 下只有 mysql / qdrant / es **三个** manager，**没有** embedding client manager。
  ⚠️ 这点要特别强调：**仓库里关于 embedding 服务只有两处东西**——配置 `conf/app_config.yaml:31-34` 和配置类 `app/conf/app_config.py:39-43`（挂载在 `:63`），外加 `app/clients/qdrant_client_manager.py:29` 的一句注释。**没有任何调用代码，不要写成「已实现」。**
- **LLM 客户端**：`LLMConfig` 定义在 `app/conf/app_config.py:51-55` 并挂进了 `AppConfig`（`:65`），但全仓库搜索 `LLM` 只命中这两处定义，**没有任何 client / service 使用它**。
- **API 层**：`pyproject.toml` 装了 `fastapi`，但仓库里没有任何 FastAPI 应用代码。

`pyproject.toml` 里还装了四条「装了但没用上」的依赖——**它们其实就是作者对后续章节的路线图**：

| 依赖 | 状态 | 它对应的待办 |
|---|---|---|
| `fastapi`（HTTP 框架） | 零使用 | 「对外提供问答接口」还没开始写 |
| `langchain` / `langgraph`（Agent 编排） | 零引用 | 多步骤 Agent 流程还在规划 |
| `jieba`（中文分词） | 零引用 | 对应「2.3 维度取值建全文索引」（中文分词后才能灌 ES） |
| `langchain-huggingface` | 零引用 | 对应「2.2 字段建向量索引」 |

### 7.5 核心的那个 `build()`：5 个 TODO 分别要做什么

这是全项目的「施工图」。`MetaKnowledgeService.build()` 的骨架里，5 个 TODO 编号就是接下来要实现的任务清单：

| 编号 | 位置 | 要做什么 | 具体怎么做（按现有配置推断） | 状态 |
|---|---|---|---|---|
| **2.1** | `:22-27` | **把表信息和字段信息写进 meta 库** | 遍历 `meta_config.tables`，每张表 → `table_info` 一行；每张表的每个字段 → `column_info` 一行。需要一个「入库」方法，而那正是 `MetaMySQLRepository` 现在没有的东西 | ❌ 未实现 |
| **2.2** | `:29` | **对字段信息建向量索引（写 Qdrant）** | 把每个字段的「描述 + 别名」拼成一段文本，调 embedding 服务（`conf/app_config.yaml:31-34`，1024 维）拿到向量，存进 Qdrant 的一个 collection（维度必须用 `embedding_size: 1024`）。**这也是唯一需要 embedding 客户端的地方** | ❌ 未实现 |
| **2.3** | `:31-32` | **对指定的维度字段取值建全文索引（写 ES）** | 从 `dw` 库里把 `sync: true` 的 10 个维度字段的全部取值抽出来（华东、华南、黄金、苹果……），灌进 ES 的 `data_agent` 索引（`conf/app_config.yaml:39`）。中文分词靠 IK 插件 | ❌ 未实现 |
| **3.1** | `:36` | **把指标信息写进 meta 库** | `meta_config.metrics` 里的 GMV / AOV → `metric_info`；指标与字段的关联 → `column_metric`（多对多中间表） | ❌ 未实现 |
| **3.2** | `:37` | **对指标信息建向量索引** | 和 2.2 同理，只是文本换成指标的「名称 + 描述 + 别名」（如 GMV：成交总额、订单总额） | ❌ 未实现 |

**一句话总结现状**：

> **5 个 Docker 服务、5 张业务表、115 行样例数据、176 行业务元数据、4 个 ORM 模型、3 个连接管理器都就绪；**
> **`build()` 里 5 个 TODO 全是 `pass`，在线问答链路一行代码都没有。**
> 这是典型的**「骨架搭好、等你填肉」**阶段。

### 7.6 建议的上手顺序（如果你要接着写代码）

1. **先补 `MetaMySQLRepository` 的方法**（比如 `save_tables()` / `save_columns()`），把 2.1 和 3.1 打通——这两步不需要任何新依赖，只需读写 MySQL。
2. **再写 embedding 客户端**（照 `app/clients/es_client_manager.py` 的套路写一个 `embedding_client_manager.py`），然后做 2.2 / 3.2。
3. **最后做 2.3**：需要在 `app/repositories/mysql/dw/` 下写「从数仓抽维度取值」的查询，再写 `app/repositories/es/` 的写入逻辑。
4. 等链路 A 通了，再考虑链路 B（FastAPI + LLM + 执行 SQL）。

---

## 8. 已知问题与提醒

下面每一条都是**实际核对过文件/命令输出**的，不是猜测。做演示项目关系不大，但如果要上线，前 4 条必须先修。

### 8.1 🔴 明文密码 + 占位符密钥 + 第三方代理地址

```yaml
# conf/app_config.yaml:16
  password: Atguigu.123      # ⚠️ 明文密码，meta(:16) 和 dw(:23) 两处都是它
# conf/app_config.yaml:43
  api_key: <api_key>         # ⚠️ 占位符，根本跑不通
# conf/app_config.yaml:44
  base_url: https://api.openai-proxy.org/v1   # ⚠️ 第三方代理，不是官方域名
```

三个问题：

1. **数据库密码明文入库**。`Atguigu.123` 直接写在版本库里的 yaml 中，任何人拿到仓库就拿到了密码。（`docker/docker-compose.yaml:8-10` 里还有一份同样的明文。）
2. **`api_key: <api_key>` 是未填的占位符**——也就是说**这个项目当前绝对跑不通真实的 LLM 调用**，作者自己也没填。
3. **`base_url` 指向 `api.openai-proxy.org`** 这样一个第三方代理。这意味着你的 API Key 和**全部对话内容都会经过一个不受你控制的中间人**。

**正确做法**：密码和 Key 放进环境变量或 `.env`（`.env` 加进 `.gitignore`），yaml 里只写 `${oc.env:DB_PASSWORD}` 这类引用。**前端类比**：这和你绝不会把 `JWT_SECRET` 提交到 Git 里是同一个道理。

### 8.2 🟠 `__pycache__/*.pyc` 被误提交进版本库

`git ls-files` 实际输出里，**有 8 个 `.pyc` 编译缓存被 Git 跟踪**：

```
app/clients/__pycache__/__init__.cpython-312.pyc
app/clients/__pycache__/qdrant_client_manager.cpython-312.pyc
app/core/__pycache__/__init__.cpython-312.pyc
app/core/__pycache__/log.cpython-312.pyc
app/scripts/__pycache__/__init__.cpython-312.pyc
app/scripts/__pycache__/build_meta_knowledge.cpython-312.pyc
app/services/__pycache__/__init__.cpython-312.pyc
app/services/__pycache__/meta_knowledge_service.cpython-312.pyc
```

而 `.gitignore` 的全部内容只有 4 行：

```
/.venv
/logs
/.idea
/docker/embedding/bge-large-zh-v1.5/
```

**没有忽略 `__pycache__`。**

- **`.pyc` 是什么**：Python 把源码编译成字节码后的缓存文件，运行时自动生成。**它不该进版本库**——二进制、平台相关、每次运行都可能变，会污染 diff、制造无意义的冲突。
- **前端类比**：等同于把 `node_modules/` 或 `.next/` 的构建产物提交进了 Git。
- **修法**：在 `.gitignore` 加 `__pycache__/` 和 `*.pyc`，然后 `git rm -r --cached` 掉已跟踪的那些。

### 8.3 🟠 单例「能在 import 时构造，却不能保证被初始化」

三个 manager 都是这个模式（`mysql_client_manager.py:24-25`、`es_client_manager.py:20`、`qdrant_client_manager.py:24`）：

```python
qdrant_client_manager = QdrantClientManager(app_config.qdrant)   # import 时就构造了
```

但 `init()` 只在各自的 `__main__` 测试块里、以及 `build_meta_knowledge.py:15` 里被显式调用。**没有任何机制保证「用之前一定 init 过」。**

后果：谁写了 `from app.clients.es_client_manager import es_client_manager` 然后直接用 `es_client_manager.client`，拿到的是 `None`，会得到 `AttributeError: 'NoneType' object has no attribute ...`——而且**报错位置离真正的原因很远，很难查**。

**更稳的写法**：懒加载（首次访问时才创建）、或在 `__init__` 里直接建好、或提供 `@property` 在未初始化时抛出明确错误。

### 8.4 🟡 `logs/app.log` 里的历史日志与当前代码对不上

`logs/app.log` 里实际只有两行（**文件本身是合法 UTF-8，145 字节，无 BOM，正文是 `Building……`，没有任何损坏**）：

```
2026-09-20 14:43:34.350 | INFO     | __main__:build:15 - Building……
2026-09-20 18:24:43.657 | INFO     | __main__:build:9 - Building……
```

日志格式里的 `build:15` / `build:9` 表示「函数 `build` 的第 15 行 / 第 9 行」。

**但当前 `build_meta_knowledge.py` 的第 9 行是 `from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository`，第 15 行是 `meta_mysql_client_manager.init()`——两行都不是日志语句，而且整个文件根本没有任何 `logger.xxx()` 调用。**

**结论**：这两条日志是**旧版本代码**跑出来的残留。它反过来证明了一件好事：**这个脚本以前是打过日志的**（`logger.info("Building……")` 之类），后来被删掉了，但日志文件没清、`logger` 的 import 也忘了一起删。

**顺带一提**：这两条日志的 `__main__` 前缀还说明，当时是用 `python app/scripts/build_meta_knowledge.py` 这种「直接跑文件」的方式启动的；而现在正确方式应该是从项目根目录 `python -m app.scripts.build_meta_knowledge`。

### 8.5 🟡 Qdrant 的 demo 用 `size=4`，而配置是 1024

`app/clients/qdrant_client_manager.py:41` 的 `VectorParams(size=4, ...)` 是 demo 值（因为它的测试数据只有 4 个数），而真实配置 `conf/app_config.yaml:29` 是 `embedding_size: 1024`。

**后果**：如果照 demo 建了集合，以后往这个集合里写 1024 维的真实 embedding 会**直接报维度不匹配**。真实流程必须用 1024。作者自己在 `:28-29` 注释里也提醒了。

### 8.6 🟡 其他小问题汇总

| 位置 | 问题 | 影响 |
|---|---|---|
| `app/scripts/build_meta_knowledge.py:31` | `add_argument('-c','--conf')` **没写 `required=True`**，不传参数时 argparse 不报错、`args.conf` 为 `None`，错误被推迟到 `Path(None)` 才以 `TypeError` 炸出来 | 报错位置离原因很远，难排查。修法：加 `required=True` |
| `app/scripts/build_meta_knowledge.py:8` | `from app.repositories.mysql.meta import meta_mysql_repository` 从未使用 | 无功能影响，误导读者 |
| 同上 `:10` | `from app.services import meta_knowledge_service` 从未使用 | 同上 |
| 同上 `:7` | import 了 `logger` 但从不调用 | 仅为副作用 import，且等于没有日志 |
| 同上 `:17-18` | 变量名遮蔽了导入的模块名 | 潜在 bug 隐患 |
| 同上 `:14` | `build()` 无 `return`，丢弃了 service 的返回值 | 逻辑上「丢结果」 |
| `app/services/meta_knowledge_service.py:18` | 用 `print` 而非 `logger` 输出调试 | 不走日志系统，且是残留代码 |
| `app/services/meta_knowledge_service.py:32` | 12 空格缩进的那个 `pass` 是多余的死代码 | 无功能影响，但读代码容易看错 |
| `app/repositories/mysql/meta/meta_mysql_repository.py:5` | 参数名 `Session` 用了大写 | 命名误导（大写通常留给类名） |
| `app/conf/app_config.py:72` | 被注释掉的 `# print(...)` | 调试残留 |
| `conf/__init__.py` | `conf/` 里放的是 yaml，却有 Python 包的标记 | 多余 |
| `app/models/*.py` | 未声明外键约束 | 与 SQL 一致，但关系只靠约定（逻辑外键） |
| `conf/meta_config.yaml:173` vs `:175` | **`AOV` 指标定义内部不自洽**：描述写的是「所有订单的**成交金额**平均值」，但 `relevant_columns` 指向的是 `fact_order.order_quantity`（**数量**字段） | 按描述它应该指向 `fact_order.order_amount`。可能是笔误，也可能是刻意口径（「平均每单件数」），**当前没有代码能验证**，留给后续确认 |
| `conf/meta_config.yaml:100` / `:112` / `:118` | `dim_date` 的 `year` / `month` / `day` 被标成 `sync: false`，只有 `quarter` 是 `true` | 也就是说将来 ES 里不会有「2025」「3」这些时间取值——但用户问「去年」时**恰恰需要按年过滤**。这可能是设计选择（时间条件由 LLM 直接推），也可能是**待修正的标记**；当前没有代码能验证，只做提示 |
| `docker/mysql/meta.sql:19-29` vs `conf/meta_config.yaml` | `column_info` 有 `type` / `examples` 两列，但配置里不提供这两项数据 | **填充来源尚未实现**（见 6.4 节的「规格缺口」） |

---

## 附录 A：术语表

按「中文名 / 英文名 / 一句话解释 / 前端类比」组织。**第一次读不懂时回来查这张表就够了。**

### A.1 数据库相关

| 中文名 | 英文名 | 一句话解释 | 前端类比 |
|---|---|---|---|
| 数据库 | database | 一个命名空间，里面装很多张表 | 一个大模块 / 命名空间 |
| 表 | table | 一类数据的集合，列结构固定 | 一个数组 `[{}, {}, ...]`，每条对象字段固定 |
| 行 / 记录 | row / record | 一条具体数据 | 数组里的一个对象 |
| 列 / 字段 | column / field | 一个属性，有固定类型 | 对象的 key，但有类型约束 |
| 主键 | primary key | 能**唯一标识**一行的字段，不重复、不能为空 | 列表渲染的 `key`，但更强 |
| 外键 | foreign key | 指向另一张表主键的字段，用来表达两张表的关系 | 一个「引用/指针」，像 `order.customerId → customer.id` |
| **逻辑外键** | logical foreign key | **只是业务约定**，不是数据库强约束——**本项目的 4 个外键字段就是这种**（SQL 里没有 `FOREIGN KEY`） | 像 TS 里你写了 `customerId: string` 但**运行时没人校验**它真的存在 |
| 索引 | index | 为了「查得快」额外维护的排好序的目录 | 给数组建一个 `Map`，从「遍历找」变成「直接查」 |
| SQL | Structured Query Language | 用来操作数据库的声明式语言 | 一种「查询 DSL」（像你在 GraphQL 里描述你要什么） |
| 数仓 / 数据仓库 | data warehouse（dw） | **专门给分析用的数据库**。业务库按订单一条条存（方便写），数仓按「事实+维度」组织（方便多维聚合查） | 业务库像「操作日志」，数仓像「给 BI 用的预聚合数据集市」 |
| 维度表 | dimension table（`dim_`） | 存**描述性属性**（地区名、客户名、品类），用来筛选/分组/打标签。通常很小、很少变 | 一份「枚举/字典表」，用来给数据打标签 |
| 事实表 | fact table（`fact_`） | 存**发生了什么**：外键（指向各维度）+ 度量（可累加的数字） | 一张「事件流水表」，每条记录带几个外键指针 |
| 星型模型 | star schema | 中间一张事实表、四周发散若干维度表，形状像星星 | 「一个主数组 + 几张字典表按 id 关联」的经典数据建模 |
| 度量 | measure | 能求和、求平均的**数字**（数量、金额） | 可以放进 `reduce()` 求和的字段 |
| 联合主键 | composite primary key | 两个字段**一起**当主键，保证「这一对组合」不重复 | 多对多映射表 `{aId, bId}` 里 `(aId, bId)` 唯一 |
| 外键约束 | FOREIGN KEY constraint | 数据库层面强制检查「引用的那条真的存在」——**本项目没用**（为了导入性能） | 像开了运行时校验 vs 只靠 TS 类型 |

### A.2 Python / 后端工程相关

| 中文名 | 英文名 | 一句话解释 | 前端类比 |
|---|---|---|---|
| 对象关系映射 | ORM（Object-Relational Mapping） | 让你用「操作对象」的方式操作数据库表，不用手写 SQL | Prisma / Drizzle / TypeORM 的 schema 定义 |
| 连接池 | connection pool | 提前开好一批数据库长连接放池里复用（建连接很贵） | 配置好并复用的 axios 实例 |
| 会话 | session | 一次业务操作的工作上下文，真正执行 SQL 的载体，用完归还连接 | 一次请求上下文（`ctx`，用完释放） |
| 异步 / 等待 | async / await | `async def` 调用时返回「协程」（像 Promise），必须 `await` 才真正执行 | `async`/`await` + Promise，几乎一样 |
| 事件循环点火 | asyncio.run() | 创建事件循环、把协程跑起来。**Python 必须有这一步**，否则协程根本不执行 | Node 里进程启动时自动有的事件循环（Python 要显式点） |
| 仓储层 | repository | 把「怎么读写数据库」从业务逻辑里隔出来的一层 | 把 `fetch('/api/x')` 都收进 `api/user.ts` |
| 依赖注入 | dependency injection | 依赖从外部传进来，而不是内部写死 new 一个 | `function Service(apiClient) {}`，把 client 当参数传 |
| 单例 | singleton | 全程序只有一个实例 | `export const xxx = {...}` 模块级常量 |
| 装饰器 | decorator | 给函数/类套一层外挂改它的行为 | 高阶函数 / `@decorator` / HOC |
| 空占位语句 | `pass` | Python 里表示「这里什么都不做」（因为语法要求块不能为空） | 空的 `{}` |

### A.3 搜索 / 向量相关

| 中文名 | 英文名 | 一句话解释 | 前端类比 |
|---|---|---|---|
| 倒排索引 | inverted index | 「词 → 文档列表」的映射（普通索引是「文档 → 词」），查询时直接求交集，不用扫全表 | 提前建好 `Map<string, Set<id>>`，而不是每次 `filter(includes)` |
| 分词 | tokenization | 把一句话切成一个个「词」，这样才能按词匹配 | `str.split(' ')` 的中文专业版（中文没有空格，所以要词典） |
| 向量 | vector | 一串固定长度的数字（本项目是 **1024 个**） | 一个定长 `number[]` |
| 文本嵌入 | embedding | 把一段文本变成一串数字，**意思相近 → 数字也相近** | 给字符串做「语义编码」，但要求语义相近的编码也相近 |
| 余弦相似度 | cosine similarity | 衡量两个向量的**夹角**（不是长度）：1 = 最像，0 = 无关，-1 = 相反 | 两个归一化向量点积；用角度而非距离，避免被长度干扰 |
| 向量数据库 | vector database（Qdrant） | 专门存向量、专门回答「哪 N 个最像」的数据库，用 ANN 索引换速度 | 「相似度搜索」的专用索引服务 |
| 近似最近邻 | ANN（Approximate Nearest Neighbor） | 不保证找到绝对最近的，但**快几百倍**——牺牲一点精度换可用性 | 模糊搜索用倒排索引，而不是全量遍历 |
| 推理服务 | TEI（Text Embeddings Inference） | 把「文本→向量」模型包装成一个常驻 HTTP 服务，避免每次启动都加载模型 | 把重计算放进 Web Worker / 独立微服务 |
| 近似关键词排序 | relevance score | ES 不只是「命中/不命中」，还会给结果**打分排序** | 搜索结果的 `score` 字段，按相关度排序 |

### A.4 Docker / 运维相关

| 中文名 | 英文名 | 一句话解释 | 前端类比 |
|---|---|---|---|
| 镜像 | image | 「安装包」：程序 + 全部依赖打包好，只读、不变 | 一个装好一切的环境快照 |
| 容器 | container | 镜像**跑起来的实例**，可随时删。**不是虚拟机**，共享宿主内核 | `new Image()` 出来的对象实例；或浏览器无痕窗口 |
| 数据卷 | volume | 数据存在**容器外面**，容器删了数据还在 | 同步到硬盘的用户目录（vs 无痕窗口里的临时数据） |
| 绑定挂载 | bind mount | 把宿主机上某个**具体目录**挂进容器 | 软链接一个本地文件夹进去 |
| 端口映射 | port mapping | `"3308:3306"` = 宿主机 3308 → 容器内 3306 | 反向代理的端口转发规则 |
| 编排 | docker compose | 用一个 YAML 把多个服务一次配好，一条命令同时起 | `concurrently` / `npm-run-all` 同时跑多个服务，但更彻底 |
| 容器编排文件 | docker-compose.yaml | 声明 5 个服务用什么镜像、开什么端口、挂什么卷、给多少内存 | `package.json` 的 `scripts` + 一份环境清单 |
| 构建 | build | 基于别人的镜像再改一层（例如装个插件） | 基于基础镜像再 `npm i` 一层 |

### A.5 本项目专属名词

| 名词 | 是什么 |
|---|---|
| **掌柜问数** | 本项目的名字。目标：让不会写 SQL 的人用中文提问就能查数据 |
| **ChatBI** | 对话式商业智能。就是「用聊天的方式问数据」这整类产品 |
| **NL2SQL** | Natural Language to SQL，把自然语言翻译成 SQL 的技术方向 |
| **元数据知识库**（meta knowledge） | 把「业务黑话 ↔ 数据库字段」整理成 AI 能检索的资料。**本项目当前的全部工作就是建它** |
| **`meta` 库** | 存「关于数据的说明书」的库（4 张表：`table_info` / `column_info` / `metric_info` / `column_metric`） |
| **`dw` 库** | 存真实业务数据的数仓（5 张表 + 115 行样例数据） |
| **`sync: true/false`** | `conf/meta_config.yaml` 里每个字段的开关。`true` 的 10 个字段是「要被抽取取值灌进 ES」的维度字段 |
| **`role`** | 每个字段的角色：`primary_key` / `foreign_key` / `measure` / `dimension`。让机器知道「这个字段能不能 SUM、能不能 GROUP BY」 |
| **链路 A** | 离线建库链路：`meta_config.yaml` → 写 meta 库 / Qdrant / ES。**骨架已搭好，5 步全是空** |
| **链路 B** | 在线问答链路：提问 → 召回 → 生成 SQL → 查 dw → 返回。**一行代码都没有** |
| **IK 分词器** | 给 ES 装的中文分词插件。官方镜像没带，所以要自建 ES 镜像 |
| **BGE** | BAAI General Embedding，智源研究院的向量模型系列。本项目用 `bge-large-zh-v1.5`，输出 1024 维 |

---

## 附录 B：怎么把这个项目跑起来

⚠️ **先说结论**：这个项目**跑起来只能验证「基础设施都活着 + 代码能连上」**。因为核心业务逻辑（`build()` 里的 5 个 TODO）还没写，**跑完不会有任何数据进 meta 库 / Qdrant / ES**。想验证功能，现在没有功能可验证。

### B.1 前置条件

| 需要什么 | 说明 |
|---|---|
| **Docker Desktop** | 5 个服务都靠它跑 |
| **至少 16GB 内存** | 5 个容器要约 7.25GB（见 6.7 节），加上浏览器/编辑器/Python |
| **Python ≥ 3.12** | `pyproject.toml:4` 要求 `requires-python = ">=3.12"` |
| **约 1.3GB 的 embedding 模型文件** | 放在 `docker/embedding/bge-large-zh-v1.5/`。**这个目录被 `.gitignore:4` 忽略，克隆仓库后不会存在，必须自己准备**（至少不能缺 `pytorch_model.bin`，约 1242MB） |
| 网络 | 首次启动要拉 MySQL / Kibana / Qdrant / TEI 镜像，并**本地构建** ES 镜像 |

### B.2 第一步：启动 Docker 服务

仓库里没有现成的 `docker compose up` 说明文档，下面是 Docker 的标准用法：

```bash
cd docker
docker compose up -d      # 后台启动全部 5 个服务（第一次会自动拉镜像 / 构建 ES 镜像）
docker compose ps         # 看各服务状态
```

**第一次启动的预期**：

- `elasticsearch` 会**明显更慢**（要从 `docker/elasticsearch/Dockerfile` 现场构建 + 装 IK 插件）。不是卡死。
- `kibana` 可能报几次连不上 ES（`depends_on` 只保证启动顺序，不保证 ES 就绪），等几十秒刷新即可。`docker/docker-compose.yaml:45-46` 有说明。

### B.3 第二步：验证 5 个服务都起来了

```bash
docker compose ps          # 5 个都应该是 Up（不是 Exited）
```

| 服务 | 怎么验证 | 期望结果 |
|---|---|---|
| **mysql** | `docker compose exec mysql mysql -uatguigu -pAtguigu.123 -e "show databases;"` | 能看到 `dw` 和 `meta` 两个库 |
| | `docker compose exec mysql mysql -uatguigu -pAtguigu.123 dw -e "select count(*) from fact_order;"` | **115** |
| | `docker compose exec mysql mysql -uatguigu -pAtguigu.123 meta -e "show tables;"` | 4 张表：`table_info`、`column_info`、`metric_info`、`column_metric`（**都是空的**） |
| **elasticsearch** | 浏览器 / curl `http://localhost:9200` | 返回一段 JSON，含版本号 `8.19.10` |
| **kibana** | 浏览器打开 **`http://localhost:15601`** | Kibana 首页。左侧菜单 → **Dev Tools**，可以手敲 ES 查询 |
| **qdrant** | `http://localhost:6333/dashboard`，或 `http://localhost:6333/collections` | 返回 `{"result":{"collections":[]}}`（**空列表，因为还没建任何集合**） |
| **embedding（TEI）** | `http://localhost:8081/health` | 返回 `ok` 之类的健康响应 |

⚠️ **端口一定要用对**：

| 服务 | 宿主机端口 | 别搞错 |
|---|---|---|
| MySQL | **3308** | 不是默认的 3306 |
| Elasticsearch | **9200** | ✅ |
| Kibana | **15601** | ⚠️ **不是默认的 5601**！`docker/docker-compose.yaml:44` 是 `"15601:5601"`，宿主机上的 5601 **访问不到** |
| Qdrant | **6333**（HTTP）/ **6334**（gRPC） | ✅ |
| embedding | **8081** | 容器内是 80 |

### B.4 第三步：跑 Python 侧（安装依赖 + 执行入口）

```bash
# 回到项目根目录（不是 docker/）
cd ..

# 安装依赖（本项目用 uv 管理；用 pip 也行）
uv sync
# 或者：pip install -e .

# 运行真正的入口（必须从项目根目录跑，否则 import app.xxx 会失败）
python -m app.scripts.build_meta_knowledge -c conf/meta_config.yaml
```

**预期输出**：屏幕上会打印出 2 个指标对象（Python 的 `repr` 格式，来自 `app/services/meta_knowledge_service.py:18` 那行调试 `print`），**然后就没有然后了**。

**预期的数据库变化**：**没有变化。** `meta` 库的 4 张表仍然是空的，Qdrant 里没有 collection，ES 里没有 `data_agent` 索引。

> 这不是你操作错了——这是**当前代码的真实状态**：`build()` 里的 5 个 TODO（2.1 / 2.2 / 2.3 / 3.1 / 3.2）全是空壳。

**常见的两类报错**：

| 现象 | 原因 | 怎么办 |
|---|---|---|
| 不传 `-c` 报 `TypeError` | `app/scripts/build_meta_knowledge.py:31` 没写 `required=True`，参数才变成 `None` 传给 `Path()` | 加上 `-c conf/meta_config.yaml` 即可（见 8.6 节） |
| `ModuleNotFoundError: No module named 'app'` | 没在项目根目录执行 | `cd` 到项目根目录，用 `python -m app.scripts.build_meta_knowledge` |

### B.5 排查清单：起不来时按顺序看

1. **先看日志**：`docker compose logs -f <服务名>`（比如 `elasticsearch`）。这是排查第一步，没有例外。
2. **内存不够**（最高频）：症状是某容器 `Exited`、或 ES 报 OOM、或 Docker Desktop 整体卡死。
   → 不调 SQL 时先 `docker compose stop kibana`（**立刻省 2GB**，代码完全不需要它）。
3. **改了 `dw.sql` 想让它生效**：不可能，除非删卷。`/docker-entrypoint-initdb.d` **只在第一次启动（卷为空时）执行**（`docker/docker-compose.yaml:15`）。
   → `docker compose down -v` 然后重新 `up`。⚠️ **`-v` 会永久删掉库里的数据。**
4. **Kibana 连不上 ES**：`depends_on` 只保证启动顺序。等几十秒刷新。
5. **embedding 起不来**：检查 `docker/embedding/bge-large-zh-v1.5/` 是否存在且完整（**克隆仓库后它不存在**，必须自己准备约 1.3GB 模型文件）。
6. **在容器里写 `localhost` 去连别的容器**：容器内的 `localhost` 是**它自己**。
   → 容器之间用**服务名**（如 Kibana 用 `http://elasticsearch:9200`，`docker-compose.yaml:42`）；**宿主机上的代码用 `localhost`**（`conf/app_config.yaml:13`）。本项目业务代码在宿主机跑，所以配置里全写 `localhost`——**这是对的，别改**。
7. **向量维度不匹配**：TEI 输出 1024 维（`config.json:13`），Qdrant 建集合必须也用 1024（`conf/app_config.yaml:29`）。代码里那个 `size=4` 是 demo（`app/clients/qdrant_client_manager.py:41`），**不要照抄**。
8. **想看数据到底进没进 ES**：用 Kibana 的 Dev Tools，不用写代码。

### B.6 想单独验证某个 client 能连上

三个 client 文件末尾都有自测块，可以直接跑（**注意这是 demo，不改任何业务数据**）：

```bash
python -m app.clients.mysql_client_manager    # 连 dw 库，查 fact_order 前 10 行并打印类型
python -m app.clients.es_client_manager       # 在 ES 建 books 索引、写一本书、查出来
python -m app.clients.qdrant_client_manager   # 建 test_collection_async、写 4 个 4 维向量、查最近 2 条
```

分别对应 `app/clients/mysql_client_manager.py:27-41`、`app/clients/es_client_manager.py:22-51`、`app/clients/qdrant_client_manager.py:27-68`。

⚠️ 跑 qdrant 那个 demo 会在你的 Qdrant 里建一个叫 `test_collection_async` 的**4 维**集合。它和真实业务无关，看完可以手动删掉（或 `delete_collection`）。

---

## 结语：三句话带走

1. **它在干什么**：做一个中文自然语言查数仓的 AI 助手。用户问「华东地区去年销售额多少」，系统自己搞清楚要查 `fact_order.order_amount` + `dim_region.region_name` + `dim_date.year`，生成 SQL 去查 `dw` 库。
2. **它的核心设计**：不能把数据库结构直接丢给大模型（模型不懂业务黑话），所以要先建一个**元数据知识库**——用 **MySQL `meta` 库**存结构化定义、用 **Qdrant + embedding** 做语义召回、用 **Elasticsearch + IK 分词**做取值关键词召回。
3. **它现在的进度**：**基础设施和配置齐了，核心逻辑一点没写。** 5 个 Docker 服务、5 张业务表、115 行样例数据、176 行业务元数据、4 个 ORM 模型、3 个连接管理器都就绪；`MetaKnowledgeService.build()` 里 5 个 TODO（2.1 / 2.2 / 2.3 / 3.1 / 3.2）全部是空实现（要么是 `pass`，要么只是一行注释），在线问答链路一行代码都没有。当前处于典型的**「骨架搭好、等你填肉」**阶段。

---

## 修订记录

本文定稿前经过一轮逐条事实核对（核对报告见 `docs/project-explained/04-review-notes.md`，共 6 条低严重度问题）。**下面是这 6 条问题的处理情况，一条不落地列出来，方便你看到哪些地方被纠正过。**

> 核对报告的总体结论是：132 处 `文件:行号` 引用全部有效、代码片段与源码逐字一致、无臆造标识符、无「把 TODO 说成已完成」，**没有发现任何会误导读者的事实错误**。所以下面这 6 条都是「把话说得更准」级别的修正。

| 编号 | 核对报告指出的问题 | 本文如何处理 |
|---|---|---|
| **F1** | §4.1 把 `sync: false` 的 14 个字段概括成「全是主键、外键、度量值」，但实际只有 11 个是，另外 3 个是 `dim_date` 的 `year`/`month`/`day`（`role: dimension`）；而 §8.6 又正确写了这 3 个是待确认项，两处自相矛盾 | ✅ **已修正**。§4.1 改为「14 个里 **11 个**是主键/外键/度量值（并逐个列出 `:10/:38/:66/:94/:128/:134/:140/:146/:152/:158/:164`），**另有 3 个**是 `dim_date` 的 `year`(`:100`)/`month`(`:112`)/`day`(`:118`)——它们本来就是维度却被标成 `sync: false`，**疑似标记问题**」，并显式写明与 8.6 节同一件事、两处口径一致。列出的 11+3 个行号已按 `conf/meta_config.yaml` 逐个复测（`primary_key=5` / `foreign_key=4` / `measure=2` / `dimension=3`） |
| **F2** | 对 `meta_knowledge_service.py` 的 3.1 / 3.2 行号描述**三处互相矛盾**（按核对报告，修订前分别位于 §4.1 `:440`、§5.6 `:1024`、§7.2 `:1602`——这三处写的是「`:36-38` 内部是 pass」/「只有一行注释（`:36`）」/「`:36-38` 全是 pass」） | ✅ **已按事实统一**。事实是 `:36` 是 3.1 的注释、`:37` 是 3.2 的注释、`:38` 是两者**共用**的一个 `pass`。三处统一成这一种表述：§4.1 的流程块改为「3.1 `:36` 只有一行注释 / 3.2 `:37` 只有一行注释 /（3.1 与 3.2 共用 `:38` 的一个 pass）」；§5.6 的 TODO 表格和 §7.2 的现状表格同步改成同一口径 |
| **F3** | §7 开头写「我把每个文件按**三档**分清楚」，但正文是 7.1–7.4 **四档** | ✅ **已修正**。「三档」改为「**四档**（已实现 / 骨架空壳 / 仅 demo / 规划中）」，与正文的 7.1–7.4 对齐 |
| **F4** | §7.4 写「`pyproject.toml` 里还装了**三条**『装了但没用上』的依赖」，紧随其后的表格实际是 **4 行** | ✅ **已修正**。「三条」改为「**四条**」（`fastapi` / `langchain`+`langgraph` / `jieba` / `langchain-huggingface`），与表格行数对齐；`langchain` 与 `langgraph` 仍合并为一行展示，因为二者同属 Agent 编排 |
| **F5** | §6.5 的「embedding 模型目录里都是什么」表格只列了 10 个条目，但目录里实际还存在 `.gitattributes`、`config_sentence_transformers.json` 和 `.cache/`（HuggingFace 下载缓存） | ✅ **已补全**。主表格后新增一张小表，补上 `.gitattributes`（约 1.5 KB）、`config_sentence_transformers.json`（约 124 B）和 `.cache/huggingface/download/*.metadata`，并注明这三样「**与向量计算无关**，但既然标题是『目录里都是什么』就一并说明」。三个条目的存在与大小均已实测 |
| **F6** | 仓库有 3 个 `.py` 处于「已 `git add` 未提交」状态，其中 `meta_knowledge_service.py` 相对 `HEAD` 多 1 行，用 `git show HEAD:` 对照的读者会发现行号整体偏移 1（**提问者注明这不是文档的错误**） | ✅ **已在文首补充说明，未改动任何行号**。开头「全文只讲仓库里真实存在的东西」那段后新增一段：所有 `文件:行号` **以当前工作树为准**，其中 `app/services/meta_knowledge_service.py` 相对最后一次提交有 **1 行偏移**（工作树 40 行 / HEAD 39 行），其余文件行数与提交版本一致。**按核对员与队长的要求，只加说明、绝不重编号** |

### 附带修正（自查发现，与 F2 同类）

在统一 F2 的过程中，我发现全文还有**一处同类的不精确概括**（核对报告未列出）：**结语**第 3 句原本写「5 个 TODO（2.1 / 2.2 / 2.3 / 3.1 / 3.2）**全是 `pass`**」，但按源码 `:29` 与 `:37` 其实**只有注释、连 `pass` 都没有**（真正存在的 `pass` 在 `:27`、`:32`、`:38`）。

→ ✅ **已改为**「全部是空实现（要么是 `pass`，要么只是一行注释）」。这样既不夸大，也与 §5.6、§7.2、§7.5 的描述完全一致。

### 本次修订没有做的事

为遵守「不允许为了好看而新增未经核实的内容」，以下两点**明确不做**：

1. **没有重编号任何 `文件:行号` 引用**（F6 只加说明）。所有引用仍指向仓库当前工作树，修改后已重新确认未被波及。
2. **没有改动任何结论性判断**。四档分期、5 个 TODO 全未实现、在线链路一行代码都没有、逻辑外键、Kibana 15601、9 个 dataclass、8 个 `.pyc`、embedding 无客户端代码等，全部保持原样——它们已在核对报告中逐条实测通过。

