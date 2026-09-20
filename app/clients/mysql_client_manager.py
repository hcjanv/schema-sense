from app.conf.app_config import  DBConfig, app_config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine, AsyncSession
import asyncio

class MySQLClientManager:
    def __init__(self, config: DBConfig):
        self.engine: AsyncEngine | None = None
        self.config = config

    def _get_url(self):
        return  f"mysql+asyncmy://{self.config.user}:{self.config.password}@{self.config.host}:{self.config.port}/{self.config.database}?charset=utf8mb4"

    # mysql + asyncmy: // atguigu: Atguigu.123 @ localhost: 3308 / dw?charset = utf8mb4
    # 数据库  异步驱动     用户名       密码               主机   端口      库名        字符集
    def init(self):
        self.engine = create_async_engine(self._get_url(), pool_size=10, pool_pre_ping=True) #池子里最多保留 10 个 长连接,每次从池里拿连接前先 ping 一下( 8 小时不活动就断开连接)

    async def close(self):
        await self.engine.dispose()

meta_mysql_client_manager = MySQLClientManager(app_config.db_meta) # ⑥ 页面级「全局单例」：元数据库
dw_mysql_client_manager = MySQLClientManager(app_config.db_dw)  # ⑦ 全局单例：数据仓库

if __name__ == "__main__":
    dw_mysql_client_manager.init()
    engine = dw_mysql_client_manager.engine

    async def test():
        async with AsyncSession(engine, autoflush=True, expire_on_commit=False) as session: # AsyncSession	「一次会话」，真正执行 SQL 的载体
            sql = "select * from fact_order limit 10"
            result = await session.execute(text(sql)) # text()把裸 SQL 字符串包成 SQLAlchemy 认识的对象	相当于给字符串套一层 new SQL() 的语义

            rows = result.mappings().fetchall()

            print(type(rows))
            print(type(rows[0]))
            print(rows[0])

    asyncio.run(test())