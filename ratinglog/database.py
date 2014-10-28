# -*- coding: utf-8 -*-
'''
Created on 2014. 10. 15.

@author: kimdongup
'''

from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker


class DBManager:
    """데이터베이스 처리를 담당하는 공통 클래스"""
    
    __engine = None
    __session = None

    @staticmethod
    def init(db_url, db_log_flag=True):
        DBManager.__engine = create_engine(db_url, echo=db_log_flag) 
        DBManager.__session = \
            scoped_session(sessionmaker(autocommit=False, 
                                        autoflush=False, 
                                        bind=DBManager.__engine))

        global dao
        dao = DBManager.__session
    
    @staticmethod
    def init_db():
        from ratinglog.model import *
        from ratinglog.model import Base
        Base.metadata.create_all(bind=DBManager.__engine)

dao = None        
