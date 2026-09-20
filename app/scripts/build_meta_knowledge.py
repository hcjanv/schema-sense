import argparse
import asyncio

from pathlib import Path

from app.core.log import logger
from app.services import meta_knowledge_service
from app.services.meta_knowledge_service import MetaKnowledgeService


async def build(config_path: Path):
    meta_knowledge_service = MetaKnowledgeService()
    await  meta_knowledge_service.build(config_path)
    # print(config_path)
    logger.info("Building……")

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