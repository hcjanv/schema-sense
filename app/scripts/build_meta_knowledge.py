import argparse  # 标准库：命令行参数解析 → 相当于 commander / yargs
import asyncio

from pathlib import Path # 标准库：路径对象 → 相当于 node 的 path / URL

from app.clients.mysql_client_manager import meta_mysql_client_manager
from app.core.log import logger
from app.repositories.mysql.meta import meta_mysql_repository
from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
from app.services import meta_knowledge_service
from app.services.meta_knowledge_service import MetaKnowledgeService

#把 conf/meta_config.yaml 里手写的"业务元数据"（表、字段、指标的中文业务含义）构建成 AI 能检索的知识库
async def build(config_path: Path):
    meta_mysql_client_manager.init()
    async with meta_mysql_client_manager.session_factory() as session:
        meta_mysql_repository = MetaMySQLRepository(session)
        meta_knowledge_service = MetaKnowledgeService(meta_mysql_repository)
        await  meta_knowledge_service.build(config_path)
        
    await meta_mysql_client_manager.close()

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