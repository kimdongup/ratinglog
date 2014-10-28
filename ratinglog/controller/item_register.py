# -*- coding: utf-8 -*-
'''
Created on 2014. 10. 15.

@author: kimdongup
'''

import os
from flask import request, redirect, url_for, current_app, render_template, \
                    session
from werkzeug.utils import secure_filename
from datetime import datetime
import uuid
from wtforms import Form, FileField, TextField, TextAreaField, validators

from ratinglog.database import dao
from ratinglog.model.rate import Rate
from ratinglog.controller.login import login_required
from ratinglog.logger import Log
from ratinglog.blueprint import ratinglog
from ratinglog.controller.item_show import get_rate_info

class rateUploadForm(Form):
    """사진 등록 화면에서 사진 파일, 태그, 설명 경도, 위도, 사진 찍은 날짜을 검증함"""
    
    uploadfile = FileField('uploadfile')
    
    priority = TextField('priority', 
                    [validators.Length(
                        min=1, 
                        max=1, 
                        message='1자리로 입력하세요.')])
    title = TextField('title', 
                            [validators.Length(
                                min=1, 
                                max=100, 
                                message='100자리 이하로 입력하세요.')])
    granted = TextField('granted', 
                    [validators.Length(
                        min=1, 
                        max=20, 
                        message='20자리로 입력하세요.')])
    category = TextField('category', 
                            [validators.Length(
                                min=1, 
                                max=20, 
                                message='20자리 이하로 입력하세요.')])
    definition = TextAreaField('definition', 
                    [validators.Length(
                        min=1, 
                        max=400, 
                        message='400자리로 입력하세요.')])
    comments = TextAreaField('comments', 
                            [validators.Length(
                                min=1, 
                                max=400, 
                                message='400자리 이하로 입력하세요.')])
    sql = TextAreaField('sql', 
                            [validators.Length(
                                min=1, 
                                max=400, 
                                message='400자리 이하로 입력하세요.')])


ALLOWED_EXTENSIONS = set(['zip'])

def __allowed_file(filename):
    return '.' in filename and \
            filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@ratinglog.route('/rate/upload')
@login_required
def upload_Rate_form():
    """ 파일을 업로드 하기 위해 업로드폼 화면으로 전환시켜주는 함수 """
    
    form = rateUploadForm(request.form)
    
    return render_template('upload.html', form=form)

@ratinglog.route('/rate/update/<Rate_id>')
@login_required
def update_Rate_form(Rate_id):
    """ 업로드폼에서 입력한 값들을 수정하기 위해 DB값을 읽어와 업로드폼 화면으로 전달한다. """
    
    r = dao.query(Rate).filter_by(id=Rate_id).first()
    form = rateUploadForm(request.form, r)
        
    return render_template('upload.html', Rate=r, form=form)


@ratinglog.route('/rate/upload', methods=['POST'])
@login_required
def upload_Rate():
    """ Form으로 파일과 변수들을 DB에 저장하는 함수. """

    form = rateUploadForm(request.form)
        
    # HTTP POST로 요청이 오면 사용자 정보를 등록
    if form.validate():  
        #: Session에 저장된 사용자 정보를 셋팅
        user_id = session['user_info'].id
        username = session['user_info'].username
        
        
        #: Form으로 넘어온 변수들의 값을 셋팅함
        priority = form.priority.data
        title = form.title.data
        granted = form.granted.data
        category = form.category.data
        definition = form.definition.data
        comments = form.comments.data
        sql = form.sql.data

        upload_date = datetime.today()
    
        #: 업로드되는 파일정보 값들을 셋팅한다.
        upload_Rate = request.files['uploadfile']
        filename = None
        filesize = 0
        filename_orig = upload_Rate.filename
        try:
            #: 파일 확장자 검사 : 현재 zip만 가능
            if upload_Rate and __allowed_file(upload_Rate.filename):
                
                ext = (upload_Rate.filename).rsplit('.', 1)[1]
    
                #: 업로드 폴더 위치는 얻는다.
                upload_folder = \
                    os.path.join(current_app.root_path, 
                                 current_app.config['UPLOAD_FOLDER'])
                #: 유일하고 안전한 파일명을 얻는다.   
                filename = \
                    secure_filename(username + 
                                    '_' + 
                                    unicode(uuid.uuid4()) +
                                    "." + 
                                    ext)
                
                upload_Rate.save(os.path.join(upload_folder, 
                                               filename))
                
                filesize = \
                    os.stat(upload_folder + filename).st_size
                
            else:
                raise Exception("File upload error : illegal file.")
    
        except Exception as e:
            Log.error(str(e))
            raise e
    
        try :
            #: 사진에 대한 정보 DB에 저장
            rate = Rate(user_id, 
                          priority, 
                          title, 
                          granted, 
                          category, 
                          definition, 
                          comments, 
                          sql, 
                          filename_orig, 
                          filename,
                          filesize,
                          upload_date)

            dao.add(rate)
            dao.commit()
    
        except Exception as e:
            dao.rollback()
            Log.error("Upload DB error : " + str(e))
            raise e
    
        return redirect(url_for('.show_all'))
    else:
        return render_template('upload.html', form=form)


