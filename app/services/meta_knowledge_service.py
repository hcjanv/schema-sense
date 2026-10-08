import uuid
from dataclasses import asdict
from pathlib import Path

from langchain_huggingface import HuggingFaceEndpointEmbeddings
from omegaconf import OmegaConf
from app.conf.meta_config import MetaConfig
from app.entities.column_info import ColumnInfo
from app.entities.table_info import TableInfo
from app.entities.value_info import ValueInfo
from app.repositories.es.value_es_repository import ValueEsRepository
from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
from app.repositories.qdrant.column_qdrant_repositories import ColumnQdrantRepository

class MetaKnowledgeService:
    def __init__(self,
                 meta_mysql_repository: MetaMySQLRepository,
                 dw_mysql_repository: DWMySQLRepository,
                 column_qdrant_repository: ColumnQdrantRepository,
                 embedding_client:HuggingFaceEndpointEmbeddings,
                 value_es_repository: ValueEsRepository):
        self.meta_mysql_repository: MetaMySQLRepository = meta_mysql_repository
        self.dw_mysql_repository: DWMySQLRepository = dw_mysql_repository
        self.column_qdrant_repository: ColumnQdrantRepository = column_qdrant_repository
        self.embedding_client:HuggingFaceEndpointEmbeddings = embedding_client
        self.value_es_repository: ValueEsRepository = value_es_repository

    async def _sava_tables_to_meta_db(self,meta_config: MetaConfig)->list[ColumnInfo]:
        table_infos: list[TableInfo] = []
        column_infos: list[ColumnInfo] = []

        for table in meta_config.tables:
            # table -> table_info
            table_info = TableInfo(id=table.name,
                                   name=table.name,
                                   role=table.role,
                                   description=table.description)
            table_infos.append(table_info)

            # 查询字段类型
            column_types = await self.dw_mysql_repository.get_column_types(table.name)

            for column in table.columns:
                # 查询字段取值示例
                column_values = await self.dw_mysql_repository.get_column_values(table.name, column.name)

                # column -> column_info
                column_info = ColumnInfo(id=f"{table.name}.{column.name}",
                                         name=column.name,
                                         type=column_types[column.name],
                                         role=column.role,
                                         examples=column_values,
                                         description=column.description,
                                         alias=column.alias,
                                         table_id=table.name)
                column_infos.append(column_info)
        # print(table_infos)
        # print("="*100)
        # print(column_infos)

        async  with self.meta_mysql_repository.session.begin():
            await self.meta_mysql_repository.save_table_infos(table_infos)
            await self.meta_mysql_repository.save_column_infos(column_infos)

        return column_infos


    async def _save_columns_to_qdrant(self, column_infos: list[ColumnInfo]):
        await self.column_qdrant_repository.ensure_collection()

        points: list[dict] = []
        for column_info in column_infos:
            points.append({
                "id": uuid.uuid4(),
                "embedding_text": column_info.name,
                "payload": asdict(column_info)
            })

            points.append({
                "id": uuid.uuid4(),
                "embedding_text": column_info.description,
                "payload": asdict(column_info)
            })

            for alia in column_info.alias:
                points.append({
                    "id": uuid.uuid4(),
                    "embedding_text": alia,
                    "payload": asdict(column_info)
                })

        # 向量化
        embeddings: list[list[float]] = []
        embedding_texts = [point["embedding_text"] for point in points]
        embedding_batch_size = 20
        for i in range(0, len(embedding_texts), embedding_batch_size):  # 0 20 40 60
            batch_embedding_text = embedding_texts[i:i + embedding_batch_size]  # 0-19 20-39
            batch_embeddings = await self.embedding_client.aembed_documents(batch_embedding_text)
            embeddings.extend(batch_embeddings)

        ids = [point["id"] for point in points]

        payloads = [point["payload"] for point in points]
        await self.column_qdrant_repository.upsert(ids, embeddings, payloads)


    async def _save_values_to_es(self, meta_config: MetaConfig):
        await self.value_es_repository.ensure_index()

        values_infos: list[ValueInfo] = []
        for table in meta_config.tables:
            for column in table.columns:
                if column.sync:
                    # 查询字段取值
                    current_column_values = await self.dw_mysql_repository.get_column_values(table.name, column.name,
                                                                                             100000)

                    current_values_infos = [ValueInfo(id=f"{table.name}.{column.name}.{current_column_value}",
                                                      value=current_column_value,
                                                      column_id=f"{table.name}.{column.name}")
                                            for current_column_value in current_column_values]

                    values_infos.extend(current_values_infos)

        await self.value_es_repository.index(values_infos)

    async def build(self, config_path: Path) -> MetaConfig:
        # 1.读取配置文件
        context = OmegaConf.load(config_path) #读 yaml 成 DictConfig（一个支持点号访问的字典，能 cfg.a.b）
        schema = OmegaConf.structured(MetaConfig) #把 dataclass 变成"结构定义/schema"，提供默认值 and 类型约束
        # OmegaConf.merge(schema, context)	schema 打底，用户 yaml 覆盖；类型不对或字段名写错会直接报错
        # OmegaConf.to_object(...)	把 DictConfig 转成真正的 Python 对象（MetaConfig 实例，内部嵌套 TableConfig/ColumnConfig/MetricConfig）
        meta_config: MetaConfig = OmegaConf.to_object(OmegaConf.merge(schema, context))

        print(meta_config.metrics)

        # 2.根据配置文件同步指定的表信息和指标信息
        if meta_config.tables:
            # 2.1 将表信息和字段信息保存meta数据库中
            column_infos = await self._sava_tables_to_meta_db(meta_config)

            # 2.2 对字段信息建立向量索引
            await self._save_columns_to_qdrant(column_infos)

            # 2.3 对指定的维度字段取值建立全文索引
            await self._save_values_to_es(meta_config)

        # 根据配置文件同步指定的指标信息
        if meta_config.metrics:
            # 3.1 将指标信息保存meta数据库中
            # 3.2 对指标信息建立向量索引
            pass

        return meta_config
