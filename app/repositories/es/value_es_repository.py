from elasticsearch import AsyncElasticsearch


class ValueEsRepository:

    index_name = "value_index"
    index_mappings = {
        "dynamic": False,
        "properties": {
          "id": {"type": "keyword"},
          "value": {"type": "text", "analyzer": "ik_max_word", "search_analyzer": "ik_max_word"},
          "column_id": {"type": "keyword"}
       }
    }

    def __init__(self, client: AsyncElasticsearch):
        self.client = client

    async def ensure_index(self):
        if not await self.client.indices.exists(index=self.index_name):
            await self.client.indices.create(
                index=self.index_name,
                mappings=self.index_mappings
            )
