from pathlib import Path
from omegaconf import OmegaConf
from app.conf.meta_config import MetaConfig
from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository

class MetaKnowledgeService:
    def __init__(self, meta_mysql_repository: MetaMySQLRepository):
        self.meta_mysql_repository: MetaMySQLRepository = meta_mysql_repository

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
            for table in meta_config.tables:
                # table -> table_info
                for column in table.columns:
                    # column -> column_info
                    pass

            # 2.2 对字段信息建立向量索引

            # 2.3 对指定的维度字段取值建立全文索引
            pass

        # 根据配置文件同步指定的指标信息
        if meta_config.metrics:
            # 3.1 将指标信息保存meta数据库中
            # 3.2 对指标信息建立向量索引
            pass

        return meta_config
