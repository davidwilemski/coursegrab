
import redis
import requests
import csv
import StringIO
import re
import hashlib
import gevent
import geventutil

# make gevent awesome
from gevent import monkey
monkey.patch_all()

COURSE_STRING = '{}{}_{}' # dept, catalog, section
COURSES_BASEURL = 'http://www.ro.umich.edu/timesched/pdf/'

redis_depts = 'coursegrab_departments_{}' # term
redis_classes = 'coursegrab_{}_classes_{}' # dept, term
redis_sections = 'coursegrab_{}{}_classes_sections_{}' # dept, catalog, term
redis_all_classes = 'coursegrab_all_classes_{}' # term
redis_open_classes = 'coursegrab_open_classes_{}' # term
redis_closed_classes = 'coursegrab_closed_classes_{}' # term

dept_regex = re.compile(r'\(([A-Z]*)\)')

r = redis.StrictRedis(host='localhost', port=6379, db=0)

def update_courses():
    term = r.get('coursegrab_current_term')

    if term is None:
        # should log, maybe notify
        print 'no current term configured, cannot run'
        return

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

            pipe.sadd(all_classes_key, COURSE_STRING.format(dept, catalog, section))
        pipe.execute() # run transaction!

    else:
        print 'no need to update all classes!'

    # only run update if hash is different for open classes
    open_hash_key = '{}_open_hash'.format(term)
    oldhash = r.get(open_hash_key)
    newhash = hashlib.sha1(opencourses_request.text).hexdigest()

    if newhash != oldhash:
        # we want updating the open/closed class sets to be atomic
        pipe = r.pipeline()
        pipe.set(open_hash_key, newhash)
        pipe.delete(open_classes_key)
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
        print 'no need to update open classes!'

    num_closed_classes = r.scard(closed_classes_key)
    print 'there are', num_closed_classes, 'closed classes'


if __name__ == '__main__':
    halfhour = 60 * 30 # 30 minutes in seconds
    geventutil.schedule(halfhour, update_courses)
