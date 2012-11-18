
import redis
import requests
import csv
import StringIO
import re
import hashlib
import gevent
from gevent.wsgi import WSGIServer
from twilio.rest import TwilioRestClient
from tornado import web, wsgi
import os
import json
import logging

# local imports
import geventutil

# make gevent awesome
from gevent import monkey
monkey.patch_all()

COURSE_STRING = '{}_{}_{}' # dept, catalog, section
COURSES_BASEURL = 'http://www.ro.umich.edu/timesched/pdf/'

redis_depts = 'coursegrab_departments_{}' # term
redis_classes = 'coursegrab_{}_classes_{}' # dept, term
redis_sections = 'coursegrab_{}{}_classes_sections_{}' # dept, catalog, term
redis_all_classes = 'coursegrab_all_classes_{}' # term
redis_open_classes = 'coursegrab_open_classes_{}' # term
redis_closed_classes = 'coursegrab_closed_classes_{}' # term
redis_number_to_coursestring = 'coursegrab_{}_{}' # coursenum, term
redis_notify_set = 'coursegrab_{}_{}' # course string, term
redis_term_phones = 'coursegrab_phones_{}' # term
redis_all_phones= 'coursegrab_phones' # course string, term
redis_phone_to_courses = 'coursegrab_{}_courses_{}' # phone, term
twilio_key = 'coursegrab_twilio_send_worker'

dept_regex = re.compile(r'\(([A-Z]*)\)')

r = redis.StrictRedis(host='localhost', port=6379, db=0)
log = logging.getLogger(__file__)

def twilio_worker():
    # loads settings from the env
    # variables: TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN
    # also uses TWILIO_SOURCE_NUMBER to configure the from phone number
    client = TwilioRestClient()
    source_num = os.environ['TWILIO_SOURCE_NUMBER']

    while True:
        data = r.brpop(twilio_key)[1]
        data = json.loads(data)

        # TODO validate that this is a phone number, should be okay 
        # for now because the only way a phone number gets here
        # is via a real text message
        phonenum = data['phonenum']
        msg = data['message']

        log.info("sending notification sms")

        message = client.sms.messages.create(
                to=phonenum,
                _from=source_num,
                body=msg)


def update_courses():
    """
    Updates our information about courses currently offered and which have 
    seats available. All of these updates are done within redis transactions
    so as to ensure that data is not in an inconsistent state for other
    clients that may be connected

    Also notifies any users that were queued up to be notified of a change
    in a course's availability.

    This is done by keeping a set in memory of the previous closed classes
    and getting the difference betweent that and the new set of closed classes.
    Any that was in the oldset but not in newset are now available and should
    have users in the corresponding class queue notified.
    """
    term = r.get('coursegrab_current_term')

    if term is None:
        # should log, maybe notify
        log.error('no current term configured, cannot run')
        return

    log.info("updating course information")

    depts_key = redis_depts.format(term)
    all_classes_key = redis_all_classes.format(term)
    open_classes_key = redis_open_classes.format(term)
    closed_classes_key = redis_closed_classes.format(term)

    courses_url = '{}{}.csv'.format(COURSES_BASEURL, term)
    opencourses_url = '{}{}_open.csv'.format(COURSES_BASEURL, term)

    courses_request = requests.get(courses_url)
    opencourses_request = requests.get(opencourses_url)

    courses_file = StringIO.StringIO(courses_request.text)
    opencourses_file = StringIO.StringIO(opencourses_request.text)

    courses_csv = csv.reader(courses_file, delimiter=',')
    opencourses_csv = csv.reader(opencourses_file)

    courses_fieldnames = courses_csv.next()
    opencourses_fieldnames = opencourses_csv.next()

    # check if the file hash is different for all classes
    all_hash_key = '{}_all_hash'.format(term)
    oldhash = r.get(all_hash_key)
    newhash = hashlib.sha1(courses_request.text).hexdigest()

    if newhash != oldhash:
        # transactionalize this too!
        pipe = r.pipeline()
        pipe.set(all_hash_key, newhash)
        pipe.delete(all_classes_key)
        for c in courses_csv:
            dept = dept_regex.search(c[4]).group(0).strip('()').strip()
            catalog = c[5].strip()
            section = c[6].strip()
            course_number = c[3].strip()

            classes_key = redis_classes.format(dept, term)
            sections_key = redis_sections.format(dept, catalog, term)

            pipe.sadd(depts_key, dept)
            pipe.sadd(classes_key, catalog)
            pipe.sadd(sections_key, section)

            course_string = COURSE_STRING.format(dept, catalog, section)
            course_key = redis_number_to_coursestring.format(course_number, term)

            pipe.sadd(all_classes_key, course_string)
            pipe.set(course_key, course_string)
        pipe.execute() # run transaction!

    else:
        log.info('no need to update all classes!')

    # only run update if hash is different for open classes
    open_hash_key = '{}_open_hash'.format(term)
    oldhash = r.get(open_hash_key)
    newhash = hashlib.sha1(opencourses_request.text).hexdigest()

    classes_updated = False
    if newhash != oldhash:
        # store a set of closed classes
        old_closed = r.smembers(closed_classes_key) 
        classes_updated = True

        # we want updating the open/closed class sets to be atomic
        pipe = r.pipeline()
        pipe.set(open_hash_key, newhash)
        pipe.delete(open_classes_key)
        pipe.delete(closed_classes_key)
        for c in opencourses_csv:
            dept = dept_regex.search(c[4]).group(0).strip('()').strip()
            catalog = c[5].strip()
            section = c[6].strip()
            open_seats = c[-3].strip()
            max_seats = c[-4].strip()

            classes_key = redis_classes.format(dept, term)
            sections_key = redis_sections.format(dept, catalog, term)


            pipe.sadd(open_classes_key, COURSE_STRING.format(dept, catalog, section))

        # include computing closed_classes set in the transaction
        pipe.sdiffstore(closed_classes_key, all_classes_key, open_classes_key)
        pipe.execute() # run the transaction
    else:
        log.info('no need to update open classes!')

    if not classes_updated:
        return # no need to recompute closed classes or try to notify people

    num_closed_classes = r.scard(closed_classes_key)
    log.info('there are ' + num_closed_classes + ' closed classes')

    new_closed = r.smembers(closed_classes_key)
    now_available = old_closed - new_closed

    # get users in each user notification queue
    for c in now_available:
        # users_to_notify is a set of phone numbers
        users_to_notify = r.smembers(redis_notify_set.format(c, term))

        courseinfo = c.split('_')
        msg = "{} {} section {} is now available! Hurry up before someone takes your spot!".format(courseinfo[0], courseinfo[1], courseinfo[2])
        for phonenum in users_to_notify:
            # construct a text message for each user and SEND SEND SEND
            r.lpush(twilio_key,
                    json.dumps({'phonenum': phonenum, 'message': msg}))


