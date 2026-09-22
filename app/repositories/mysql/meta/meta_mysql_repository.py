from sqlalchemy.ext.asyncio import AsyncSession


class MetaMySQLRepository:
    def __init__(self, Session: AsyncSession):
        self.session = Session

