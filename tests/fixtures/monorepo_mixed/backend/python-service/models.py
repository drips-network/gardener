"""
Data models for the Python service
"""

from sqlalchemy import Column, Integer, String
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    name = Column(String(100))
    email = Column(String(100))


class DataModel:
    def __init__(self, id, value):
        self.id = id
        self.value = value
