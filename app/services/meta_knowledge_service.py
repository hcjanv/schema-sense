from pathlib import Path
from omegaconf import OmegaConf

from app.conf.meta_config import MetaConfig


class MetaKnowledgeService:
    def __init__(self):
        pass

    async def build(self, config_path: Path) -> MetaConfig:
        # 1.读取配置文件
        context = OmegaConf.load(config_path)
        schema = OmegaConf.structured(MetaConfig)
        meta_config: MetaConfig = OmegaConf.to_object(OmegaConf.merge(schema, context))

        print(meta_config.metrics)

        # 2.根据配置文件同步指定的表信息和指标信息
        if meta_config.tables:
            # 配置文件中有表信息
            # 同步表信息
            pass

        if meta_config.metrics:
            # 配置文件中有指标信息
            # 同步指标信息
            pass

        return meta_config