@ratinglog.route('/rate/update/<Rate_id>', methods=['POST'])
@login_required
def update_Rate(Rate_id):
    """ 사진 업로드 화면에서 사용자가 수정한 내용을 DB에 업데이트 한다. """

    form = rateUploadForm(request.form)

    if form.validate(): 
        #: 업데이트 대상 항목들
        priority = form.priority.data
        title = form.title.data
        granted = form.granted.data
        category = form.category.data
        definition = form.definition.data
        comments = form.comments.data
        sql = form.sql.data
  
        user_id = session['user_info'].id
        username = session['user_info'].username
              
        upload_date = datetime.today()
    
        #: 업로드되는 파일정보 값들을 셋팅한다.
        update_Rate = request.files['uploadfile']
        filename = None
        filesize = 0
        filename_orig = update_Rate.filename
        
        try:
            #: 파일 확장자 검사 : 현재 zip만 가능
            if update_Rate and __allowed_file(update_Rate.filename):
                
                ext = (update_Rate.filename).rsplit('.', 1)[1]
    
                #: 업로드 폴더 위치는 얻는다.
                upload_folder = \
                    os.path.join(current_app.root_path, 
                                 current_app.config['UPLOAD_FOLDER'])
                #: 유일하고 안전한 파일명을 얻는다.   
                filename = \
                    secure_filename(username + 
                                    '_' + 
                                    unicode(uuid.uuid4()) +
                                    "." + 
                                    ext)
                
                update_Rate.save(os.path.join(upload_folder, 
                                               filename))
                
                filesize = \
                    os.stat(upload_folder + filename).st_size
                
                os.remove(get_rate_info(Rate_id)[0]+get_rate_info(Rate_id)[1])
                
            else:
                raise Exception("File update error : illegal file.")
    
        except Exception as e:
            Log.error(str(e))
            raise e
                         
        try :
        
            #: 변경전 원래의 rate 테이블 값을 읽어 온다.
            AA = dao.query(Rate).filter_by(id=Rate_id).first()
            #: 업데이트 값 셋팅
            AA.priority = priority
            AA.title = title
            AA.granted = granted
            AA.category = category
            AA.definition = definition
            AA.comments = comments
            AA.sql = sql
            AA.filename_orig= filename_orig
            AA.filename= filename
            AA.filesize=filesize
            AA.upload_date=upload_date
            dao.commit()
    
        except Exception as e:
            dao.rollback()
            Log.error("Update DB error : " + str(e))
            raise e
    
        return redirect(url_for('.show_all'))
    else:
        raise Exception("File update error : improper input.")

@ratinglog.route('/rate/remove/<Rate_id>')
@login_required
def remove(Rate_id):
    """ DB에서 해당 데이터를 삭제하고 관련된 파일을 함께 삭제한다."""

    user_id = session['user_info'].id
    
    try:
        AA = dao.query(Rate).filter_by(id=str(Rate_id)).first()
        
        dao.delete(AA)
        dao.commit()

        upload_folder = os.path.join(current_app.root_path, 
                                     current_app.config['UPLOAD_FOLDER'])
        os.remove(upload_folder + str(AA.filename))

    except Exception as e:
        dao.rollback()
        Log.error("Rate remove error => " + Rate_id + ":" + user_id + \
                  ", " + str(e))
        raise e
    
    return redirect(url_for('.show_all'))