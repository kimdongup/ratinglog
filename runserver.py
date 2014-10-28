'''
Created on 2014. 10. 15.

@author: kimdongup
'''

import sys

from ratinglog import create_app

reload(sys)
sys.setdefaultencoding('utf-8')

application = create_app()    

if __name__ == '__main__':
    print "starting ......"

    application.run(host='0.0.0.0', port=5000, debug=True)