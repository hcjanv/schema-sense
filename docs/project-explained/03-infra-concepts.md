# 03 · 基础设施与概念扫盲：docker/ 目录 + MySQL / Elasticsearch / Kibana / Qdrant / embedding / Docker

> 本文写给**完全不懂后端、不懂运维的前端开发者**。
> 目标：读完这一篇，你能看懂 `docker/` 目录里每个文件在干什么，能分清 MySQL / Elasticsearch / Kibana / Qdrant / embedding / Docker 这 6 个词各自是什么、为什么这个项目同时需要它们，并且知道启动它们时最容易踩的坑在哪里。
>
> 全文只讲**这个仓库里真实存在的东西**。仓库里还没写的部分，会在最后一章明确标出来（"还没实现"），不会替它编故事。

---

## 0. 一分钟建立大图景

这个项目（掌柜问数 data-agent）要做的事，用前端语言说就是：

**用户用中文问一句"华南地区去年销量最高的商品是什么"，系统要自己搞明白这句话该查哪张表、怎么写成 SQL，然后把结果给出来。**

为了做到这一点，后端不能只有"一个数据库"。它需要 5 个各司其职的"服务"，而 `docker/docker-compose.yaml` 就是把这 5 个服务一次性启动起来的**配置清单**：

| # | 服务名 | 它是什么 | 一句话职责 | 类比（前端视角） |
|---|---|---|---|---|
| 1 | `mysql` | 关系型数据库 | 真正存业务数据（订单/客户/商品）+ 存"数据库的说明书" | 像一个自带的 SQLite，只不过是网络版的 |
| 2 | `elasticsearch` | 全文检索引擎 | 支持"按关键词模糊搜索"、能正确切中文词 | 像给数据库加了一个超强的搜索框 |
| 3 | `kibana` | ES 的图形界面 | 给人（不是给代码）看/调 ES 里的数据 | 像 Navicat / Adminer / MongoDB Compass |
| 4 | `qdrant` | 向量数据库 | 存"句子的向量"，支持"找最像的 N 条" | 像一个能做"语义相似度"排序的索引 |
| 5 | `embedding` | 向量化服务 | 把一句话变成 1024 个数字 | 一个 HTTP 接口：文本进去，数字数组出来 |

配置文件在 `docker/docker-compose.yaml:1-80`，一共 80 行，本文第 2 章会一行一行讲。

**一个重要事实**：本项目里跑在 Docker 里的**只有这 5 个基础设施服务**，Python 业务代码（`app/` 目录）是**跑在你本机上**的。证据：`conf/app_config.yaml:13-14` 里连数据库用的是 `host: localhost` + `port: 3308`——如果业务代码也在容器里，这里就该写容器名 `mysql` 而不是 `localhost` 了。

---

## 1. Docker 是什么（以及它**不是**什么）

### 1.1 先纠正一个最常见的误解

**Docker 容器 ≠ 虚拟机。**

| | 虚拟机（VMware / VirtualBox） | Docker 容器 |
|---|---|---|
| 里面跑什么 | 一整套完整的操作系统（含自己的内核） | 只跑一个程序 + 它需要的依赖库 |
| 内核 | 每个虚拟机**自带**一个内核 | **和宿主机共用同一个内核** |
| 体积 | 几 GB 起 | 几十 MB 到几百 MB |
| 启动时间 | 几十秒到几分钟 | 通常 1 秒内 |
| 类比 | 在你电脑里装了一台"完整的电脑" | 在你电脑里新开了一个"进程"，但把它隔离得很干净 |

所以你要这样理解：容器不是"小电脑"，而是**一个被隔离起来、自带全部依赖的进程**。它之所以能保证"在我机器上能跑，在你机器上也一定能跑"，是因为它把程序需要的运行环境（Python 版本、系统库、配置）都打包进了镜像里，而不是靠你本机装没装对。

补充一个 Windows 上的细节：Docker 容器共享的是 **Linux 内核**，而 Windows 本身没有 Linux 内核，所以你在 Windows 上装 Docker Desktop 时，它会在后台偷偷起一个**轻量 Linux 虚拟机**来提供这个内核。也就是说：Windows 上跑容器，底下确实有一层虚拟机，但**容器本身仍然不是虚拟机**——一台虚拟机里可以同时跑成百上千个容器，这正是区别所在。

### 1.2 六个必须知道的词

**① 镜像（image）= 安装包 / 类**
`mysql:8.0` 就是"MySQL 8.0 这个软件的安装包"。它只读、不会变、可以放在仓库里共享。类比：前端的 `node_modules` 压缩包，或者更准确一点——**一个装好一切的操作系统快照**。

**② 容器（container）= 安装包跑起来的那个实例 / 对象**
`docker run mysql:8.0` 之后产生的东西。镜像和容器的关系，就像 **class 和 new 出来的实例**、**镜像文件和挂载后的 ISO**。

**③ 端口映射（ports）= 把容器里的端口"接"到你电脑上**
```yaml
ports:
  - "3308:3306"
```
（`docker/docker-compose.yaml:11-12`）

这行的意思是：**你电脑（宿主机）的 3308 端口 → 容器内部的 3306 端口**。冒号前面是"外面能访问到的口"，后面是"容器里那个程序真正在听的口"。MySQL 在容器里永远听 3306，但你从外面访问时要用 3308。

为什么本机端口要用 3308 而不是 3306？合理推测是为了避开你本机可能**已经装过**的 MySQL（它默认占 3306）。不用担心对不上——`conf/app_config.yaml:14` 和 `:21` 里写的也是 3308，两边是配套的。

**④ 数据卷（volume）= 数据存在容器外面**
```yaml
volumes:
  - mysql_data:/var/lib/mysql          # docker/docker-compose.yaml:13-14
  - es_data:/usr/share/elasticsearch/data   # :32-33
  - qdrant_data:/qdrant/storage        # :57-58
```
以及文件末尾对三个卷的声明（`docker/docker-compose.yaml:77-80`）。

这是**最重要的一条**，务必理解：

> 容器是**用完即弃**的。如果你把 MySQL 容器删掉（`docker compose down` 甚至 `-v`），容器内部 `/var/lib/mysql` 里那一堆数据文件也会跟着消失。
> 但如果你把它"挂"在一个 volume 上，数据实际是存在**宿主机的 Docker 管理目录**里的；容器删了再重建，卷还在，数据还在。

类比最贴切的其实是：**容器像浏览器的无痕窗口，volume 像你同步到硬盘的用户目录**。无痕窗口一关，窗口里的东西没了；但只要文件是落在你用同步盘挂载的目录里的，重开一个窗口它照样在。

**⑤ 镜像构建（build）= 基于别人的镜像再改一层**
```yaml
elasticsearch:
  build: ./elasticsearch    # docker/docker-compose.yaml:22-23
```
注意这里是 `build` 而不是 `image`——说明 ES 用的**不是官方镜像**，而是拿本目录 `docker/elasticsearch/Dockerfile` **自己烤**出来的镜像。原因见本文第 6 章（要装中文分词插件）。

**⑥ docker-compose = 一个 YAML 管多个容器**
如果没有它，你得手敲 5 条长长的 `docker run`（每条还带一堆 `-e`、`-p`、`-v`，只要写错一个字母就白干）。有了它，**一次配置，一条命令同时起 5 个服务**：

```yaml
services:      # docker/docker-compose.yaml:1
  mysql: ...
  elasticsearch: ...
  kibana: ...
  qdrant: ...
  embedding: ...
```

通用启动流程（Docker 的标准用法，不是本仓库文档里写死的命令）：

```bash
cd docker
docker compose up -d      # 后台启动全部 5 个服务；第一次会自动拉镜像/构建 ES 镜像
docker compose ps         # 看各服务状态
docker compose logs -f    # 看日志（起不来时第一件事）
docker compose down       # 停止并删除容器（卷会保留，数据不丢）
```

`restart: unless-stopped`（如 `docker/docker-compose.yaml:5`）表示"除非你手动停，否则容器挂了/电脑重启了都自动拉起来"，属于省心配置。

---

## 2. `docker/docker-compose.yaml` 逐服务精讲

### 2.1 mysql（`docker/docker-compose.yaml:3-20`）

```yaml
mysql:
  image: mysql:8.0                                            # :4
  container_name: mysql                                       # :5
  environment:
    MYSQL_ROOT_PASSWORD: Atguigu.123                          # :8
    MYSQL_USER: atguigu                                       # :9
    MYSQL_PASSWORD: Atguigu.123                               # :10
  ports:
    - "3308:3306"                                             # :11-12
  volumes:
    - mysql_data:/var/lib/mysql                               # :14
    - ./mysql:/docker-entrypoint-initdb.d                      # :15
  command:
    --character-set-server=utf8mb4                             # :17
    --collation-server=utf8mb4_general_ci                      # :18
  mem_limit: 768m                                              # :19
  cpus: "1"                                                    # :20
```

几个要点：

