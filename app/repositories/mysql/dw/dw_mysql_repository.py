from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

class DWMySQLRepository:
    def __init__(self,session: AsyncSession):
        self.session = session

    async def get_column_types(self, table_name)->dict[str,str]:
        sql = f"show columns from {table_name}"
        result = await self.session.execute(text(sql))
        result_dict = result.mappings().fetchall()
        # [{Field:order_id,Tyge:varchar(30),Null:No},{Field:customer_id,Tyge:varchar(20),Null:Yes}]
        return {row['Field']: row['Type'] for row in result_dict}  # compd
        # {order_id:varchar(30),customer_id:varchar(30)}


    async def get_column_values(self, table_name, column_name, limit=10):
        sql = sql = f"select distinct {column_name} from {table_name} limit {limit}"
        result = await self.session.execute(text(sql))
        return [row[0] for row in result.fetchall()]  # compl