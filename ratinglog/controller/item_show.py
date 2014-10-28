# -*- coding: utf-8 -*-
'''
Created on 2014. 10. 15.

@author: kimdongup
'''

import os
from flask import request, current_app, send_from_directory \
				, render_template, session, url_for
from sqlalchemy import or_

from ratinglog.database import dao
from ratinglog.model.rate import Rate
from ratinglog.controller.login import login_required
from ratinglog.blueprint import ratinglog
from ratinglog.logger import Log


def get_rate_info(Rate_id):
    """업로드된 파일 관련 정보를 얻는다.
       내부 함수인 __get_download_info()와 트위터 연동에 사용된다.
    """
    
    rate = dao.query(Rate).filter_by(id=Rate_id).first()
    download_folder = \
        os.path.join(current_app.root_path, 
                     current_app.config['UPLOAD_FOLDER'])
    download_filepath = os.path.join(download_folder, 
                                     rate.filename)
    
    return (download_folder, rate.filename, 
            download_filepath, rate.title)

def __get_download_info(Rate_id, prefix_filename=''):
    rate_info = get_rate_info(Rate_id)
    
    download_folder = rate_info[0]
    original_filename = rate_info[1]
    download_filename = prefix_filename + original_filename

    return send_from_directory(download_folder, 
                               download_filename, 
                               as_attachment=True, 
                               mimetype='application/zip')
    

@ratinglog.route('/rate/download/<Rate_id>')
@login_required
def download_Rate(Rate_id):
    return __get_download_info(Rate_id)


@ratinglog.route('/rate/', defaults={'page': 1})
@ratinglog.route('/rate/page/<int:page>')
@login_required
def show_all(page=1):    
    
    user_id = session['user_info'].id
    per_page = current_app.config['PER_PAGE']
    
    rate_count = dao.query(Rate).count()
    pagination = Pagination(page, per_page, rate_count)
    
    if page != 1:
        offset = per_page * (page - 1)
    else:
        offset = 0
    
    Rate_pages = dao.query(Rate). \
                        filter_by(user_id=user_id). \
                        order_by(Rate.upload_date.desc()). \
                        limit(per_page). \
                        offset(offset). \
                        all()
    
    return render_template('list.html',
        pagination=pagination,
        rates=Rate_pages) 


@ratinglog.route('/rate/search', methods=['POST'])
@login_required
def search_Rate():    
    search_word = request.form['search_word'];
    
    if (search_word == ''):
        return show_all();
    
    user_id = session['user_info'].id
    
    Rates=dao.query(Rate).filter_by(user_id=user_id). \
               filter(or_(Rate.category.like("%" + search_word + "%"), 
                          Rate.title.like("%" + search_word + "%"))). \
               order_by(Rate.upload_date.desc()).all()    
       
    return render_template('list.html', rates=Rates)


""" 출처 : http://flask.pocoo.org/snippets/44/ """

from math import ceil


class Pagination(object):
    
    def __init__(self, page, per_page, total_count):
        self.page = page
        self.per_page = per_page
        self.total_count = total_count

    @property
    def pages(self):
        return int(ceil(self.total_count / float(self.per_page)))

    @property
    def has_prev(self):
        return self.page > 1

    @property
    def has_next(self):
        return self.page < self.pages

    def iter_pages(self, left_edge=2, left_current=2,
                   right_current=5, right_edge=2):
        last = 0
        for num in xrange(1, self.pages + 1):
            if num <= left_edge or \
               (num > self.page - left_current - 1 and \
                num < self.page + right_current) or \
               num > self.pages - right_edge:
                if last + 1 != num:
                    yield None
                yield num
                last = num
                
                