- **用了官方镜像 `mysql:8.0`**（`:4`），也就是"直接下载 MySQL 官方安装包"，不需要自己构建。
- **三个环境变量创建了两个账号**（`:8-10`）：`root`/超级用户，以及一个普通用户 `atguigu`。这个 `atguigu` 就是业务代码要用的账号——见 `conf/app_config.yaml:15-16`（user: atguigu）。
- **字符集强制 utf8mb4**（`:17-18`）。这一条对中文项目**至关重要**：`utf8mb4` 是"能完整存下中文、emoji"的编码。历史上有一种叫 `utf8` 的 MySQL 编码其实只能存 3 字节字符，会导致 emoji 报错，所以现在一律用 `utf8mb4`。
- **`:15` 这行是"魔法行"**：`./mysql`（也就是仓库里的 `docker/mysql/` 目录）被挂到了容器里的 `/docker-entrypoint-initdb.d`。

#### ⭐ 必须理解的机制：`/docker-entrypoint-initdb.d` 自动导库

MySQL 官方镜像有一条约定：**如果容器里的数据目录是空的（第一次启动），它会按文件名字母顺序，自动执行 `/docker-entrypoint-initdb.d` 下所有的 `.sql` / `.sql.gz` / `.sh` 文件。**

这正好解释了这个项目为什么"一启动就自带数据"：

- `docker/mysql/dw.sql`（318 行）会被自动执行 → 建出数仓库 `dw` 和 5 张表 + 灌入示例数据；
- `docker/mysql/meta.sql`（48 行）会被自动执行 → 建出元数据库 `meta` 和 4 张表。

按字母序 `dw.sql` 先于 `meta.sql` 执行，不过两个文件各自都只建自己的库（`dw.sql:3` 建 `dw`，`meta.sql:2` 建 `meta`），互不依赖，先跑谁都没关系。

> **踩坑提醒**：这个自动导入**只在"数据目录为空"时发生**，也就是**只有第一次启动有效**。
> 如果你后来改了 `dw.sql`（比如加了一张表），重新 `docker compose up` 是**不会**重新执行的——因为卷 `mysql_data` 里已经有数据了，MySQL 认为"这不是第一次启动"。
> 想重来一遍，需要把卷一起删掉（`docker compose down -v`，`-v` 就是删卷），或者进容器手动执行 SQL。
> **注意 `down -v` 会永久删掉你库里的数据**，这个项目里都是示例数据所以无所谓，真项目里千万别乱按。

### 2.2 elasticsearch（`docker/docker-compose.yaml:22-35`）

```yaml
elasticsearch:
  build: ./elasticsearch                                       # :23  ← 自建镜像！
  container_name: elasticsearch                                # :24
  environment:
    discovery.type: single-node                                # :27
    xpack.security.enabled: "false"                            # :28
    ES_JAVA_OPTS: "-Xms1g -Xmx1g"                              # :29
  ports:
    - "9200:9200"                                              # :31
  volumes:
    - es_data:/usr/share/elasticsearch/data                    # :33
  mem_limit: 2g                                                # :34
  cpus: "2"                                                    # :35
```

- **`:23` 用的是 `build`，不是 `image`**：这个 ES 是从 `docker/elasticsearch/Dockerfile` 现场构建出来的（原因：要装中文分词插件，见第 6 章）。**这意味着第一次启动会更慢**（要下载基础镜像 + 装插件），这是正常的。
- **`single-node`（`:27`）**：ES 天生是为"多台机器组成集群"设计的，各个节点要互相发现。开发环境只有一台，就显式告诉它"我就一个节点，别找了"。不写这条，ES 会一直尝试找其他节点，日志里刷一堆警告甚至起不来。
- **`xpack.security.enabled: false`（`:28`）**：ES 8.x 默认开启账号密码 + HTTPS，第一次用会非常麻烦（要生成证书、设密码）。开发环境直接关掉，这样代码里 `http://localhost:9200` 裸着连就行（印证：`app/clients/es_client_manager.py:11-12` 拼的 URL 就是纯 http，没有任何认证信息）。
- **`ES_JAVA_OPTS: "-Xms1g -Xmx1g"`（`:29`）**：ES 是 Java 写的，这两个参数是给 JVM 的"最小/最大堆内存"。设为相等是为了避免运行时反复扩缩容。**记住这个数：1G**，因为它是后面内存计算的组成部分。
- **端口 9200**（`:31`）是 ES 的 HTTP 接口端口；9300 是集群内部通信端口，这里没有暴露出来（单机不需要）。

### 2.3 kibana（`docker/docker-compose.yaml:37-48`）

```yaml
kibana:
  image: kibana:8.19.10                                        # :38
  environment:
    ELASTICSEARCH_HOSTS: http://elasticsearch:9200              # :42
  ports:
    - "15601:5601"                                             # :44
  depends_on:
    - elasticsearch                                            # :45-46
```

**Kibana 是什么？** 它就是 **Elasticsearch 的图形管理界面**。你可以这样记：

> ES 像数据库（没有界面，只能用 API / 代码操作），
> Kibana 像 Navicat / Adminer / MongoDB Compass ——一个能让你**用网页点着看数据**的客户端。

实际用起来就是：浏览器打开 `http://localhost:15601`（注意端口是 **15601**，不是 Kibana 默认的 5601——`:44` 把容器里的 5601 映射到了宿主机的 15601），进去之后有个叫 **Dev Tools** 的页面，可以手敲 ES 的查询语句看结果。**它不参与任何业务逻辑，纯粹是给人调试用的。**这一点很重要——本项目代码里**没有任何地方连接 Kibana**（你可以自己在仓库里搜 `kibana`，只会搜到 `docker-compose.yaml` 里这几行）。

两个细节值得注意：

- **`:42` 里写的是 `http://elasticsearch:9200`，用的是"服务名"而不是 `localhost`。** 因为在容器里，`localhost` 指的是**这个容器自己**（Kibana 容器里当然没有 ES）。Docker Compose 会自动给每个服务建立一个内部 DNS，所以容器之间可以直接用服务名 `elasticsearch` 互相访问。
  **对比一下**：本项目 Python 代码在宿主机上跑，所以 `conf/app_config.yaml:37` 用的是 `host: localhost`。**"谁和谁在同一个网络里"决定了你该写 `localhost` 还是服务名**——这是新手最容易搞混的一点。
- **`:45-46` 的 `depends_on`** 只保证"先启动 ES 容器，再启动 Kibana 容器"，**不保证 ES 已经完全就绪**。所以第一次启动时 Kibana 可能报几次连不上，等一会儿自己就好了。
- **端口 15601**（`:44`）：Kibana 容器里听 5601，故意映射到宿主机的 15601（避开本机可能已有的 5601）。

### 2.4 qdrant（`docker/docker-compose.yaml:50-60`）

```yaml
qdrant:
  image: qdrant/qdrant:v1.16                                  # :51
  ports:
    - "6333:6333"   # HTTP                                    # :55
    - "6334:6334"   # gRPC                                    # :56
  volumes:
    - qdrant_data:/qdrant/storage                             # :58
```

- **QDrant 是"向量数据库"**，它存在的唯一理由就是高效地做一件事：**"给我一串向量，找出库里最像的那 N 条"**。它是更专业的数据库（Rust 写的），不做事务、不做表关联，只做向量检索。详细解释见第 9 章。
- 它同时开了两个端口：**6333 走 HTTP**（REST，像普通接口一样用），**6334 走 gRPC**（二进制协议，性能更好）。本项目代码用的是 HTTP —— 看 `app/clients/qdrant_client_manager.py:12-13` 拼的是 `http://host:port`。
- 这里**没写 `mem_limit` 之外的特殊配置**，属于"开箱即用"，Qdrant 默认配置对开发足够。

### 2.5 embedding（`docker/docker-compose.yaml:62-75`）

```yaml
embedding:
  image: ghcr.io/huggingface/text-embeddings-inference:cpu-1.8    # :63
  ports:
    - "8081:80"                                                  # :67
  environment:
    MODEL_ID: /models/bge-large-zh-v1.5                          # :69
    MAX_CONCURRENT_REQUESTS: "16"                                # :70
    MAX_BATCH_TOKENS: "16384"                                    # :71
  volumes:
    - ./embedding/bge-large-zh-v1.5:/models/bge-large-zh-v1.5     # :73
```

- **`ghcr.io/huggingface/text-embeddings-inference`** 是 HuggingFace 官方出的 **TEI（Text Embeddings Inference）** 服务镜像。它的作用：**把"文本 → 向量"这个能力包装成一个 HTTP 服务**。
  也就是说，你不用在 Python 里 `pip install torch` 再加载几个 G 的模型（那样每次启动都要等很久、还很吃内存），而是让一个独立服务把模型加载好，你的代码只管发 HTTP 请求。
  **类比**：像一个专门干一件事的微服务 / Serverless 函数——输入字符串，输出 `[0.12, -0.03, ...]` 共 1024 个浮点数。
