import argparse  # 标准库：命令行参数解析 → 相当于 commander / yargs
import asyncio

from pathlib import Path # 标准库：路径对象 → 相当于 node 的 path / URL

from app.clients.embedding_client_manager import embedding_client_manager
from app.clients.es_client_manager import es_client_manager
from app.clients.mysql_client_manager import meta_mysql_client_manager, dw_mysql_client_manager
from app.clients.qdrant_client_manager import qdrant_client_manager
from app.core.log import logger
from app.repositories.es.value_es_repository import ValueEsRepository
from app.repositories.mysql.dw import dw_mysql_repository
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
from app.repositories.mysql.meta import meta_mysql_repository
from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
from app.repositories.qdrant import column_qdrant_repositories
from app.repositories.qdrant.column_qdrant_repositories import ColumnQdrantRepository
from app.services import meta_knowledge_service
from app.services.meta_knowledge_service import MetaKnowledgeService

#把 conf/meta_config.yaml 里手写的"业务元数据"（表、字段、指标的中文业务含义）构建成 AI 能检索的知识库
async def build(config_path: Path):
    meta_mysql_client_manager.init()
    dw_mysql_client_manager.init()
    qdrant_client_manager.init()
    embedding_client_manager.init()
    es_client_manager.init()


    async with meta_mysql_client_manager.session_factory() as meta_session, dw_mysql_client_manager.session_factory() as dw_session :
        meta_mysql_repository = MetaMySQLRepository(meta_session)
        dw_mysql_repository = DWMySQLRepository(dw_session)
        column_qdrant_repository = ColumnQdrantRepository(qdrant_client_manager.client)
        value_es_repository = ValueEsRepository(es_client_manager.client)

        meta_knowledge_service = MetaKnowledgeService(meta_mysql_repository=meta_mysql_repository,
                                                      dw_mysql_repository=dw_mysql_repository,
                                                      column_qdrant_repository=column_qdrant_repository,
                                                      embedding_client=embedding_client_manager.client,
                                                      value_es_repository=value_es_repository)
        await  meta_knowledge_service.build(config_path)
        
    await meta_mysql_client_manager.close()
    await dw_mysql_client_manager.close()
    await qdrant_client_manager.close()
    await embedding_client_manager.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        # prog="build_meta_knowledge.py",
        # description="Build Knowledge for Meta Knowledge",
        # epilog="Text at the bottom of help",
    )

    # parser.add_argument('filename')  # 位置参数
    parser.add_argument( '-c','--conf') #接受一个值的选项
    # parser.add_argument( "-v", "--verbose",action = 'store_true')  # 启用/禁用旗标
    args = parser.parse_args()
    config_path = args.conf
    # print(sys.argv[2])
    asyncio.run(build(Path(config_path)))