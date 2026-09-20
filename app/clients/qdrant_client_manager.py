import asyncio
from qdrant_client import AsyncQdrantClient #AsyncQdrantClient ：和 Qdrant 服务器通话的"客户端"对象，所有请求都靠它发。   PointStruct：插入数据时的"一条记录"的格式
from qdrant_client.models import Distance, PointStruct, VectorParams # VectorParams 描述"表里的向量多长、怎么算相似"，Distance 是"算法选项"，比如 Distance.COSINE 表示用余弦相似度
#app_config：整个项目的配置总对象。它来自 app/conf/app_config.py，那个文件读了 conf/app_config.yaml，所以 app_config.qdrant 就是 yaml 里的：
from app.conf.app_config import QdrantConfig, app_config

class QdrantClientManager:
    def __init__(self, config: QdrantConfig):
        self.client: AsyncQdrantClient | None = None
        self.config: QdrantConfig = config

    def _get_url(self) -> str:
        return f"http://{self.config.host}:{self.config.port}"

    def init(self) -> None:
        self.client = AsyncQdrantClient(url=self._get_url())

    async def close(self) -> None:
        if self.client is not None:
            await self.client.close()
            self.client = None


qdrant_client_manager = QdrantClientManager(app_config.qdrant)


if __name__ == "__main__":
    # 测试用的向量维度，与下面 demo 数据保持一致
    # 正式建集合时应该用 app_config.qdrant.embedding_size（这里是 1024）

    qdrant_client_manager.init()
    client = qdrant_client_manager.client

    async def test():
        try:
            # 创建集合（脚本可以重复运行，先删掉上一次的测试集合）
            if await client.collection_exists("test_collection_async"):
                await client.delete_collection("test_collection_async")
            await client.create_collection(
                collection_name="test_collection_async",
                vectors_config=VectorParams(size=4, distance=Distance.COSINE),
            )

            await client.upsert(
                collection_name="test_collection_async",
                wait=True, #等写入落盘再返回
                points=[
                    PointStruct(id=1, vector=[0.05, 0.61, 0.76, 0.74], payload={"city": "Berlin"}),
                    PointStruct(id=2, vector=[0.05, 0.71, 0.42, 0.11], payload={"city": "London"}),
                    PointStruct(id=3, vector=[0.05, 0.41, 0.56, 0.79], payload={"city": "Moscow"}),
                    PointStruct(id=4, vector=[0.18, 0.01, 0.59, 0.69], payload={"city": "New York"}),
                ],
            )

            # 查询数据 先 await 出真东西，再点它的响应对象上取 .points
            search_result = (await client.query_points(
                collection_name="test_collection_async",
                # query=[0.1, 0.6, 0.70, 0.75],
                query=[0.05, 0.71, 0.42, 0.11],
                with_payload=False,
                limit=2,
            )).points

            print(search_result)
        finally:
            await qdrant_client_manager.close()

    asyncio.run(test()) #发动机点火