- **`cpu-1.8`** 后缀说明这是**CPU 版本**（不是 GPU 版本）。所以它在你的笔记本上就能跑，但速度是"够用"级别——把一段文本变成向量大概几十到几百毫秒。
- **`:67` 端口 `8081:80`**：TEI 容器内部听 80 端口，映射成宿主机的 8081。和 `conf/app_config.yaml:33` 的 `port: 8081` 对应。
- **`:69` `MODEL_ID: /models/bge-large-zh-v1.5`**：告诉 TEI "去容器里这个路径加载模型"。
- **`:73` 挂载**：把仓库里 `docker/embedding/bge-large-zh-v1.5/`（本地磁盘上的模型文件，约 1.3GB）挂进容器。**这就是为什么这个项目不需要联网下载模型**——模型文件已经躺在仓库目录里了（该目录被 `.gitignore:4` 忽略，所以不会提交到 Git，需要你自己准备）。
- **`:70-71` 两个性能参数**：`MAX_CONCURRENT_REQUESTS: 16` 表示最多同时处理 16 个请求；`MAX_BATCH_TOKENS: 16384` 表示一批最多处理 16384 个 token。这是防止并发太高把内存打爆的保护阈值。

### 2.6 三个命名卷（`docker/docker-compose.yaml:77-80`）

```yaml
volumes:
  mysql_data:
  es_data:
  qdrant_data:
```

末尾这三行是**声明**（不是定义内容），配合前面各服务的挂载使用。规则：

- `mysql_data:/var/lib/mysql`（`:14`）→ MySQL 的数据/账号/权限全在这里；
- `es_data:/usr/share/elasticsearch/data`（`:33`）→ ES 的索引数据；
- `qdrant_data:/qdrant/storage`（`:58`）→ Qdrant 的向量数据。

**注意 `embedding` 服务没有卷**（`:72-73` 是"目录挂载"而不是命名卷）——因为模型是只读的，服务本身也不产生需要保留的数据。

还有一点值得说清：`./mysql:/docker-entrypoint-initdb.d`（`:15`）和 `./embedding/...`（`:73`）这种以 `./` 开头的叫**绑定挂载（bind mount）**，是把宿主机上某个**具体目录**挂进去；而 `mysql_data:` 这种叫**命名卷（named volume）**，由 Docker 自己管理存储位置。一句话区别：

> **bind mount = "把项目里的这个文件夹借给容器用"；named volume = "借给容器一块 Docker 管理的硬盘"。**
> 前者适合"配置文件/初始化脚本/模型"这种**你源码里就有**的东西；后者适合"数据库数据"这种**程序运行时生成、你不关心它具体存在哪**的东西。

### 2.7 ⚠️ 内存与 CPU 配额：这是你最可能踩的坑

| 服务 | mem_limit | cpus | 出处 |
|---|---|---|---|
| mysql | 768m | 1 | `docker/docker-compose.yaml:19-20` |
| elasticsearch | 2g | 2 | `:34-35` |
| kibana | 2g | 1.5 | `:47-48` |
| qdrant | 512m | 1 | `:59-60` |
| embedding | 2g | 2 | `:74-75` |
| **合计** | **约 7.25 GB** | **7.5 核** | |

- 这些 `mem_limit` / `cpus` 是**有意压低的**（都是很"抠"的值，明显是照着开发机算过的），目的是防止某个服务失控吃满你整台电脑。
- **但总量摆在那里：光这 5 个容器就要预留约 7.25GB 内存。**再加上你本机的浏览器、编辑器、以及宿主机上跑的 Python（后面还会加载 LLM 客户端等依赖），**建议开发机至少 16GB 内存**。
- 内存不够时的典型症状，**按发生顺序**：
  1. 某个容器起来了又立刻退出 → `docker compose ps` 看到 `Exited`；
  2. ES 起不来 / 报 OOM → 因为它是内存大户（2g 限制 + 1g Java 堆）；
  3. Docker Desktop 整体卡死或被杀。
- **排查第一步永远是看日志**：`docker compose logs -f elasticsearch`。
- **如果你内存吃紧，最省事的两招**：
  1. **不写 SQL 调试时就把 Kibana 停掉**（`docker compose stop kibana`）——它占 2g，但**代码完全不需要它**，它是给人看的。这一招能立刻省下 2GB。
  2. 只启动你当前需要的服务：`docker compose up -d mysql qdrant`（Compose 支持指定服务名）。

---

## 3. MySQL 与关系型数据库基础（给前端的最小知识集）

### 3.0 先给一个"你能立刻懂"的类比

如果你写过前端的状态管理，可以这样对号入座：

| 数据库概念 | 通俗解释 | 前端类比 |
|---|---|---|
| 数据库（database） | 一个"命名空间"，里面装很多表 | 一个大模块 / 一个命名空间 |
| 表（table） | 一类数据的集合，有固定的列结构 | 一个数组 `[{}, {}, ...]`，且每条对象的字段固定 |
| 行（row / record） | 一条具体数据 | 数组里的一个对象 |
| 列（column / field） | 一个字段 | 对象的 key，但有**固定类型**（字符串/数字/时间） |
| 主键（primary key） | 能**唯一标识**一行的字段 | 列表渲染时的 `key`，但更强：它保证不重复、不能为空 |
| 外键（foreign key） | 指向另一张表主键的字段 | 一个"引用/指针"，像 `order.customerId → customer.id` |
| 索引（index） | 为了"查得快"额外建立的数据结构 | 像给数组建了一个 Map，从"遍历找"变成"直接查" |
| SQL | 用来操作数据库的语言 | 一种声明式的"查询 DSL"（像你在 GraphQL 里描述你要什么） |

**为什么需要"关系型"？** 因为数据之间有关联：一个订单属于某个客户、某个商品、某个地区、某一天。关系型数据库的核心能力就是**用 SQL 把这些表按 key 拼起来**（`JOIN`），并且保证一致性。

**MySQL 的角色**：MySQL 就是这类数据库里最流行的一个开源实现（同类还有 PostgreSQL、Oracle、SQL Server）。在本项目里，MySQL 是**唯一存真实业务数据的地方**，两个库分别是 `dw` 和 `meta`。

### 3.1 用真实 SQL 看这些概念

拿本项目 `docker/mysql/dw.sql:9-15` 举例：

```sql
CREATE TABLE dim_region
(
    region_id   VARCHAR(20) PRIMARY KEY,   -- 主键
    province    VARCHAR(50),               -- 普通列
    region_name VARCHAR(50),
    country     VARCHAR(50)
);
```

- `VARCHAR(20)` = "最多 20 个字符的变长字符串"。前端的类比就是"这个字段是 string"。
- `PRIMARY KEY` = 主键。`region_id` 是主键意味着：**不可能有两行 `region_id` 一样，也不允许为空**。
- 这张表的数据（`docker/mysql/dw.sql:18-23`）：
  ```
  ('R001', '广东省', '华南', '中国'),
  ('R002', '浙江省', '华东', '中国'),
  ```
  一行 = `{ region_id: 'R001', province: '广东省', region_name: '华南', country: '中国' }`。

### 3.2 索引是什么？为什么它能变快？

数据库的表默认是"一堆行按插入顺序堆在那儿"。你要找 `province = '广东省'`，数据库只能**一行一行扫**（这叫全表扫描）。

**索引就是额外维护的一份"排好序的目录"**：像书的目录，或者像 JS 里的 `Map`。建了索引之后，找 `'广东省'` 就不用扫全表了。

代价是：**索引占空间，而且每次插入/更新数据都要顺手更新索引**（写变慢一点，换读变快）。所以索引不是越多越好。

> **本项目的一个真实观察**：`docker/mysql/dw.sql` 全文里，**除了 `PRIMARY KEY` 之外没有创建任何其他索引**（可以自己搜 `INDEX` / `KEY`，只有主键那些）。这是合理的——示例数据量太小（`fact_order` 才 115 行，见 `docker/mysql/dw.sql:204-318`），建不建索引都快。但是**这里正好演示了一个真实工程问题**：数据量上去之后，这种设计是要补索引的。

### 3.3 外键：为什么本项目"有外键但没约束"

`fact_order` 里有 `customer_id` / `product_id` / `date_id` / `region_id` 四个字段（`docker/mysql/dw.sql:195-198`），它们**语义上**分别指向 4 张维度表的主键。

但**仔细看建表语句，并没有 `FOREIGN KEY` 约束**（`docker/mysql/dw.sql:192-201` 只有字段定义，没有任何 `FOREIGN KEY ... REFERENCES ...`）。这是一个**有意的、很常见的工程选择**：

- 数据库层面加外键约束 → 插入数据时数据库会帮你检查"这个 customer_id 是否存在"，但**每次写入都要额外查一次**，批量导数据时会明显变慢。
- 数仓场景（尤其是导数据）通常**只在应用层/文档层保证一致性，不用数据库外键**。
- 而"这个字段是外键、指向哪张表"这件事，本项目是用**另一套机制**记录的——也就是下一章的 `meta` 库（比如 `conf/meta_config.yaml:130-133` 明确写了 `customer_id` 的 `role: foreign_key`、`description: 关联客户维度的外键`）。

**这是个很好的例子**：数据（`dw` 库）和"对数据的描述"（`meta` 库）被分开了。为什么要这样分，见 3.5。

### 3.4 SQL 长什么样

一条典型 SQL 长这样（本项目仓库里还没有真实的查询语句，这句是**通用示例**，用来帮你理解语法）：

```sql
SELECT d.region_name, SUM(f.order_amount) AS gmv
FROM fact_order f
JOIN dim_region d ON f.region_id = d.region_id
GROUP BY d.region_name
ORDER BY gmv DESC;
```

读法（跟 JS 对照）：

