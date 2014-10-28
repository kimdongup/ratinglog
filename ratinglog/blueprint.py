# -*- coding: utf-8 -*-
'''
Created on 2014. 10. 15.

@author: kimdongup
'''

from flask import Blueprint
from ratinglog.logger import Log

ratinglog = Blueprint('ratinglog', __name__,
                     template_folder='../templates', static_folder='../static')

Log.info('static folder : %s' % ratinglog.static_folder)
Log.info('template folder : %s' % ratinglog.template_folder)
