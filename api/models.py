from sqlalchemy import Column, Integer, Boolean, UniqueConstraint
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Follower(Base):
    __tablename__ = 'followers'
    id = Column(Integer, primary_key=True, autoincrement=True)
    follower_id = Column(Integer, primary_key=False, nullable=False)
    followed_id = Column(Integer, primary_key=False, nullable=False)
    tenant_id = Column(Integer, primary_key=False, nullable=False)
    deleted = Column(Boolean, default=False, nullable=False)

    __table_args__ = (
        UniqueConstraint('tenant_id', 'follower_id', 'followed_id', name='uix_tenant_follower_followed'),
    )

    def as_tuple(self):
        return (self.tenant_id, self.follower_id, self.followed_id, self.deleted)