- `FROM fact_order f` —— 从事实表开始，起了个别名 `f`（像 `const f = fact_order`）；
- `JOIN dim_region d ON f.region_id = d.region_id` —— 把地区表按 key 拼进来（像用 `Map` 做一次 `map.get(f.region_id)` 再合并对象）；
- `GROUP BY d.region_name` —— 按地区分组（像 `groupBy`）；
- `SUM(f.order_amount)` —— 组内求和（像 `reduce`）；
- `ORDER BY gmv DESC` —— 按结果降序排。

**"问数"这类产品要做的事，本质就是：把用户的中文问题，翻译成上面这种 SQL。**

### 3.5 为什么要分成两个库：`dw` 和 `meta`

这是整个项目设计里最值得前端开发者理解的一点。

- **`dw`（data warehouse，数据仓库）**：存**业务数据本身**。订单、客户、商品、地区、日期。见 `docker/mysql/dw.sql`。
- **`meta`（元数据）**：存**对数据的描述**，也就是"描述数据库的数据库"。每张表叫什么、每个字段是什么含义、什么类型、有哪些别名、哪些字段是度量、有哪些指标。见 `docker/mysql/meta.sql`。

**为什么必须分开？举例说明：**

用户问"上个月华南的销售额是多少"，机器需要知道：
1. "华南"对应哪个字段？→ 需要知道 `dim_region.region_name` 这个字段存在，且它的中文别名包含"地区/区域/大区"；
2. "销售额"对应哪个公式？→ 需要知道有一个叫 GMV 的指标，等于 `SUM(fact_order.order_amount)`。

这些信息**不是数据，而是"关于数据的知识"**。如果不单独存：

- 难道要写死在代码里？那换一个数据库（换客户、换业务）就得改代码——**产品就没法复用**；
- 难道从表结构里反推？**做不到**。`order_amount` 这个字段名，机器不可能自己推出它中文叫"销售额/订单金额/收入"，也不知道"销售额"还缺一个 `SUM()`。字段的**业务含义**只有人知道，必须人工标注后存下来。

所以本项目的思路是：

> **`dw` 是"数据"，`meta` 是"数据的说明书"。**
> 用户问一句话，先去 `meta` 里查出"该用哪些表、哪些字段、哪个指标"，再拿这个结果去 `dw` 里写 SQL 取数。

而这份"说明书"的内容，最终来源于人工编写的 `conf/meta_config.yaml`（176 行，里面给每张表、每个字段、每个指标都写了中文描述和别名）。计划中的流程是：读这个 YAML → 写进 `meta` 库的 4 张表（见 `app/services/meta_knowledge_service.py:21-38`，**注意这里是骨架代码，关键步骤还是 `pass`，尚未实现**）。

---

## 4. `docker/mysql/dw.sql`：星型模型（数仓的经典套路）

### 4.1 5 张表的结构

`docker/mysql/dw.sql` 建了 `dw` 库（`:3`）和 5 张表：

| 表名 | 类型 | 主键 | 行数（示例数据） | 存什么 | 出处 |
|---|---|---|---|---|---|
| `dim_region` | 维度表 | `region_id` | 6 | 地区：省 / 大区 / 国家 | `:9-23` |
| `dim_customer` | 维度表 | `customer_id` | 20 | 客户：姓名 / 性别 / 会员等级 | `:27-55` |
| `dim_product` | 维度表 | `product_id` | 15 | 商品：名称 / 品类 / 品牌 | `:60-83` |
| `dim_date` | 维度表 | `date_id` | 90 | 日期：年 / 季 / 月 / 日 | `:88-187` |
| `fact_order` | **事实表** | `order_id` | 115 | 订单：数量 / 金额 + 4 个外键 | `:192-318` |

（行数来自各 `INSERT` 语句的行数，比如 `dim_region` 在 `:18-23` 有 6 行。）

### 4.2 什么是"星型模型"

想象把这 5 张表画在纸上：

```
        dim_date              dim_region
             \                    /
              \                  /
   dim_customer ——  fact_order  —— dim_product
```

**中间一张事实表，四周发散出去若干维度表**——形状像一颗星星，所以叫**星型模型（star schema）**。这是数据仓库最经典、最常见的建模方式。

规则只有两条：

**① 维度表（dimension table）= 存"按什么角度看"（描述性属性）**
`dim_region` 里存的是"地区叫什么、属于哪个大区"，`dim_customer` 里存的是"客户叫什么、什么性别、什么等级"。它们都是**用来筛选、分组、打标签**的。它们通常很小（这里最多 90 行），而且**很少变**（广东永远是广东）。

**② 事实表（fact table）= 存"发生了什么" + 可累加的数字（度量）**
`fact_order` 一行 = 一笔订单。看 `docker/mysql/dw.sql:192-201`：

```sql
CREATE TABLE fact_order
(
    order_id       VARCHAR(30) PRIMARY KEY,   -- 主键
    customer_id    VARCHAR(20),   -- 外键 → dim_customer
    product_id     VARCHAR(20),   -- 外键 → dim_product
    date_id        INT,           -- 外键 → dim_date
    region_id      VARCHAR(20),   -- 外键 → dim_region
    order_quantity INT,           -- 度量：数量
    order_amount   FLOAT          -- 度量：金额
);
```

**这条设计规律值得记一辈子**：

> **事实表 = 外键（指向各个维度） + 度量（数字，能 SUM/AVG 的）**
> **维度表 = 描述性文字（用来做筛选条件和分组标签）**

**③ 什么是"度量（measure）"？**
就是**能算总和、平均值的数字**。`order_quantity`（买了几个）能加起来，`order_amount`（花了多少钱）也能加起来。而 `customer_name` 不能"加起来"——那是维度。本项目在 `conf/meta_config.yaml:154-164` 里明确把这两个字段标成了 `role: measure`，其他字段标成 `dimension`，这就是"度量 vs 维度"的机器可读定义。

### 4.3 一条真实数据是怎么串起来的

以 `docker/mysql/dw.sql:204` 这一行为例：

```
('ORD20250101001', 'C001', 'P001', 20250101, 'R001', 1, 8999.00)
```

翻译成人话（把 4 个外键拿去各维度表里查）：

| 字段 | 值 | 查出来的含义 | 查哪里 |
|---|---|---|---|
| `order_id` | ORD20250101001 | 订单号 | — |
| `customer_id` | C001 | **李伟**，男，黄金会员 | `dw.sql:36` |
| `product_id` | P001 | **iPhone 15 Pro**，手机数码，苹果 | `dw.sql:69` |
| `date_id` | 20250101 | 2025 年 1 月 1 日，Q1 | `dw.sql:98` |
| `region_id` | R001 | 广东省，**华南** | `dw.sql:18` |
| `order_quantity` | 1 | 买了 1 件（度量） | — |
| `order_amount` | 8999.00 | 花了 8999 元（度量） | — |

于是"2025 年 1 月 1 日华南地区李伟买了一台 iPhone，花了 8999 元"——**这就是星型模型的价值：把一句业务事实拆成"一笔交易记录 + 4 个指针"，避免重复存储**。

如果不用星型模型，你得在订单表里把"李伟/男/黄金/iPhone 15 Pro/手机数码/苹果/广东省/华南/中国/2025/Q1"全部抄一遍——115 行订单就要抄 115 遍，改一个商品名要改 100 多行。**这就是"规范化/拆表"的意义。**

### 4.4 为什么要专门有一张 `dim_date`

`dim_date`（`docker/mysql/dw.sql:88-95`）的字段是 `date_id / year / quarter / month / day`，示例数据是 `20250101, 2025, 'Q1', 1, 1`（`:98`）。

为什么不直接在事实表里存一个日期字符串，还要单独建表？因为**"按季度统计"这种需求非常常见**。如果只有日期，你得在 SQL 里写 `CASE WHEN month IN (1,2,3) THEN 'Q1' ...`；有了 `dim_date`，"季度"就是普通字段，直接 `GROUP BY quarter` 就行。

**这也是"维度表"的通用价值：把计算、映射、枚举这些事提前算好存起来，让查询变简单。**

---

## 5. `docker/mysql/meta.sql`：描述数据库的数据库

### 5.1 4 张表

`docker/mysql/meta.sql` 建了 `meta` 库（`:2`）和 4 张表：

| 表 | 存什么 | 出处 |
|---|---|---|
| `table_info` | 每张表的编号 / 名称 / 类型（fact 还是 dim）/ 描述 | `:8-14` |
| `column_info` | 每个字段的编号 / 名称 / 类型 / 角色 / 示例 / 描述 / 别名 / 属于哪张表 | `:19-29` |
| `metric_info` | 业务指标（如 GMV）的编码 / 名称 / 描述 / 关联字段 / 别名 | `:32-39` |
| `column_metric` | "字段 ↔ 指标"的多对多关联表 | `:43-48` |

### 5.2 逐字段对照（以 `column_info` 为例）

`docker/mysql/meta.sql:19-29`：

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

