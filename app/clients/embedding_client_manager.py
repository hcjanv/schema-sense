import asyncio

from huggingface_hub import AsyncInferenceClient, InferenceClient
from langchain_huggingface import HuggingFaceEndpointEmbeddings

from app.conf.app_config import EmbeddingConfig, app_config


class EmbeddingClientManager:
    def __init__(self, config: EmbeddingConfig):
        self.config = config
        self.client: HuggingFaceEndpointEmbeddings | None = None

    def _get_url(self):
        return f"http://{self.config.host}:{self.config.port}"

    def init(self):
        # 新版 langchain-huggingface 要求 model 是 HF 仓库名，本地 TEI 地址只能通过 base_url 挂到 client 上
        self.client = HuggingFaceEndpointEmbeddings(model=self.config.model)
        self.client.client = InferenceClient(base_url=self._get_url())
        self.client.async_client = AsyncInferenceClient(base_url=self._get_url())

    async def close(self):
        if self.client:
            self.client.client.close()
            await self.client.async_client.close()

embedding_client_manager = EmbeddingClientManager(app_config.embedding)

if __name__ == "__main__":
    embedding_client_manager.init()
    client = embedding_client_manager.client

    async  def test():
        text = "what is deep learning"
        query_result = await client.aembed_query(text)
        print(query_result[:3])

    asyncio.run(test())