from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.column_info import ColumnInfo
from app.entities.table_info import TableInfo
from app.repositories.mysql.meta.mappers.column_info_mapper import ColumnInfoMapper
from app.repositories.mysql.meta.mappers.table_info_mapper import TableInfoMapper


class MetaMySQLRepository:
    def __init__(self, Session: AsyncSession):
        self.session = Session

    async def save_table_infos(self, table_infos: list[TableInfo]):
        # merge: 主键已存在则更新,不存在则插入,脚本可重复执行
        for table_info in table_infos:
            await self.session.merge(TableInfoMapper.to_model(table_info))

    async def save_column_infos(self, column_infos: list[ColumnInfo]):
        for column_info in column_infos:
            await self.session.merge(ColumnInfoMapper.to_model(column_info))