- **`COMMENT`** 是 MySQL 的"列注释"，纯粹给人/工具看的，写进数据库后可以用 `SHOW FULL COLUMNS FROM column_info` 查出来。本项目大量使用它，**等于把文档写进了数据库里**。
- **`role` 字段是整个设计的核心**：`primary_key` / `foreign_key` / `measure` / `dimension`。机器读到 `role='measure'` 就知道"这个字段可以 SUM"，读到 `role='dimension'` 就知道"这个字段可以用来分组/筛选"——**这就把上一章的"度量 vs 维度"变成了机器可读的数据**。
- **`examples` 和 `alias` 用了 `JSON` 类型**：MySQL 8 支持存 JSON（像 `["地区", "区域", "大区"]` 这样一个数组）。为什么用 JSON 而不是另建表？因为这是"一份随时可能变长的标签列表"，建关联表太重。**前端类比**：就像你在一个字段里直接存了一个数组，而不用为它开一张关联表。
- **`table_id` 是事实上的外键**：指向 `table_info.id`，表达"这个字段属于哪张表"。但**和 `dw.sql` 一样，这里也没有写 `FOREIGN KEY` 约束**（`meta.sql:28` 只是一个普通列）。

**`alias`（别名）是干什么用的？** 用户不会严格说"region_name"，他会说"地区"、"区域"、"大区"。这些同义词就写在 `alias` 里，检索的时候都能命中同一个字段。真实数据来源见 `conf/meta_config.yaml:21`（`alias: [地区, 区域, 大区]`）。**这是"中文问数"能work的关键之一。**

### 5.3 `column_metric`：联合主键是什么

```sql
CREATE TABLE column_metric
(
    column_id VARCHAR(64) COMMENT '列编号',
    metric_id VARCHAR(64) COMMENT '指标编号',
    PRIMARY KEY (column_id, metric_id)     -- docker/mysql/meta.sql:47
);
```

注意这是**两个字段一起做主键**，叫**联合主键（composite primary key）**。含义是：

> 单独一个 `column_id` 可以重复出现，单独一个 `metric_id` 也可以重复出现，
> 但 **`(column_id, metric_id)` 这一对组合不能重复**。

**为什么要这样设计？** 因为指标和字段之间是**多对多**关系：GMV 要用到 `order_amount`，将来可能还有一个指标也要用 `order_amount`；反过来一个字段也可能被多个指标用到。这种"多对多"在关系型数据库里的标准解法就是**中间表（junction table）**。

**前端类比**：这就像"标签系统"——一篇文章可以有多个标签，一个标签可以属于多篇文章，于是需要一张 `article_tag(article_id, tag_id)` 表，且这对组合唯一。

### 5.4 这 4 张表 ↔ 代码里的 ORM 类

代码里用 **SQLAlchemy**（Python 生态最主流的 ORM）把这些表映射成类：

| 数据库表 | ORM 类 | 定义文件 | 备注 |
|---|---|---|---|
| `table_info` | `TableInfoMySQL` | `app/models/table_info.py:6-24` | `__tablename__ = "table_info"`（`:8`） |
| `column_info` | `ColumnInfoMySQL` | `app/models/column_info.py:7-42` | `__tablename__ = "column_info"`（`:8`） |
| `metric_info` | `MetricInfoMySQL` | `app/models/metric_info.py:7-30` | `__tablename__ = "metric_info"`（`:8`） |
| `column_metric` | `ColumnMetricMySQL` | `app/models/column_metric.py:6-18` | 两个 `primary_key=True`（`:11`、`:16`）就是联合主键 |

> **一处需要更正的说法**：常见说法是"`app/models/` 下有 5 个 ORM 类"——**准确的说法是 4 个表对应的 4 个 ORM 类，另外还有一个公共基类**。
> `app/models/base.py:3` 定义的是 `class Base(DeclarativeBase)`，它是所有 ORM 类的**父类**（每个模型文件都 `from app.models.base import Base`，如 `app/models/table_info.py:4`），它**不对应任何一张表**。
> 这个 `Base` 的作用（`app/models/base.py:1`）是提供 SQLAlchemy 2.0 的"声明式基类"：你可以把它理解成**前端里的一个抽象基类/接口**，子类继承它之后就自动具备"能被映射成数据库表"的能力。

顺带解释一个 ORM 概念（**ORM = Object Relational Mapping，对象关系映射**）：

```python
id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="列编号")
```
（`app/models/table_info.py:9-13`）

这一行同时说了三件事：① Python 里 `id` 是字符串类型（`Mapped[str]`）；② 数据库里它是 `VARCHAR(64)`（`String(64)`）；③ 它是主键。**ORM 的价值就是：让你用写类的方式描述表结构，不用手写 `CREATE TABLE`，而且类型检查/IDE 补全都能用上。** 前端类比：很像 Prisma / TypeORM 的 schema 定义。

### 5.5 代码怎么连 `meta` 库

两处明确的证据：

- `app/clients/mysql_client_manager.py:24`：`meta_mysql_client_manager = MySQLClientManager(app_config.db_meta)` —— 全局单例，专门连 `meta` 库（配置来自 `conf/app_config.yaml:12-17`，`database: meta`）。
- `app/scripts/build_meta_knowledge.py:15-21`：`build()` 函数先 `meta_mysql_client_manager.init()`，再开 session、构造 `MetaKnowledgeService`，最后 `close()`。这是**这个脚本负责"把 `conf/meta_config.yaml` 里的知识写进 `meta` 库"** 的入口。

⚠️ **诚实标注**：`app/services/meta_knowledge_service.py:21-38` 目前是**骨架**——只有 `for` 循环和注释（`# table -> table_info`、`# column -> column_info`），真正的写入操作还是 `pass`。`app/repositories/mysql/meta/meta_mysql_repository.py:4-7` 也只有一个空的 `__init__`。**也就是说"写库"这一步尚未实现，`meta` 库现在是空的 4 张表。** 不要去猜测它已经实现了什么。

---

## 6. Elasticsearch + IK 分词：为什么这个项目要自建 ES 镜像

### 6.1 ES 是什么

**Elasticsearch（简称 ES）是一个"专门用来搜东西"的数据库。** 它的核心能力和 MySQL 完全不同：

| | MySQL | Elasticsearch |
|---|---|---|
| 擅长 | 精确查询、事务、表关联 | **全文检索**（模糊、分词、相关度排序） |
| 查询方式 | `WHERE name LIKE '%苹果%'` | 把文本切成词，按词命中，还能算"哪条更相关" |
| 类比 | 一本**按编号排列**的档案柜 | 一本书**后面的"关键词索引"** |

### 6.2 "倒排索引"是什么（这是 ES 的灵魂）

普通数据库的索引是"**文档 → 词**"（我知道第 3 行有"苹果"）。

**倒排索引是反过来的：词 → 文档列表**：

```
苹果   → [文档1, 文档7, 文档9]
手机   → [文档1, 文档3]
华为   → [文档3, 文档5]
```

这样你搜"华为手机"，ES 直接拿到 `华为` 的列表和 `手机` 的列表，**求交集**就得到结果——不需要扫任何一行数据。

**前端类比**：就像你自己写一个搜索，不用 `list.filter(item => item.title.includes(q))`（那要遍历所有数据），而是提前建好 `Map<string, Set<id>>`，查询时直接 `map.get(词)`。

### 6.3 和 MySQL 的 `LIKE` 比，强在哪

假设数据里有"iPhone 15 Pro"这个词。用 MySQL 写 `WHERE product_name LIKE '%手机%'`：

- **找不到**。因为 `LIKE '%手机%'` 是纯粹的**字符子串匹配**——必须字面包含"手机"两个字。而 `iPhone 15 Pro` 里没有"手机"这两个字，尽管它明明是一部手机。

ES 的做法是：

1. **建索引时**把"手机数码"这类文本**切成词**（分词），并记录每个词出现在哪些文档；
2. **查询时**对查询词也分词，然后按"词"匹配，还能给结果**打分排序**。

所以 ES 能解决的问题是：**"我不确定用户会用什么词，但我要把语义上相关的东西找出来"**。

`LIKE '%xxx%'` 还有另外两个问题：① 前导通配符（开头的 `%`）会导致**无法使用索引、必然全表扫描**，数据量一大就慢到不可用；② 它**没法排序**——匹配上了就是匹配上了，没有"哪条更相关"的概念。

### 6.4 ⭐ 为什么必须自建镜像装 IK 插件

**ES 默认的分词器不认识中文词。** 它按"一个字符一个字符"或者"一整串不切"的方式处理中文，结果就是：

- 输入"中华人民共和国"，ES 可能切成 `中`/`华`/`人`/`民`/...，全是单字，**"华人"这种词就搜不准**；
- 或者当成一个整体，**只有完整输入才有结果**。

**IK 分词器（elasticsearch-analysis-ik）就是中国人写的中文分词插件**，它让 ES 能按"词"切分中文，比如把"中华人民共和国"切成 `中华人民共和国` / `中华人民` / `中华` / `人民` / `共和国` 等。

因为官方 ES 镜像里**没有**这个插件，所以本项目**必须自己构建镜像**。看 `docker/elasticsearch/Dockerfile` 全文（12 行）：

```dockerfile
FROM elasticsearch:8.19.10                                          # :1

USER root                                                            # :3

COPY plugins/elasticsearch-analysis-ik-8.19.10.zip /tmp/             # :5

RUN /usr/share/elasticsearch/bin/elasticsearch-plugin install --batch \
    file:///tmp/elasticsearch-analysis-ik-8.19.10.zip                # :7-8

RUN chown -R elasticsearch:elasticsearch /usr/share/elasticsearch/plugins   # :10

USER elasticsearch                                                   # :12
```

