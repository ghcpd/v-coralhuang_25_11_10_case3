from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import UniqueConstraint

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False)


class Follower(db.Model):
    __tablename__ = 'followers'
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    follower_id = db.Column(db.Integer, nullable=False)
    followed_id = db.Column(db.Integer, nullable=False)
    deleted = db.Column(db.Boolean, default=False, nullable=False)

    __table_args__ = (
        UniqueConstraint('tenant_id', 'follower_id', 'followed_id', name='uq_tenant_follower_followed'),
    )


def init_db():
    # Create tables
    db.create_all()
