# -*- coding: utf-8 -*-
'''
Created on 2014. 10. 15.

@author: kimdongup
'''

class ratinglogConfig(object):
    #: 데이터베이스 연결 URL
    DB_URL= 'sqlite:///'
    #: 데이터베이스 파일 경로
    DB_FILE_PATH= 'resource/database/ratinglog'
    #: 파일 업로드 시 파일이 임시로 저장되는 임시 폴더
    TMP_FOLDER = 'resource/tmp/'
    #: 업로드 완료된  파일이 저장되는 폴더
    UPLOAD_FOLDER = 'resource/upload/'
    #: 업로드되는 파일의 최대 크키(3메가)
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024
    #: 세션 타임아웃은 초(second) 단위(60분)
    PERMANENT_SESSION_LIFETIME = 60 * 60
    #: 쿠기에 저장되는 세션 쿠키
    SESSION_COOKIE_NAME = 'ratinglog_session'
    #: 로그 레벨 설정
    LOG_LEVEL = 'debug'
    #: 디폴트 로그 파일 경로
    LOG_FILE_PATH = 'resource/log/ratinglog.log'
    #: 디폴트 SQLAlchemy trace log 설정
    DB_LOG_FLAG = 'True'
    #: 트위터에 등록된 ratinglog 어플리케이션 인증키 (https://dev.twitter.com/apps)
    TWIT_APP_KEY    = 'r7ArDMW110wfjzn5UCWRvwEwm'
    TWIT_APP_SECRET = 'OzszLKSD0C6lC2qwLnH7WhmuGIhm56b6vqbwuo2AKYLNTIfiqk'
    #: 트위터 연동에 대한 콜백 서버 URL(어플리케이션 루트 경로)
    TWIT_CALLBACK_SERVER = 'http://maramura.iptime.org:5000'
    #: 사진 목록 페이징 설정
    PER_PAGE = 10