**逐行讲解（Dockerfile 就是"从一个基础镜像开始，一步步改"的脚本）：**

| 行 | 做什么 | 为什么 |
|---|---|---|
| `:1` | 以官方 `elasticsearch:8.19.10` 为基础 | 版本必须和 Kibana 的 `8.19.10`（`docker-compose.yaml:38`）严格一致，否则 Kibana 连不上 |
| `:3` | 切成 `root` 用户 | 因为下一步要往系统目录里写文件。**ES 官方镜像默认不是 root**（出于安全考虑），所以这里必须显式提权 |
| `:5` | 把插件 zip 复制进镜像的 `/tmp/` | 注意源路径写的是 `plugins/...`（**相对路径**）——它是相对于"构建上下文"的，也就是 `docker-compose.yaml:23` 里的 `build: ./elasticsearch`，所以实际文件在 `docker/elasticsearch/plugins/elasticsearch-analysis-ik-8.19.10.zip`（约 4.6MB） |
| `:7-8` | 调 ES 自带的插件管理命令安装这个 zip | `file://` 表示"从本地文件装"，`--batch` 表示"不要交互式问我 yes/no"（构建过程不能有人回答） |
| `:10` | 把插件目录的所有者改成 `elasticsearch` 用户 | 上一步是 root 装的，文件属主是 root；不改的话普通用户跑 ES 时读不了插件 |
| `:12` | 切回 `elasticsearch` 用户 | **安全最佳实践**：容器里的程序不应该以 root 跑 |

**这个 zip 里有什么？** 我解压列过它的条目（22 个），关键的是这些词典文件：

```
config/main.dic                        ← 主词典（几万个中文词）
config/surname.dic                     ← 姓氏词典（"张""李"等，为了人名分词准）
config/quantifier.dic                  ← 量词（"个""件""台"）
config/stopword.dic                    ← 停用词（"的""了"这种没信息量的词）
config/IKAnalyzer.cfg.xml              ← 配置文件
elasticsearch-analysis-ik-8.19.10.jar  ← 插件本体
```

**"分词到底按什么切"完全由这些 `.dic` 词典决定**，所以 IK 后面还可以加自定义词典（把公司内部黑话、商品名塞进去），这也是为什么中文搜索经常需要"调词典"。

### 6.5 代码怎么连 ES

- 配置：`conf/app_config.yaml:36-39`（`host: localhost`、`port: 9200`、`index_name: data_agent`）。
- 客户端：`app/clients/es_client_manager.py:11-15` 拼出 `http://localhost:9200`，用 `AsyncElasticsearch` 连接；`:20` 导出全局单例 `es_client_manager`。

⚠️ **诚实标注**：`app/clients/es_client_manager.py:22-51` 那段 `if __name__ == '__main__'` 是**连通性验证脚本**（建了个叫 `books` 的索引、插了一条 Snow Crash 的书、再查出来）——这是**学语法用的 demo，不是业务逻辑**。仓库里目前**没有**真正的 ES 业务代码（真正的索引名应该是 `data_agent`，来自 `conf/app_config.yaml:39`，而 demo 里写的是 `books` 硬编码）。`app/repositories/es/` 目录目前是**空的**（只有一个空 `__init__.py`）。

---

## 7. Kibana：ES 的图形界面

已经讲过核心结论，这里补充"你实际会怎么用它"：

1. 启动后浏览器打开 **`http://localhost:15601`**（`docker/docker-compose.yaml:44` 把容器里的 5601 映射成了宿主机 15601；**所以宿主机上的 5601 是访问不到的**，一定用 15601）；
2. 左侧菜单找到 **Dev Tools**；
3. 里面可以手敲 ES 的 REST 请求，比如：
   ```
   GET data_agent/_search
   {
     "query": { "match": { "product_name": "手机" } }
   }
   ```
   点一下执行就能看到结果——**不用写任何 Python 代码就能验证"数据进 ES 了吗""分词切对了吗"**。

**为什么开发时特别需要它？** 因为 ES 里存的数据你没法像 MySQL 那样随便找个客户端看（ES 的数据结构是 JSON 文档，不是表）。没有 Kibana，你只能靠 `curl` 敲命令。**它的定位就是"调试工具"，代码永远不会连它。**

---

## 8. embedding（向量）与 `bge-large-zh-v1.5` 模型

### 8.1 什么是"向量"（embedding）

**一句话：embedding 就是把一段文本变成一串固定长度的数字。**

比如把这三个句子喂给模型：

| 句子 | 变成（示意，真实是 1024 个数，这里只写 3 位） |
|---|---|
| "怎么退款" | `[0.82, 0.11, -0.35, ...]` |
| "我要退货" | `[0.80, 0.13, -0.31, ...]` |
| "今天天气真好" | `[-0.44, 0.91, 0.02, ...]` |

关键规律：

> **意思相近的句子，它们的数字串也相近。**

"怎么退款"和"我要退货"意思几乎一样，所以我们看到它们的向量**每个位置上的数字都差不多**；"今天天气真好"跟它们意思无关，向量就**离得很远**。

**这就解决了一个纯靠字符串搜索永远做不到的事情**：用户说"我要退货"，但数据库里存的原文是"退款流程"——"退"和"货"这两个字虽然出现了，但**没有任何一个连续子串能匹配上**，`LIKE` 搜索完全失效。而向量搜索可以：因为两句话的**含义**接近。

**前端类比**：这就像把所有字符串都映射到一个高维坐标空间里的点，然后"找相似的句子"就变成了"找距离最近的点"——一个**几何问题**。

### 8.2 余弦相似度：怎么判断"像不像"

把两个向量想象成从原点出发的两支箭头。**余弦相似度**（cosine similarity）衡量的是**这两个箭头的夹角**，不是长度：

- 夹角 0°（方向完全一样）→ 相似度 = **1**（最像）；
- 夹角 90°（垂直，毫无关系）→ 相似度 = **0**；
- 方向相反 → 相似度 = **-1**。

公式（`·` 是点积，`||x||` 是长度）：

```
cos(A, B) = (A · B) / (||A|| × ||B||)
```

**为什么用夹角而不是直线距离？** 因为"句子的长短"会影响向量的长度。一句话长，它的向量可能整体数值更大，但**方向**才代表"意思"。用夹角就天然忽略了长短这个干扰。

这也解释了本项目的一个细节：模型的 `modules.json:14-19` 里最后一步是一个 **`Normalize`** 层——把向量长度归一化成 1。归一化之后，余弦相似度就退化成简单的点积，计算更快。（该目录里有 `modules.json` 声明了这个步骤；对应的 `2_Normalize` 目录内容未随模型一起存放在本仓库中。）

**⚠️ 一个非常实用的坑（来自模型自己的 README `docker/embedding/bge-large-zh-v1.5/README.md:118-133`）**：
BGE 系列模型的相似度分布集中在 `[0.6, 1]` 这个区间，所以"相似度 0.5 就算相似"是**错**的——0.5 在 BGE 里已经算很不像了。而且**真正有用的是"相对排序"，不是绝对值**（谁排第一才是关键）。要卡阈值也是 0.8 / 0.85 / 0.9 这种。

### 8.3 `bge-large-zh-v1.5` 是什么

- **bge** = **B**AAI **G**eneral **E**mbedding，由**智源研究院（BAAI）**训练的向量模型系列。
- `zh` = 中文版；`large` = 大号（约 3.26 亿参数）；`v1.5` = 改进版（相似度分布更合理）。
- 看看它的成绩（模型 README `docker/embedding/bge-large-zh-v1.5/README.md:346-348`）：在中文向量评测榜 **C-MTEB** 上平均分 64.53，**1024 维**，同尺寸里是第一梯队。
- 名称在配置里的两处出现：`conf/app_config.yaml:34`（`model: BAAI/bge-large-zh-v1.5`）和 `docker/docker-compose.yaml:69`（`MODEL_ID: /models/bge-large-zh-v1.5`）。

**它输出多少维？1024 维。** 三处互相印证：

1. `docker/embedding/bge-large-zh-v1.5/config.json:13` → `"hidden_size": 1024`；
2. `docker/embedding/bge-large-zh-v1.5/1_Pooling/config.json:2` → `"word_embedding_dimension": 1024`；
3. `conf/app_config.yaml:29` → `embedding_size: 1024`（Qdrant 建集合时必须用这个维度）。

> **这个"1024"是贯穿整个系统的关键数字**：TEI 产出的向量是 1024 个数，Qdrant 存的向量也必须是 1024 个数。**两边对不上就会直接报错**——这是把项目跑起来时很常见的一类错误。
> 代码里还有一处**明确的提示**：`app/clients/qdrant_client_manager.py:29` 的注释写着"正式建集合时应该用 `app_config.qdrant.embedding_size`（这里是 1024）"，而它下面的 demo（`:41`）为了演示用了 `size=4`（因为 demo 数据只有 4 个数）。**别把 demo 的 4 当成真实配置。**

### 8.4 模型目录逐文件说明

