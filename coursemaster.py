
import redis
import requests
import csv
import StringIO
import re

COURSE_STRING = '{}{}_{}'
COURSES_BASEURL = 'http://www.ro.umich.edu/timesched/pdf/'

dept_regex = re.compile(r'\(([A-Z]*)\)')

r = redis.StrictRedis(host='localhost', port=6379, db=0)

def update_courses(term):
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

    #closed_classes = set()
    open_classes = set()
    all_classes = set()

    for c in courses_csv:
        dept = dept_regex.search(c[4]).group(0).strip('()').strip()
        catalog = c[5].strip()
        section = c[6].strip()
        # course_number = c[3]
        #r.sadd('coursegrab_departments', dept)
        #r.sadd('coursegrab_{}_classes'.format(dept), catalog)
        #r.sadd('coursegrab_{}_classes_sections'.format(dept), section)

        all_classes.add(COURSE_STRING.format(dept, catalog, section))

        

    for c in opencourses_csv:
        dept = dept_regex.search(c[4]).group(0).strip('()').strip()
        catalog = c[5].strip()
        section = c[6].strip()
        open_seats = c[-3].strip()
        max_seats = c[-4].strip()

        open_classes.add(COURSE_STRING.format(dept, catalog, section))

    closed_classes = all_classes - open_classes
    print 'closed classes:', closed_classes



if __name__ == '__main__':
    #update_courses('WN2013')
    update_courses('FA2012')
