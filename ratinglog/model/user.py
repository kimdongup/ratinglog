# -*- coding: utf-8 -*-
'''
Created on 2014. 10. 15.

@author: kimdongup
'''

from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship

from ratinglog.model import Base


class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True)
    email = Column(String(50), unique=False)
    password = Column(String(55), unique=False)

    rates = relationship('Rate', 
                          backref='user', 
                          cascade='all, delete, delete-orphan')
    
    def __init__(self, name, email, password):
        self.username = name
        self.email = email
        self.password = password

    def __repr__(self):
        return '<User %r %r>' % (self.username, self.email)
    
    