目录：`docker/embedding/bge-large-zh-v1.5/`（总大小约 1.3GB，**被 `.gitignore:4` 忽略，不在 Git 里，需要自己准备**）。

| 文件 | 大小 | 作用 | 出处 |
|---|---|---|---|
| `pytorch_model.bin` | **约 1242 MB** | **模型权重本体**——3.26 亿个学好的参数。整个目录 95% 的体积都在这里 | — |
| `config.json` | 小 | **模型结构配置**：多少层、多少头、向量多长 | `:13` hidden_size 1024；`:26` 24 层；`:24` model_type `bert`；`:23` 最长 512；`:39` 词表 21128 |
| `tokenizer.json` | 约 0.4 MB | **分词器的完整定义**（现代格式，词表 + 切词规则全在里面） | — |
| `vocab.txt` | 约 107 KB | **分词器词表**：一行一个 token，共 **21128** 行（和 `config.json:39` 的 `vocab_size: 21128` 完全对应）。开头是 `[PAD]`、`[unused1]`... 这类特殊符号，后面是中文单字 | `vocab.txt:1-8` |
| `tokenizer_config.json` | 小 | 分词器**行为配置**：特殊符号叫什么、是否转小写 | `:13` tokenizer_class `BertTokenizer`；`:4` `do_lower_case: true` |
| `special_tokens_map.json` | 小 | 定义 5 个特殊 token 的名字：`[CLS]` `[SEP]` `[PAD]` `[MASK]` `[UNK]` | `:2-6` |
| `1_Pooling/config.json` | 小 | **池化配置**——决定"怎么把一整句话的多个 token 向量合成一个句子向量" | `:3` `pooling_mode_cls_token: true`（取 `[CLS]` 位置的那个向量当句子向量） |
| `modules.json` | 小 | **处理流水线的清单**：① Transformer（跑模型）→ ② Pooling（合成句子向量）→ ③ Normalize（归一化） | `:1-20` |
| `sentence_bert_config.json` | 小 | 给 `sentence-transformers` 库读的配置 | `:2` `max_seq_length: 512`（一句话最长 512 个 token，超了会被截断） |
| `config_sentence_transformers.json` | 小 | 记录导出这个模型时用的库版本 | `:2-6` |
| `README.md` | 小 | **模型说明文档**（智源官方 FlagEmbedding 的 README，427 行） | `:84` 中文版说明；`:346-348` C-MTEB 成绩；`:118-133` 相似度分布注意事项 |
| `.gitattributes` | 小 | Git LFS 相关声明（Git 大文件追踪配置） | — |
| `.cache/huggingface/download/*.metadata` | 小 | HuggingFace 下载时留下的元数据（记录"这些文件是从哪下的"），**功能上可忽略** | — |

**把这些串起来理解一次**：一段中文文本进来 → 用 `tokenizer.json` + `vocab.txt` 切成 token（最多 512 个）→ 送进 `pytorch_model.bin` 这个 BERT 模型 → 得到每个 token 的 1024 维向量 → 按 `1_Pooling/config.json` 取 `[CLS]` 那个向量当作整句的表示 → 归一化 → **输出 1024 个数字**。

---

## 9. Qdrant：为什么不能用 MySQL 存向量

### 9.1 Qdrant 是什么

**Qdrant 是一个"向量数据库"。** 它只干一件事，但干得极快：

> **存一堆 `(向量, 附加信息)`，然后回答"哪 N 个向量跟这个查询向量最像？"**

它支持 HTTP（6333）和 gRPC（6334）两个接口（`docker/docker-compose.yaml:55-56`），你把它想象成一个"专门做相似度搜索的 API 服务"就够了。

### 9.2 为什么 MySQL 做不了这件事

理论上，你当然可以把 1024 个数字拼成一个字符串塞进 MySQL 的一列里，然后查询时全表捞出来、在 Python 里一个个算余弦相似度。**但代价是：**

| 问题 | MySQL 的做法 | Qdrant 的做法 |
|---|---|---|
| 怎么比 | 全表扫描 + 逐行算 | **ANN（近似最近邻）索引**，直接跳到最可能的那一片 |
| 复杂度 | 数据量 N → 算 N 次（O(N)） | 近似 O(log N) 级别 |
| 100 万条时 | 每条算 1024 次乘法 → 卡死 | 毫秒级返回 |
| 算相似度 | 数据库根本不认"向量"这个类型（MySQL 8 没有原生向量类型/距离算子） | 原生支持余弦/点积/欧氏距离 |

**Qdrant 的核心技术叫 HNSW**（一张"多层跳跃图"）——你可以先不深究，只需要知道：**它用"近似"换来了巨大的速度**，牺牲一点点精度换来几百倍的加速。对"找相似句子"这种场景，近似完全够用。

**前端类比**：这就像"模糊搜索时用倒排索引 vs 每次遍历整个数组"。数据小的时候二者没差别，数据一大就是"能用"和"不能用"的差别。

### 9.3 在 Qdrant 里的几个概念

代码 `app/clients/qdrant_client_manager.py:39-53` 演示得很清楚（这段是 demo，但概念是真的）：

```python
await client.create_collection(
    collection_name="test_collection_async",
    vectors_config=VectorParams(size=4, distance=Distance.COSINE),   # :39-42
)

await client.upsert(
    collection_name="test_collection_async",
    wait=True,                                                        # :46
    points=[
        PointStruct(id=1, vector=[0.05, 0.61, 0.76, 0.74], payload={"city": "Berlin"}),  # :48
        ...
    ],
)
```

| 概念 | 含义 | MySQL 里的对应物 |
|---|---|---|
| `collection`（集合） | 一组向量的容器 | **表（table）** |
| `VectorParams(size=..., distance=...)` | 声明"每条向量的维度"和"用什么距离算相似" | 列的类型定义 |
| `PointStruct` | 一条记录 = `id` + `vector` + `payload` | **一行（row）** |
| `payload` | 附带的任意 JSON（`{"city": "Berlin"}`），可以做过滤 | 其他普通列 |
| `Distance.COSINE` | 用余弦相似度 | 排序规则 |
| `query_points(..., limit=2)`（`:56-62`） | "找最像的 2 条" | `ORDER BY similarity DESC LIMIT 2` |

> **注意 `distance` 要和"模型怎么算相似"配套。** 本项目模型输出的是归一化向量（见 8.2），所以配 `COSINE` 是最自然的（也可以用 `DOT`）。如果建集合时选错距离函数，检索质量会明显变差。

### 9.4 代码怎么连 Qdrant

- 配置：`conf/app_config.yaml:26-29`（`host: localhost`、`port: 6333`、`embedding_size: 1024`）。
- 客户端：`app/clients/qdrant_client_manager.py:12-16` 拼出 `http://localhost:6333`，用 `AsyncQdrantClient` 连接；`:24` 导出单例 `qdrant_client_manager`。

⚠️ **诚实标注**：`app/repositories/qdrant/` 目录目前是**空的**（只有一个空 `__init__.py`），**没有真正的向量写入/检索业务代码**。看到的那段 `if __name__ == "__main__"` 是学习用的 demo。

---

## 10. TEI：把"文本转向量"包装成一个 HTTP 服务

### 10.1 它是什么，以及为什么需要它

**TEI（Text Embeddings Inference）是 HuggingFace 出的推理服务**——它把第 8 章那个模型**装进一个 HTTP 服务器里**。

不用它的做法是：在 Python 里 `import torch` + `SentenceTransformer(...)` 加载 1.3GB 模型。这样做的问题：

| 问题 | 后果 |
|---|---|
| 每次启动进程都要重新加载 1.3GB 模型 | 启动几十秒 |
| 模型占用大量内存，和业务代码抢 | 容易 OOM |
| 要装 PyTorch 全家桶 | 依赖体积巨大（GB 级） |
| 并发推理要自己写批处理 | 性能难调 |

用 TEI 之后：

> 模型加载一次、常驻在一个独立容器里（`docker/docker-compose.yaml:62-75`），业务代码只需 `POST http://localhost:8081/embed`，body 里带上文本，拿回 JSON 里的 1024 个数字。**这就是"把模型能力服务化"。**

**类比**：这和前端把某个重型计算放进 Web Worker 是同一个思路——不阻塞主流程，能力独立、可复用。

`docker/docker-compose.yaml:70-71` 的两个环境变量也是它在做"服务端优化"的证据：
- `MAX_CONCURRENT_REQUESTS: "16"` —— 最多同时处理 16 个请求，超了就排队；
- `MAX_BATCH_TOKENS: "16384"` —— **批处理**：多个请求的文本可以拼成一批一次算完，这比一个个算快得多（就像数据库的批量插入比逐条插入快）。

### 10.2 代码怎么连 embedding 服务

- 配置：`conf/app_config.yaml:31-34`（`host: localhost`、`port: 8081`、`model: BAAI/bge-large-zh-v1.5`）；
- 配置类：`app/conf/app_config.py:39-43` 定义了 `EmbeddingConfig`（三个字段：`host` / `port` / `model`），并在 `:63` 挂进了总配置 `AppConfig`。

