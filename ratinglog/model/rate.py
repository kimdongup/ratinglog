# -*- coding: utf-8 -*-
'''
Created on 2014. 10. 15.

@author: kimdongup
'''

from sqlalchemy import Column, Integer, String, ForeignKey, DateTime

from ratinglog.model.user import User

from ratinglog.model import Base

class Rate(Base):
    __tablename__ = 'rates'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey(User.id))
    priority = Column(String(1), unique=False)
    title = Column(String(100), unique=False)
    granted = Column(String(20), unique=False)
    category = Column(String(20), unique=False)
    definition = Column(String(400), unique=False)
    comments = Column(String(400), unique=False)
    sql = Column(String(400), unique=False)
    filename_orig = Column(String(400), unique=False)
    filename = Column(String(400), unique=False)
    filesize = Column(Integer, unique=False)
    upload_date = Column(DateTime, unique=False)
    

    def __init__(self, user_id, priority, title, granted, category, definition, comments, sql, filename_orig, filename, filesize, upload_date):
        """Rate 모델 클래스를 초기화 한다."""
        
        self.user_id = user_id
        self.priority = priority
        self.title = title
        self.granted = granted
        self.category = category
        self.definition = definition
        self.comments = comments
        self.sql = sql
        self.filename_orig = filename_orig
        self.filename = filename
        self.filesize = filesize
        self.upload_date = upload_date


    def __repr__(self):
        """모델의 주요 정보를 출력한다."""        
        
        return '<Rate %r %r>' % (self.user_id, self.upload_date)