class SMSHandler(web.RequestHandler):
    def twiml_sms(self, message):
        # TODO: break messages up if >160 characters
        message = "<?xml version=\"1.0\" encoding=\"UTF-8\" ?><Response><Sms>" + message + "</Sms></Response>"
        self.write(message)

    def _handle_sms(self, phone, words):
        term = r.get('coursegrab_current_term')

        if words[0].lower() in {"sub", "subscribe", "notify"}:
            if len(words) < 2:
                msg = "Command not recognized. Please send: \"subscribe &lt;classnumber&gt;\" or \"unsubscribe &lt;classnumber&gt;\" or 'list' to list subscriptions"
                return self.twiml_sms(msg)

            key = redis_number_to_coursestring.format(words[1], term) 
            course = r.get(key)

            # check that the course exists and is closed
            if course and r.sismember(redis_closed_classes.format(term), course):
                r.sadd(redis_notify_set.format(course, term), phone)
                r.sadd(redis_phone_to_courses.format(phone, term), course)
                parts = course.split("_")
                msg = "You are now subscribed to {} {} section {}!".format(parts[0], parts[1], parts[2])
                self.twiml_sms(msg)
            
            elif course:
                self.twiml_sms("The class you requested is not closed.")

            else:
                self.twiml_sms("The class you requested doesn't exist")

        elif words[0].lower() in {"unsub", "unsubscribe", "remove"}:
            if len(words) < 2:
                msg = "Command not recognized. Please send: \"subscribe &lt;classnumber&gt;\" or \"unsubscribe &lt;classnumber&gt;\" or 'list' to list subscriptions"
                return self.twiml_sms(msg)
            key = redis_number_to_coursestring.format(words[1], term) 
            course = r.get(key)

            if course:
                r.srem(redis_notify_set.format(course, term), phone)
                r.srem(redis_phone_to_courses.format(phone, term), course)
                parts = course.split("_")
                msg = "You are unsubscribed from {} {} section {}!".format(parts[0], parts[1], parts[2])
                self.twiml_sms(msg)

            else:
                self.twiml_sms("The class you requested doesn't exist")

        elif words[0].lower() in {'list', 'subs', 'subscriptions'}:
            courses = r.smembers(redis_phone_to_courses.format(phone, term))
            message = ['You are subscribed to:']
            for course in courses:
                course = course.split('_')
                message.append('{} {} section {}'.format(course[0], course[1], course[2]))
            if len(message) > 1:
                message = '\n'.join(message)
            else:
                message = "You are not subscribed to any classes. To get started send 'subscribe &lt;5 digit course number&gt;'."
            self.twiml_sms(message) 

        elif words[0].lower() in {'help', 'info', 'information', 'man'}:
            message = "Coursegrab is made to notify University of Michigan students of course openings. To get started send 'subscribe &lt;5 digit course number&gt;'."
            self.twiml_sms(message)

        else:
            msg = "Command not recognized. Please send: \"subscribe &lt;classnumber&gt;\" or \"unsubscribe &lt;classnumber&gt;\" or 'list' to list subscriptions"
            self.twiml_sms(msg)

    def post(self):
        msg = self.get_argument('Body', '')
        phone = self.get_argument('From', '')
        msg = msg.lower()
        words = msg.split()
        
        term = r.get('coursegrab_current_term')
        r.sadd(redis_all_phones, phone)
        r.sadd(redis_term_phones.format(term), phone)

        self._handle_sms(phone, words)


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.DEBUG, 
        format="%(asctime)s - %(levelname)s - %(name)s - %(msg)s")

    halfhour = 60 * 30 # 30 minutes in seconds
    geventutil.schedule(halfhour, update_courses)

    w = gevent.spawn(twilio_worker)

    application = wsgi.WSGIApplication([
        (r"/twilio_receive", SMSHandler),
    ])

    # create the WSGI server and use serve_forever to allow the whole
    # application to loop forever - including the course updater, twilio worker
    WSGIServer(('', 10001), application).serve_forever()