⚠️ **诚实标注（重要）**：我在整个 `app/` 目录里搜过 `embedding` / `8081` / `TEI`，**结果显示：目前仓库里只有"配置"（`app/conf/app_config.py` 里那个 dataclass），还没有任何"调用 TEI 的客户端代码"**——没有 `embedding_client_manager.py` 之类的东西。
也就是说：**`EmbeddingConfig` 这个配置项已经被定义好了，但还没有人用它。**

（对比一下：MySQL / ES / Qdrant 都各有 `app/clients/*_client_manager.py`，只有 embedding 这个服务还没有对应的客户端文件。这大概是因为它是最"靠后"的一环，还没轮到实现。**结论：这一节讲的是"这个容器存在的目的"，不是"已经被调用的代码"。**）

---

## 11. 总表 + 排雷清单

### 11.1 5 个容器 ↔ 端口 ↔ 职责 ↔ 谁在连它

| 容器 | 镜像 / 构建 | 端口映射（宿主:容器） | 在项目里的职责 | 项目里谁在连它 |
|---|---|---|---|---|
| `mysql` | `mysql:8.0`（官方） | **3308**:3306 | 存**全部真实数据**：`dw` 库（订单/客户/商品/地区/日期）+ `meta` 库（元数据，4 张空表） | 配置 `conf/app_config.yaml:12-24`；客户端 `app/clients/mysql_client_manager.py:24-25`（两个单例，分别连 `meta` 和 `dw`）；使用方 `app/scripts/build_meta_knowledge.py:15-21` |
| `elasticsearch` | **`build: ./elasticsearch`**（自建，装 IK） | **9200**:9200 | 全文检索 / 中文分词，支持"模糊找相关" | 配置 `conf/app_config.yaml:36-39`；客户端 `app/clients/es_client_manager.py:11-20` |
| `kibana` | `kibana:8.19.10` | **15601**:5601 | ES 的**图形界面**，纯人工调试 | **无任何代码连接**（全仓库搜 `kibana` 只有 compose 文件） |
| `qdrant` | `qdrant/qdrant:v1.16` | **6333**:6333（HTTP）、**6334**:6334（gRPC） | 存向量、做"找最相似的 N 条" | 配置 `conf/app_config.yaml:26-29`；客户端 `app/clients/qdrant_client_manager.py:12-24` |
| `embedding`（TEI） | `ghcr.io/huggingface/text-embeddings-inference:cpu-1.8` | **8081**:80 | 文本 → 1024 维向量的 HTTP 服务 | 只有配置 `conf/app_config.yaml:31-34` + dataclass `app/conf/app_config.py:39-43`；**客户端代码尚未实现** |

另外，端口映射和配置文件的对应关系**必须一一对上**，这是新手最常见的一类错误：

| 服务 | compose 里的宿主端口 | 配置文件里写的端口 | 一致？ |
|---|---|---|---|
| mysql | 3308（`docker-compose.yaml:12`） | 3308（`conf/app_config.yaml:14`、`:21`） | ✅ |
| elasticsearch | 9200（`:31`） | 9200（`conf/app_config.yaml:38`） | ✅ |
| qdrant | 6333（`:55`） | 6333（`conf/app_config.yaml:28`） | ✅ |
| embedding | 8081（`:67`） | 8081（`conf/app_config.yaml:33`） | ✅ |
| kibana | 15601（`:44`） | —— | 无配置（不需要） |

### 11.2 把项目跑起来时最容易踩的 7 个坑

1. **内存不够**（最高频）。5 个容器要 ~7.25GB。症状是某容器反复退出或 ES 起不来。**先 `docker compose logs -f <服务名>`，再考虑停掉 Kibana（省 2GB）。** 出处：`docker/docker-compose.yaml:19-20, 34-35, 47-48, 59-60, 74-75`。
2. **以为改了 `dw.sql` 重启就会生效**。`/docker-entrypoint-initdb.d` 只在**第一次启动**（数据卷为空时）执行。要重来必须删卷 `docker compose down -v`（**会丢数据**）。出处：`:15`。
3. **ES 第一次启动很慢**。因为要现场构建带 IK 插件的镜像（`docker/elasticsearch/Dockerfile:1-12`）。不是卡死，是没跑完。
4. **Kibana 第一次连不上 ES**。`depends_on`（`:45-46`）只保证启动顺序，不保证 ES 就绪。等几十秒刷新即可。
5. **在容器里写 `localhost` 去连别的容器**。容器内的 `localhost` 是它自己。**容器之间用服务名**（如 Kibana 用 `http://elasticsearch:9200`，`:42`）；**宿主机上的代码用 `localhost`**（如 `conf/app_config.yaml:13`）。本项目业务代码在宿主机跑，所以配置里全写 `localhost`——**这是对的，别改**。
6. **`embedding` 服务起不来**。检查 `docker/embedding/bge-large-zh-v1.5/` 是否存在且完整（该目录被 `.gitignore:4` 忽略，**克隆仓库后它不会存在**，必须自己准备约 1.3GB 的模型文件，尤其不能缺 `pytorch_model.bin`（1242MB））。
7. **向量维度不匹配**。TEI 输出 1024 维（`config.json:13`），Qdrant 建集合必须也用 1024（`conf/app_config.yaml:29`）。代码里那个 `size=4` 是 demo（`app/clients/qdrant_client_manager.py:41`），不要照抄。

### 11.3 一句话记住每个概念

| 概念 | 一句话 |
|---|---|
| **MySQL** | 存数据的**关系型数据库**，用表/行/列组织，用 SQL 查询 |
| **数仓 `dw`** | 存**业务数据本身**（订单、客户、商品……） |
| **元数据库 `meta`** | 存**"关于数据的说明书"**（表叫什么、字段什么含义、指标怎么算），这是"中文问数"能翻译成 SQL 的关键 |
| **embedding（向量）** | 把一段文本变成一串数字（这里是 **1024** 个）；**意思相近 → 数字也相近** |
| **Qdrant** | 专门存向量、专门回答"最像的 N 条是谁"的数据库 |
| **Elasticsearch** | 用**倒排索引**做全文检索的引擎，擅长模糊找相关、能排序打分 |
| **IK 分词** | 让 ES 能按**中文词**切分（官方镜像没带，所以要自建 ES 镜像） |
| **Kibana** | ES 的**图形界面**，给人调试用，代码不连它 |
| **TEI** | 把"文本 → 向量"包装成一个 **HTTP 接口**的推理服务 |
| **Docker 镜像** | 装好一切的**安装包**（只读） |
| **Docker 容器** | 镜像**跑起来的实例**（可随时删）——**不是虚拟机**，共享宿主内核、轻得多 |
| **端口映射** | `3308:3306` = 宿主机 3308 → 容器 3306 |
| **Volume（数据卷）** | 数据存在容器**外面**，容器删了数据还在 |
| **docker-compose** | 用**一个 YAML** 把 5 个服务一次配好、一条命令同时起 |

---

## 12. 附录：本仓库基础设施部分的**实现进度**（如实标注）

读文档最怕被"看起来已经实现"的代码误导，所以这里专门把"哪些是真代码、哪些还是空壳/demo"列清楚：

| 位置 | 状态 | 依据 |
|---|---|---|
| `docker/docker-compose.yaml` | ✅ 完整可用的 5 服务编排 | 80 行，配置齐全 |
| `docker/elasticsearch/Dockerfile` + `plugins/*.zip` | ✅ 完整（含 IK 词典） | 12 行 + 22 个 zip 条目 |
| `docker/mysql/dw.sql` | ✅ 建库 + 建表 + 115 行示例数据 | 318 行 |
| `docker/mysql/meta.sql` | ✅ 建库 + 4 张表（**表是空的**，数据要靠脚本写入） | 48 行 |
| `docker/embedding/bge-large-zh-v1.5/` | ✅ 模型文件齐全（~1.3GB），**但被 .gitignore 忽略，需自行准备** | `.gitignore:4` |
| `app/clients/mysql_client_manager.py` | ✅ 真的客户端（含连接池）+ 一段可运行的验证脚本 | `:13-25` 为真代码 |
| `app/clients/es_client_manager.py` | ✅ 真的客户端；`:22-51` 是**语法 demo**（写死了 `books` 索引） | — |
| `app/clients/qdrant_client_manager.py` | ✅ 真的客户端；`:27-68` 是**语法 demo**（`size=4`，非真实维度） | — |
| **TEI / embedding 的客户端** | ❌ **不存在**（只有配置 `app/conf/app_config.py:39-43`） | 全仓库 grep 无调用 |
| `app/models/*.py` | ✅ 4 个 ORM 类 + 1 个基类（`base.py:3`） | 与 `meta.sql` 4 张表一一对应 |
| `app/repositories/mysql/meta/meta_mysql_repository.py` | ⚠️ **空壳**（只有 `__init__`） | 7 行 |
| `app/services/meta_knowledge_service.py` | ⚠️ **骨架**（关键步骤是 `pass`），注释里写明了计划做的 3 件事 | `:21-38` |
| `app/repositories/es/`、`app/repositories/qdrant/` | ❌ 空目录（只有空 `__init__.py`） | — |

所以现在的整体状态是：**基础设施（Docker 这几个文件）已经配齐了，Python 侧的"连接层"（clients）也通了，但"业务逻辑层"（repositories / services）大部分还是骨架。** 后面几篇文档会接着讲 `app/` 里的代码结构。
