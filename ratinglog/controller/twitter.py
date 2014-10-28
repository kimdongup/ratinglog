# -*- coding: utf-8 -*-
'''
Created on 2014. 10. 15.

@author: kimdongup
'''

from flask import request, redirect, url_for, current_app, session
from twython import Twython, TwythonError

from ratinglog.controller.login import login_required
from ratinglog.controller.item_show import get_rate_info
from ratinglog.blueprint import ratinglog
from ratinglog.logger import Log

from ratinglog.database import dao
from ratinglog.model.rate import Rate
from datetime import datetime

@ratinglog.route('/sns/twitter/send/<Rate_id>')
@login_required
def send(Rate_id):
    """ Rate_id에 해당하는 사진과 커멘트를 트위터로 전송하는 뷰함수 """
    """"""
    if (session.__contains__('TWITTER')):

        twitter = session['TWITTER']
        __send_twit(twitter, Rate_id)
            
        return redirect(url_for('.show_all'))

    else:
        # twitter 객체가 세션에 없을경우 인증단계로 이동한다.
        return __oauth(Rate_id)



def __send_twit(twitter, Rate_id):
    """ 실제로, Rate_id에 해당하는 사진과 커멘트를 트위터로 전송하는 내부 함수 """

    try:
        r = dao.query(Rate).filter_by(id=Rate_id).first()
        twitter.update_status(status=r.title+" at "+datetime.today().strftime("%Y-%m-%d %H:%M:%S"))
    
        session['TWITTER_RESULT'] = 'ok' 

    except IOError as e:
        Log.error("send(): IOError , " + str(e))
        session['TWITTER_RESULT'] = str(e)

    except TwythonError as e:
        Log.error("send(): TwythonError , " + str(e))
        session['TWITTER_RESULT'] = str(e)



def __oauth(Rate_id):
    """ twitter로부터 인증토큰을 받기 위한 함수 """
    
    try:
        twitter = Twython(current_app.config['TWIT_APP_KEY'], 
                          current_app.config['TWIT_APP_SECRET'])
        callback_svr = current_app.config['TWIT_CALLBACK_SERVER']
        
        auth    = twitter.get_authentication_tokens(
                          callback_url= callback_svr + \
                          url_for('.callback', Rate_id=Rate_id))

        # 중간단계로 받은 임시 인증토큰은 최종인증을 위해 필요하므로 세션에 저장한다. 
        session['OAUTH_TOKEN'] = auth['oauth_token']
        session['OAUTH_TOKEN_SECRET'] = auth['oauth_token_secret']

    except TwythonError as e:
        Log.error("__oauth(): TwythonError , "+ str(e))
        session['TWITTER_RESULT'] = str(e)

        return redirect(url_for('.show_all'))
    

    # 트위터의 사용자 권한 인증 URL로 페이지를 리다이렉트한다.
    return redirect(auth['auth_url'])




@ratinglog.route('/sns/twitter/callback/<Rate_id>')
@login_required
def callback(Rate_id):
    """ twitter로부터 callback url이 요청되었을때 
        최종인증을 한 후 트위터로 해당 사진과 커멘트를 전송한다.  
    """

    Log.info("callback oauth_token:" + request.args['oauth_token']);
    Log.info("callback oauth_verifier:" + request.args['oauth_verifier']);
    
    # oauth에서 twiter로 부터 넘겨받은 인증토큰을 세션으로 부터 가져온다.
    OAUTH_TOKEN        = session['OAUTH_TOKEN']
    OAUTH_TOKEN_SECRET = session['OAUTH_TOKEN_SECRET']
    oauth_verifier     = request.args['oauth_verifier']
    
    try:
        # 임시로 받은 인증토큰을 이용하여 twitter 객체를 만들고 인증토큰을 검증한다.     
        twitter = Twython(current_app.config['TWIT_APP_KEY'], 
                          current_app.config['TWIT_APP_SECRET'], 
                          OAUTH_TOKEN, OAUTH_TOKEN_SECRET)
        final_step = twitter.get_authorized_tokens(oauth_verifier)    
        
        # oauth_verifier를 통해 얻은 최종 인증토큰을 이용하여 twitter 객체를 새로 생성한다.
        twitter = Twython(current_app.config['TWIT_APP_KEY'], 
                          current_app.config['TWIT_APP_SECRET'], 
                          final_step['oauth_token'], 
                          final_step['oauth_token_secret'])
        session['TWITTER'] = twitter
    
        # 파라미터로 받은 Rate_id를 이용하여 해당 사진과 커멘트를 트위터로 전송한다.
        __send_twit(twitter, Rate_id)

    except TwythonError as e:
        Log.error("callback(): TwythonError , "+ str(e))
        session['TWITTER_RESULT'] = str(e)

    return redirect(url_for('.show_all'))

